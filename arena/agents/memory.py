"""Evidence-based episodic memory, scoped to one merchant and one run."""

import json

from arena.infrastructure.database import encode


class ExperienceStore:
    def __init__(self, database):
        self.db = database

    def recall(self, arena_id, merchant_id, before_round, market, store, limit=3):
        # No cross-match retrieval: development seeds and holdouts cannot contaminate each other.
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM experiences WHERE arena_id=? AND merchant_id=? AND round_number<? ORDER BY round_number DESC",
                                (arena_id, merchant_id, before_round)).fetchall()
        matches = []
        for row in rows:
            context = json.loads(row["context"])
            score = (3 if context["event"] == market["event"]["type"] else 0)
            score += 1 / (1 + abs(context["demand"] - market["total_demand"]) / max(1, market["total_demand"]))
            score += 1 / (1 + abs(context["cash_before"] - store["cash"]) / max(1, store["cash"]))
            # Older records have no stock feature; keep them searchable.
            if "stock_before" in context:
                stock = sum(item["quantity"] for item in store["inventory"])
                score += 1 / (1 + abs(context["stock_before"] - stock) / max(1, stock))
            outcome = json.loads(row["outcome"])
            lesson = f"售出 {outcome['sold']} 件，余货 {outcome['inventory']} 件。"
            if outcome["missed"]:
                lesson += f"{outcome['missed']} 个品类缺货，比较提高补货与提高价格的成本。"
            else:
                lesson += "没有品类缺货，结合余货评估补货规模。"
            if outcome["prediction_error"] is not None:
                direction = "高估" if outcome["prediction_error"] < 0 else "低估"
                lesson += f"当时预测{direction}收益 {abs(outcome['prediction_error']) / 100:.2f} 元；检验本轮条件是否相似。"
            matches.append({"evidence_id": row["id"], "round": row["round_number"], "similarity": round(score, 3),
                            "context": context, "action": json.loads(row["action"]), "outcome": outcome,
                            "lesson": lesson})
        return sorted(matches, key=lambda item: (item["similarity"], item["round"]), reverse=True)[:limit]

    def record(self, connection, arena_id, number, merchant, result, market):
        projection = result.get("trace", {}).get("projection")
        outcome = {**merchant["metrics"], "cash": merchant["cash"],
                   "inventory": sum(stock["quantity"] for stock in merchant["inventory"]),
                   "predicted_profit": projection["expected_profit"] if projection else None,
                   "prediction_error": merchant["metrics"]["profit"] - projection["expected_profit"] if projection else None}
        connection.execute("INSERT INTO experiences(arena_id,merchant_id,round_number,context,action,outcome) VALUES(?,?,?,?,?,?)",
                           (arena_id, merchant["id"], number, encode({"event": market["event"]["type"], "demand": market["total_demand"],
                                                                  "cash_before": result["observation"]["store"]["cash"],
                                                                  "stock_before": sum(stock["quantity"] for stock in result["observation"]["store"]["inventory"]),
                                                                  "prices": {stock["product_id"]: stock["price"] for stock in result["observation"]["store"]["inventory"]}}),
                            encode(result["plan"]), encode(outcome)))

    def listing(self, arena_id, merchant_id):
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM experiences WHERE arena_id=? AND merchant_id=? ORDER BY round_number DESC", (arena_id, merchant_id)).fetchall()
        return [{**dict(row), **{key: json.loads(row[key]) for key in ("context", "action", "outcome")}} for row in rows]
