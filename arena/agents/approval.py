"""Persisted human decisions consumed by the graph's interrupt/resume protocol."""

import json

from langgraph.types import interrupt

from arena.domain.models import Decision
from arena.domain.market import conditions
from arena.infrastructure.database import encode
from arena.infrastructure.events import emit


class ApprovalRequired(Exception):
    """The run is durably suspended; it is not a provider or execution failure."""


class ApprovalCoordinator:
    def __init__(self, database):
        self.db = database

    def gate(self, state):
        obs = state["observation"]
        policy = obs.get("approval_policy", "off")
        projection = state.get("projection", {})
        spend = sum(action["purchase_quantity"] * next(product["cost"] for product in obs["market"]["products"] if product["id"] == action["product_id"]) for action in state["decision"]["products"]) + state["decision"]["marketing_budget"]
        risky = spend > obs["store"]["cash"] * 0.35 or projection.get("worst_cash", obs["store"]["cash"]) < obs["market"]["rent"] * 2 or bool(projection.get("risks"))
        if policy == "off" or policy == "risk" and not risky or obs["store"]["bankrupt"]:
            return {"human_action": "not_required"}
        proposal = {"plan": state["decision"], "projection": projection, "spend": spend, "cash": obs["store"]["cash"], "revision": state.get("human_revisions", 0)}
        with self.db.connect() as conn:
            conn.execute("INSERT INTO approvals(arena_id,merchant_id,round_number,proposal,version) VALUES(?,?,?,?,?) ON CONFLICT(arena_id,merchant_id,round_number) DO UPDATE SET proposal=excluded.proposal,state=CASE WHEN approvals.state='replanning' THEN 'pending' ELSE approvals.state END,version=excluded.version",
                         (obs["arena_id"], obs["store"]["id"], obs["market"]["round"], encode(proposal), state.get("human_revisions", 0)))
            row = conn.execute("SELECT * FROM approvals WHERE arena_id=? AND merchant_id=? AND round_number=?", (obs["arena_id"], obs["store"]["id"], obs["market"]["round"])).fetchone()
        emit("approval", "waiting", "等待人工审批", approval_id=row["id"], **proposal)
        response = interrupt({"approval_id": row["id"], **proposal})
        action = response["action"]
        if action == "reject":
            emit("approval", "rejected", "人工退回重新规划", reason=response.get("reason", ""))
            revisions = state.get("human_revisions", 0) + 1
            if revisions > 3:
                raise ValueError("人工退回超过三次，请创建新的分叉运行")
            with self.db.connect() as conn:
                conn.execute("UPDATE approvals SET state='replanning',version=version+1,response=NULL,resolved_at=NULL WHERE id=?", (row["id"],))
            return {"human_action": "reject", "human_revisions": revisions,
                    "reviews": state.get("reviews", []) + [{"approved": False, "issues": [response.get("reason") or "人工要求重新规划"], "reason": "人工退回"}],
                    "revisions": state.get("revisions", 0) + 1}
        decision = Decision.model_validate(response["plan"]).model_dump() if action == "modify" else state["decision"]
        emit("approval", "resolved", "人工已修改方案" if action == "modify" else "人工已批准", plan=decision, reason=response.get("reason", ""))
        return {"decision": decision, "human_action": action, "human_response": response}

    def pending(self, arena_id):
        with self.db.connect() as conn:
            rows = conn.execute("SELECT a.*,m.name FROM approvals a JOIN merchants m ON m.id=a.merchant_id WHERE a.arena_id=? AND a.state='pending' ORDER BY a.id", (arena_id,)).fetchall()
        return [{**dict(row), "proposal": json.loads(row["proposal"])} for row in rows]

    def resolve(self, arena_id, approval_id, response):
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM approvals WHERE id=? AND arena_id=?", (approval_id, arena_id)).fetchone()
            if row is None:
                raise KeyError("审批不存在")
            if row["state"] != "pending":
                raise ValueError("审批已处理，请刷新")
            if response.get("version", 0) != row["version"]:
                raise ValueError("方案已重新生成，请刷新后审批最新版本")
            if response["action"] == "modify":
                proposal = json.loads(row["proposal"])
                arena = conn.execute("SELECT scenario,seed FROM arenas WHERE id=?", (arena_id,)).fetchone()
                market = conditions(arena["scenario"], arena["seed"], row["round_number"])
                plan = response["plan"]
                spend = plan["marketing_budget"] + sum(item["purchase_quantity"] * next(product["cost"] for product in market["products"] if product["id"] == item["product_id"]) for item in plan["products"])
                if spend > max(0, proposal["cash"] - market["rent"]):
                    raise ValueError("修改后的采购与营销超过扣除本轮租金后的可用现金")
            conn.execute("UPDATE approvals SET state='resolved',response=?,resolved_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (encode(response), approval_id))
            conn.execute("UPDATE arenas SET status='paused',updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=? AND status='awaiting_approval'", (arena_id,))
