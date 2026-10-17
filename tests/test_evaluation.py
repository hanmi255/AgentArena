import statistics
import json

from arena.agents.tool_records import BUDGET_EXHAUSTED
from arena.evaluation.metrics import confidence_interval
from tests.test_api import wait_completed
from tests.test_profiles import profile


def test_identical_strategy_variants_are_scored_separately_and_paired(client):
    result = client.post("/api/experiments", json={"name": "流程消融", "rounds": 3, "seeds": [11, 23, 37], "split": "holdout", "variants": [
        {"name": "直接决策", "strategy_id": "balanced", "mode": "rule", "workflow": "direct"},
        {"name": "试算审核", "strategy_id": "balanced", "mode": "rule", "workflow": "reviewed"},
    ]})
    assert result.status_code == 201, result.text
    experiment = result.json()
    client.post(f"/api/experiments/{experiment['id']}/run")
    for arena in experiment["arenas"]:
        wait_completed(client, arena["id"])
    report = client.get(f"/api/experiments/{experiment['id']}").json()
    assert report["status"] == "completed" and len(report["scores"]) == 2
    assert all(score["samples"] == 3 and score["confidence_interval"] for score in report["scores"])
    assert all(score["estimated_model_cost"] == 0 and score["total_tokens"] == 0 for score in report["scores"])
    assert all(score["tool_calls"] == 0 for score in report["scores"])
    baseline = next(score for score in report["scores"] if score["name"] == "直接决策")
    reviewed = next(score for score in report["scores"] if score["name"] == "试算审核")
    differences = [item["profit"] - next(base["profit"] for base in baseline["outcomes"] if base["seed"] == item["seed"]) for item in reviewed["outcomes"]]
    assert report["comparisons"][0]["average_difference"] == round(statistics.mean(differences))
    assert report["comparisons"][0]["confidence_interval"] == confidence_interval(differences)
    assert report["config"]["split"] == "holdout"


def test_model_experiment_snapshots_models_and_measures_tokens_and_cost(client, model_server):
    connection = profile(model_server)
    connection.update(thinking="disabled", input_price=2, output_price=5)
    saved = client.post("/api/model-profiles", json=connection).json()
    result = client.post("/api/experiments", json={"name": "模型对照", "rounds": 3, "seeds": [19], "variants": [
        {"name": "规则", "strategy_id": "balanced"},
        {"name": "模型", "strategy_id": "balanced", "mode": "llm", "model_profile_id": saved["id"]},
    ]}).json()
    connection["model"] = "changed-after-experiment"
    client.put(f"/api/model-profiles/{saved['id']}", json=connection)
    client.post(f"/api/experiments/{result['id']}/run")
    for arena in result["arenas"]:
        wait_completed(client, arena["id"])
    report = client.get(f"/api/experiments/{result['id']}").json()
    score = next(item for item in report["scores"] if item["name"] == "模型")
    assert score["model"] == "deepseek-flash" and score["total_tokens"] == 1920
    assert score["estimated_model_cost"] == 0.00528
    assert score["confidence_interval"] is None
    assert "profile-secret" not in str(report)
    # Old traces lack execution flags; a rejected request is not a tool execution.
    with client.app.state.service.db.connect() as conn:
        row = conn.execute("SELECT d.id,d.tools FROM decisions d JOIN merchants m ON m.id=d.merchant_id WHERE m.arena_id=? AND m.mode='llm' LIMIT 1", (result["arenas"][0]["id"],)).fetchone()
        records = json.loads(row["tools"]) + [{"name": "inspect_store", "arguments": {}, "result": BUDGET_EXHAUSTED}]
        conn.execute("UPDATE decisions SET tools=? WHERE id=?", (json.dumps(records), row["id"]))
        conn.execute("UPDATE decisions SET tools=? WHERE merchant_id IN (SELECT id FROM merchants WHERE arena_id=? AND mode='rule')", (json.dumps(records), result["arenas"][0]["id"]))
    updated = client.get(f"/api/experiments/{result['id']}").json()
    assert next(item for item in updated["scores"] if item["name"] == "模型")["tool_calls"] == score["tool_calls"]
    assert next(item for item in updated["scores"] if item["name"] == "规则")["tool_calls"] == 0


def test_repeated_seeds_and_insufficient_variants_are_rejected(client):
    assert client.post("/api/experiments", json={"name": "重复种子", "strategy_ids": ["balanced", "discount"], "seeds": [11, 11]}).status_code == 422
    assert client.post("/api/experiments", json={"name": "无对照"}).status_code == 422


def test_development_and_holdout_seeds_cannot_overlap(client):
    config = {"name": "开发", "strategy_ids": ["balanced", "discount"], "seeds": [11, 23], "split": "development"}
    assert client.post("/api/experiments", json=config).status_code == 201
    config.update(name="保留集", split="holdout", seeds=[23, 37])
    assert client.post("/api/experiments", json=config).status_code == 400
    config["seeds"] = [101, 203]
    assert client.post("/api/experiments", json=config).status_code == 201
