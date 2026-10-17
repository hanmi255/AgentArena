"""Measured outcomes and paired comparisons; model prices are user-supplied estimates."""

import json
import math
import statistics
from collections import defaultdict
from arena.agents.tool_records import tool_records


T_CRITICAL = [0, 12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262,
              2.228, 2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093,
              2.086, 2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042]


def confidence_interval(values):
    if len(values) < 2:
        return None
    critical = T_CRITICAL[min(len(values) - 1, 30)]
    margin = critical * statistics.stdev(values) / math.sqrt(len(values))
    mean = statistics.mean(values)
    return [round(mean - margin), round(mean + margin)]


def evaluate_experiment(database, matches, config):
    samples = defaultdict(list)
    wins = defaultdict(float)
    profiles = config["variants"]
    per_seed = defaultdict(dict)
    completed = [arena for arena in matches if arena["status"] == "completed"]
    for arena in completed:
        with database.connect() as connection:
            rounds = [json.loads(row["snapshot"]) for row in connection.execute("SELECT snapshot FROM rounds WHERE arena_id=? ORDER BY number", (arena["id"],))]
            decisions = [dict(row) for row in connection.execute("SELECT merchant_id,input_tokens,output_tokens,duration_ms,model_config,trace,tools FROM decisions WHERE arena_id=? ORDER BY round_number", (arena["id"],))]
        highest = max(item["profit"] for item in arena["merchants"])
        winners = [item for item in arena["merchants"] if item["profit"] == highest]
        for merchant in winners:
            wins[merchant["entrant_id"]] += 1 / len(winners)
        for merchant in arena["merchants"]:
            own = [item for item in decisions if item["merchant_id"] == merchant["id"]]
            traces = [json.loads(item["trace"]) for item in own]
            trajectory = [next(item for item in snapshot["merchants"] if item["id"] == merchant["id"]) for snapshot in rounds]
            errors = [abs(store["metrics"]["profit"] - trace["projection"]["expected_profit"]) for store, trace in zip(trajectory[1:], traces) if trace.get("projection")]
            peak = trajectory[0]["equity"]
            drawdown = 0
            for item in trajectory:
                peak = max(peak, item["equity"])
                drawdown = max(drawdown, (peak - item["equity"]) / peak * 100)
            model_config = merchant.get("model_config", {})
            priced = merchant["mode"] == "rule" or bool(model_config.get("input_price") or model_config.get("output_price"))
            input_tokens = sum(item["input_tokens"] for item in own)
            output_tokens = sum(item["output_tokens"] for item in own)
            cost = (input_tokens * model_config.get("input_price", 0) + output_tokens * model_config.get("output_price", 0)) / 1000000 if priced else None
            inventory = statistics.mean(sum(stock["book_value"] for stock in item["inventory"]) for item in trajectory)
            sample = {"seed": arena["seed"], "profit": merchant["profit"], "bankrupt": merchant["bankrupt"],
                      "input_tokens": input_tokens, "output_tokens": output_tokens, "model_cost": cost,
                      "duration_ms": sum(item["duration_ms"] for item in own), "drawdown": round(drawdown, 2),
                      "stockout_rate": sum(item["metrics"]["missed"] for item in trajectory[1:]) / (len(trajectory[1:]) * 3) * 100,
                      "turnover": sum(item["metrics"]["cost_of_goods"] for item in trajectory[1:]) / inventory if inventory else 0,
                      "revisions": sum(trace.get("revisions", 0) for trace in traces),
                      "tool_calls": sum(record["executed"] for item in own for record in tool_records(json.loads(item["tools"]))) if merchant["mode"] == "llm" else 0,
                      "memory_references": sum(len(trace.get("memory", [])) for trace in traces),
                      "prediction_mae": round(statistics.mean(errors)) if errors else None,
                      "negotiation_savings": sum((contract["reference_price"] - contract["unit_price"]) * contract["quantity"] for trace in traces for contract in trace.get("negotiation", {}).get("contracts", [])),
                      "contracts": sum(len(trace.get("negotiation", {}).get("contracts", [])) for trace in traces)}
            samples[merchant["entrant_id"]].append(sample)
            per_seed[arena["seed"]][merchant["entrant_id"]] = merchant["profit"]
    scores = []
    for index, variant in enumerate(profiles):
        items = samples[variant["id"]]
        values = [item["profit"] for item in items]
        mean = round(statistics.mean(values)) if values else 0
        costs = [item["model_cost"] for item in items]
        scores.append({"strategy_id": variant["id"], "variant_id": variant["id"], "name": variant["name"], "color": ["violet", "orange", "teal", "blue"][index],
                       "model": variant["model_config"].get("model", "规则策略"), "workflow": variant["workflow"], "samples": len(items),
                       "average_profit": mean, "deviation": round(statistics.pstdev(values)) if values else 0,
                       "confidence_interval": confidence_interval(values), "win_rate": round(wins[variant["id"]] / len(items) * 100, 1) if items else 0,
                       "bankruptcy_rate": round(sum(item["bankrupt"] for item in items) / len(items) * 100, 1) if items else 0,
                       "total_tokens": sum(item["input_tokens"] + item["output_tokens"] for item in items),
                       "average_duration_ms": round(statistics.mean(item["duration_ms"] / config["rounds"] for item in items)) if items else 0,
                       "estimated_model_cost": round(sum(costs), 6) if items and all(cost is not None for cost in costs) else None,
                       "average_drawdown": round(statistics.mean(item["drawdown"] for item in items), 2) if items else 0,
                       "stockout_rate": round(statistics.mean(item["stockout_rate"] for item in items), 1) if items else 0,
                       "inventory_turnover": round(statistics.mean(item["turnover"] for item in items), 2) if items else 0,
                       "revisions": sum(item["revisions"] for item in items),
                       "tool_calls": sum(item["tool_calls"] for item in items), "memory_references": sum(item["memory_references"] for item in items),
                       "prediction_mae": round(statistics.mean(item["prediction_mae"] for item in items if item["prediction_mae"] is not None)) if any(item["prediction_mae"] is not None for item in items) else None,
                       "negotiation_savings": sum(item["negotiation_savings"] for item in items), "contracts": sum(item["contracts"] for item in items), "outcomes": items})
    comparisons = []
    baseline = profiles[0]
    for variant in profiles[1:]:
        differences = [values[variant["id"]] - values[baseline["id"]] for values in per_seed.values()]
        comparisons.append({"baseline": baseline["name"], "variant": variant["name"], "samples": len(differences),
                            "average_difference": round(statistics.mean(differences)) if differences else 0,
                            "confidence_interval": confidence_interval(differences)})
    return {"scores": sorted(scores, key=lambda item: item["average_profit"], reverse=True), "comparisons": comparisons}
