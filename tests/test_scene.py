import json

from arena.agents.context import decision_context
from tests.test_model import ModelHandler, configure


def test_public_settlement_events_reconstruct_every_store(client, arena_config):
    arena = client.post("/api/arenas", json=arena_config).json()
    path = f"/api/arenas/{arena['id']}"
    for number in range(2):
        response = client.post(path + "/step", json={"expected_round": number})
        assert response.status_code == 200
        state = response.json()["snapshot"]
        events = client.get(path + f"/timeline?round={number + 1}").json()
        settled = [item for item in events if item["node"] == "settle"]
        assert len(settled) == len(arena_config["merchants"])
        for event in settled:
            merchant = next(item for item in state["merchants"] if item["id"] == event["merchant_id"])
            assert event["payload"]["merchant"] == merchant
        assert next(item["payload"]["market"] for item in events if "market" in item["payload"]) == state["market"]
        if number:
            prior = client.get(path + "/timeline?round=1").json()
            snapshot = client.get(path + "?round=1").json()["snapshot"]
            assert [item["payload"]["merchant"] for item in prior if item["node"] == "settle"] == snapshot["merchants"]


def test_model_context_preserves_business_facts_without_ui_or_connection_metadata(client, arena_config):
    arena = client.post("/api/arenas", json=arena_config).json()
    service = client.app.state.service
    store = arena["snapshot"]["merchants"][0]
    observation = service.observation(service.db.arena(arena["id"]), arena["snapshot"], store, arena["snapshot"]["market"])
    context = decision_context(observation)
    assert context["store"]["inventory"] == store["inventory"]
    assert context["store"]["cash"] == store["cash"]
    assert context["competitors"] == observation["competitors"]
    assert "model_config" not in context["store"] and "color" not in context["store"]
    assert all("base_demand" not in item for item in context["market"]["products"])
    assert len(json.dumps(context)) < len(json.dumps(observation))


def test_planner_usage_is_reported_in_public_events(client, arena_config, model_server):
    configure(client, model_server)
    arena_config["merchants"][0]["mode"] = "llm"
    arena = client.post("/api/arenas", json=arena_config).json()
    path = f"/api/arenas/{arena['id']}"
    result = client.post(path + "/step", json={"expected_round": 0})
    assert result.status_code == 200, result.text
    decision = result.json()["decisions"][0]
    events = client.get(path + "/timeline").json()
    calls = [item for item in events if item["merchant_id"] == decision["merchant_id"] and item["status"] == "model_completed"]
    assert sum(item["payload"]["input_tokens"] for item in calls) == decision["input_tokens"]
    assert sum(item["payload"]["output_tokens"] for item in calls) == decision["output_tokens"]


def test_adaptive_planning_expands_candidates_only_when_risky(client, arena_config):
    for merchant in arena_config["merchants"]:
        merchant["workflow"] = "adaptive"
    arena = client.post("/api/arenas", json=arena_config).json()
    service = client.app.state.service
    store = arena["snapshot"]["merchants"][0]
    obs = service.observation(service.db.arena(arena["id"]), arena["snapshot"], store, arena["snapshot"]["market"])
    state = {"observation": obs, "strategy": service.db.strategy("balanced"), "workflow": "adaptive", "mode": "rule", "input_tokens": 0, "output_tokens": 0, "stages": [], "routing": {"review_required": False}}
    assert len(service.agents.decide(state)["candidates"]) == 1
    state["routing"]["review_required"] = True
    assert len(service.agents.decide(state)["candidates"]) == 2
    state["routing"]["review_required"] = False
    state["revisions"] = 1
    assert len(service.agents.decide(state)["candidates"]) == 2


def test_experience_recall_matches_cash_stock_and_explains_prediction_error(client, arena_config):
    arena = client.post("/api/arenas", json=arena_config).json()
    service = client.app.state.service
    store = arena["snapshot"]["merchants"][0]
    market = arena["snapshot"]["market"]
    stock = sum(item["quantity"] for item in store["inventory"])
    outcome = {"sold": 10, "inventory": 5, "missed": 1, "prediction_error": -2500}
    with service.db.connect() as conn:
        for number, cash, quantity in [(1, store["cash"], stock), (2, 1, 9999)]:
            conn.execute("INSERT INTO experiences(arena_id,merchant_id,round_number,context,action,outcome) VALUES(?,?,?,?,?,?)",
                         (arena["id"], store["id"], number, json.dumps({"event": market["event"]["type"], "demand": market["total_demand"], "cash_before": cash, "stock_before": quantity}), "{}", json.dumps(outcome)))
    memories = service.memory.recall(arena["id"], store["id"], 3, market, store)
    assert [item["round"] for item in memories] == [1, 2]
    assert "高估收益 25.00 元" in memories[0]["lesson"]
    assert "1 个品类缺货" in memories[0]["lesson"]
    assert service.memory.recall(arena["id"], store["id"], 1, market, store) == []


def test_review_revisions_share_one_tool_budget(client, arena_config, model_server):
    configure(client, model_server)
    arena_config["merchants"][0].update(mode="llm", workflow="reviewed", agent_options={"tool_budget": 3})
    arena = client.post("/api/arenas", json=arena_config).json()
    ModelHandler.review_rejections = 1
    path = f"/api/arenas/{arena['id']}"
    result = client.post(path + "/step", json={"expected_round": 0})
    assert result.status_code == 200, result.text
    decision = result.json()["decisions"][0]
    events = client.get(path + "/timeline").json()
    calls = [event for event in events if event["merchant_id"] == decision["merchant_id"] and event["status"] == "tool_completed"]
    assert len(calls) == 3
    assert decision["trace"]["revisions"] == 1
    usage = [event["payload"] for event in events if event["merchant_id"] == decision["merchant_id"] and event["status"] == "model_completed"]
    assert sum(item["input_tokens"] for item in usage) == decision["input_tokens"]


def test_fork_remaps_embedded_settlement_snapshots(client, arena_config):
    original = client.post("/api/arenas", json=arena_config).json()
    path = f"/api/arenas/{original['id']}"
    assert client.post(path + "/step", json={"expected_round": 0}).status_code == 200
    fork = client.post(path + "/fork", json={"round": 1}).json()
    events = client.get(f"/api/arenas/{fork['id']}/timeline").json()
    settlements = [event for event in events if event["node"] == "settle"]
    assert len(settlements) == len(fork["snapshot"]["merchants"])
    for event in settlements:
        assert event["payload"]["merchant"]["id"] == event["merchant_id"]
        expected = next(store for store in fork["snapshot"]["merchants"] if store["id"] == event["merchant_id"])
        assert event["payload"]["merchant"]["cash"] == expected["cash"]
