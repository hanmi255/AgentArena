import copy
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from fastapi.testclient import TestClient

from arena.api.app import create_app
from tests.test_model import ModelHandler, configure
from arena.agents.engine import rule_decision
from arena.execution.tasks import TaskStore, LeaseLost
from arena.domain.market import settle


def configured(client, config, approval="off"):
    config = copy.deepcopy(config)
    config["approval_policy"] = approval
    for merchant in config["merchants"]:
        merchant.update(workflow="adaptive", agent_options={"memory": "episodic", "negotiation": True, "tool_budget": 4})
    return client.post("/api/arenas", json=config).json()


def test_real_events_negotiation_delivery_and_scoped_memory(client, arena_config):
    arena = configured(client, arena_config)
    path = f"/api/arenas/{arena['id']}"
    for number in range(3):
        response = client.post(path + "/step", json={"expected_round": number})
        assert response.status_code == 200, response.text
        arena = response.json()
        for decision in arena["decisions"]:
            contracts = decision["trace"]["negotiation"]["contracts"]
            assert contracts
            ledger = client.get(path + f"/ledger?round={number+1}&merchant={decision['merchant_id']}").json()
            for contract in contracts:
                deliveries = [item for item in ledger if item["kind"] == "purchase" and item["product_id"] == contract["product_id"]]
                assert sum(item["quantity"] for item in deliveries) == contract["quantity"]
                assert sum(item["amount"] for item in deliveries) == -contract["quantity"] * contract["unit_price"]
            assert all(memory["round"] <= number for memory in decision["trace"]["memory"])
            if number:
                assert decision["trace"]["memory"]
    events = client.get(path + "/timeline?limit=1000").json()
    assert len(events) > 100
    assert {"route", "decide", "simulate", "negotiate", "settle"} <= {event["node"] for event in events}
    cursor = events[10]["id"]
    assert client.get(path + f"/timeline?after={cursor}&limit=2").json() == events[11:13]
    assert all(event["round_number"] == 2 for event in client.get(path + "/timeline?round=2").json())
    with client.app.state.database.connect() as conn:
        for product in arena["snapshot"]["market"]["products"]:
            total = conn.execute("SELECT SUM(quantity) FROM supplier_reservations WHERE arena_id=? AND round_number=3 AND product_id=?", (arena["id"], product["id"])).fetchone()[0]
            assert total <= product["supply"]
        assert not conn.execute("SELECT 1 FROM supplier_reservations WHERE status='reserved'").fetchone()


def test_approval_survives_restart_and_modified_plan_is_settled_once(tmp_path, arena_config):
    with TestClient(create_app(tmp_path, seed_demo=False)) as client:
        arena = configured(client, arena_config, "all")
        path = f"/api/arenas/{arena['id']}"
        arena = client.post(path + "/step", json={"expected_round": 0}).json()
        assert arena["status"] == "awaiting_approval"
        assert arena["current_round"] == 0
        assert client.get(path + "/ledger").json() == []
        assert client.post(path + "/run", json={"interval": 0}).status_code == 409
    with TestClient(create_app(tmp_path, seed_demo=False)) as client:
        arena = client.get(path).json()
        first = arena["approvals"][0]
        plan = first["proposal"]["plan"]
        plan["marketing_budget"] = 0
        for item in plan["products"]:
            item["purchase_quantity"] = 5
        response = client.post(path + f"/approvals/{first['id']}", json={"action": "modify", "plan": plan, "reason": "人工限制采购"})
        assert response.status_code == 200, response.text
        arena = response.json()
        while arena["approvals"]:
            approval = arena["approvals"][0]
            arena = client.post(path + f"/approvals/{approval['id']}", json={"action": "approve"}).json()
        assert arena["current_round"] == 1
        chosen = next(item for item in arena["decisions"] if item["merchant_id"] == first["merchant_id"])
        assert chosen["plan"] == plan
        assert client.post(path + f"/approvals/{first['id']}", json={"action": "approve"}).status_code == 400
        assert client.post(path + "/step", json={"expected_round": 0}).status_code == 409
        ledger = client.get(path + "/ledger").json()
        assert len({(item["round_number"], item["merchant_id"], item["kind"], item["product_id"]) for item in ledger}) == len(ledger)


def test_human_rejection_replans_and_requires_another_approval(client, arena_config):
    arena = configured(client, arena_config, "all")
    path = f"/api/arenas/{arena['id']}"
    arena = client.post(path + "/step", json={"expected_round": 0}).json()
    approval = arena["approvals"][0]
    response = client.post(path + f"/approvals/{approval['id']}", json={"action": "reject", "reason": "降低采购量"})
    assert response.status_code == 200, response.text
    arena = response.json()
    assert arena["status"] == "awaiting_approval" and arena["current_round"] == 0
    assert arena["approvals"][0]["proposal"]["plan"]
    assert arena["approvals"][0]["version"] == 1
    assert client.post(path + f"/approvals/{approval['id']}", json={"action": "approve", "version": 0}).status_code == 400
    events = client.get(path + "/timeline").json()
    assert sum(event["node"] == "decide" and event["status"] == "completed" for event in events) == 2
    assert client.get(path + "/ledger").json() == []


def test_human_modification_must_reserve_rent(client, arena_config):
    arena_config["initial_capital"] = 300000
    arena = configured(client, arena_config, "all")
    path = f"/api/arenas/{arena['id']}"
    arena = client.post(path + "/step", json={"expected_round": 0}).json()
    approval = arena["approvals"][0]
    plan = copy.deepcopy(approval["proposal"]["plan"])
    for action in plan["products"]:
        action["purchase_quantity"] = 250
    # Still within schema limits, but cannot afford procurement plus rent.
    response = client.post(path + f"/approvals/{approval['id']}", json={"action": "modify", "plan": plan})
    assert response.status_code == 400
    assert "可用现金" in response.json()["detail"]
    assert client.get(path + "/ledger").json() == []


def test_counterfactual_fork_keeps_history_state_seed_and_independent_future(client, arena_config):
    arena = configured(client, arena_config)
    path = f"/api/arenas/{arena['id']}"
    for number in range(3):
        assert client.post(path + "/step", json={"expected_round": number}).status_code == 200
    original = client.get(path).json()
    point = client.get(path + "?round=1").json()
    fork = client.post(path + "/fork", json={"round": 1}).json()
    assert fork["current_round"] == 1 and fork["seed"] == original["seed"]
    assert [item["cash"] for item in fork["snapshot"]["merchants"]] == [item["cash"] for item in point["snapshot"]["merchants"]]
    assert [item["inventory"] for item in fork["snapshot"]["merchants"]] == [item["inventory"] for item in point["snapshot"]["merchants"]]
    assert fork["parent_arena_id"] == arena["id"]
    result = client.post(f"/api/arenas/{fork['id']}/step", json={"expected_round": 1})
    assert result.status_code == 200, result.text
    replay = result.json()
    assert all(decision["trace"]["memory"] for decision in replay["decisions"])
    original_next = client.get(path + "?round=2").json()
    for old, new in zip(original_next["snapshot"]["merchants"], replay["snapshot"]["merchants"]):
        for field in ["cash", "inventory", "profit", "metrics"]:
            assert new[field] == old[field]
    comparison = client.get(f"/api/arenas/{fork['id']}/comparison").json()
    assert comparison["points"][-1]["round"] == 2
    assert client.get(path).json()["snapshot"] == original["snapshot"]


def test_no_memory_and_no_cross_arena_evidence(client, arena_config):
    first = configured(client, arena_config)
    client.post(f"/api/arenas/{first['id']}/step", json={"expected_round": 0})
    second = configured(client, arena_config)
    result = client.post(f"/api/arenas/{second['id']}/step", json={"expected_round": 0}).json()
    assert all(not item["trace"]["memory"] for item in result["decisions"])
    config = copy.deepcopy(arena_config)
    for merchant in config["merchants"]:
        merchant["agent_options"] = {"memory": "none"}
    third = client.post("/api/arenas", json=config).json()
    for number in range(2):
        result = client.post(f"/api/arenas/{third['id']}/step", json={"expected_round": number}).json()
    assert all(not item["observation"]["history"] and not item["observation"]["store"]["memory"] and not item["trace"]["memory"] for item in result["decisions"])


def test_llm_dynamic_tools_and_independent_negotiation_contexts(client, arena_config, model_server):
    configure(client, model_server)
    arena_config["merchants"][0]["mode"] = "llm"
    arena = configured(client, arena_config)
    result = client.post(f"/api/arenas/{arena['id']}/step", json={"expected_round": 0})
    assert result.status_code == 200, result.text
    decision = result.json()["decisions"][0]
    assert len(decision["tools"]) == 1
    assert decision["tools"][0]["name"] == "inspect_store"
    assert not decision["trace"]["reviews"]
    assert decision["trace"]["negotiation"]["contracts"]
    assert "private protocol state" not in json.dumps(client.get(f"/api/arenas/{arena['id']}/timeline").json())
    suppliers = [item for item in ModelHandler.requests if "你是独立供应商" in str(item["messages"][0]["content"])]
    buyers = [item for item in ModelHandler.requests if "你代表商店采购" in str(item["messages"][0]["content"])]
    assert suppliers and buyers
    supplier_data = json.loads(next(item["content"] for item in suppliers[0]["messages"] if item["role"] == "user"))
    buyer_data = json.loads(next(item["content"] for item in buyers[0]["messages"] if item["role"] == "user"))
    assert "floor" in supplier_data["private"] and "available_cash" not in supplier_data["private"]
    assert "floor" not in buyer_data["private"] and "available_cash" in buyer_data["private"]


def test_selection_requires_untouched_seeds_and_enforces_validation_budget(client):
    config = {"name": "能力消融", "scenario": "festival", "rounds": 3, "seeds": [11], "split": "development", "variants": [
        {"name": "无记忆", "strategy_id": "balanced", "workflow": "adaptive", "agent_options": {"memory": "none"}},
        {"name": "经验与谈判", "strategy_id": "balanced", "workflow": "adaptive", "agent_options": {"memory": "episodic", "negotiation": True}},
    ]}
    experiment = client.post("/api/experiments", json=config).json()
    service = client.app.state.service
    for arena in experiment["arenas"]:
        for number in range(3):
            service.advance(arena["id"], number)
        service.db.set_status(arena["id"], "completed")
    result = client.get(f"/api/experiments/{experiment['id']}").json()
    assert all(score["prediction_mae"] is not None for score in result["scores"])
    assert next(score for score in result["scores"] if score["name"] == "经验与谈判")["memory_references"] > 0
    assert client.post(f"/api/experiments/{experiment['id']}/select", json={"seeds": [11]}).status_code == 400
    assert client.post(f"/api/experiments/{experiment['id']}/select", json={"seeds": [101, 211], "round_budget": 6}).status_code == 400
    response = client.post(f"/api/experiments/{experiment['id']}/select", json={"seeds": [101], "round_budget": 6})
    assert response.status_code == 201, response.text
    validation = response.json()
    assert validation["config"]["selection"]["development_id"] == experiment["id"]
    assert validation["config"]["seeds"] == [101]
    assert validation["config"]["split"] == "holdout"


def test_competing_negotiations_reserve_atomically_and_expired_contracts_cannot_settle(client, arena_config):
    arena = configured(client, arena_config)
    service = client.app.state.service
    with service.db.connect() as conn:
        conn.execute("UPDATE arenas SET supply_policy='sequential_v1' WHERE id=?", (arena["id"],))
    states = []
    for merchant in arena["snapshot"]["merchants"]:
        market = copy.deepcopy(arena["snapshot"]["market"])
        for product in market["products"]:
            product["supply"] = 1
        obs = service.observation(service.db.arena(arena["id"]), arena["snapshot"], merchant, market)
        plan = rule_decision(obs, service.db.strategy(merchant["strategy_id"])).model_dump()
        for action in plan["products"]:
            action["purchase_quantity"] = 10
        states.append({"observation": obs, "decision": plan, "mode": "rule", "thread_id": f"reservation-{merchant['id']}"})
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(service.agents.negotiator.run, states))
    for product in ["coffee", "oats", "bar"]:
        assert sum(item["quantity"] for result in results for item in result["contracts"] if item["product_id"] == product) == 1
    assert service.agents.negotiator.run(states[0]) == results[0]
    contracts = {state["observation"]["store"]["id"]: {item["product_id"]: item for item in result["contracts"]} for state, result in zip(states, results)}
    for items in contracts.values():
        for item in items.values():
            item["expires_round"] = 0
    with pytest.raises(ValueError, match="过期"):
        settle(arena["snapshot"], {state["observation"]["store"]["id"]: state["decision"] for state in states}, states[0]["observation"]["market"], arena["initial_capital"], arena["seed"], contracts)


def test_lost_worker_cannot_reserve_supplier_stock(client, arena_config):
    arena = configured(client, arena_config)
    service = client.app.state.service
    store = TaskStore(service.db)
    job = store.claim("expired", store.enqueue(arena["id"], 0))
    with service.db.connect() as conn:
        conn.execute("UPDATE execution_jobs SET lease_until=0 WHERE id=?", (job["id"],))
    merchant = arena["snapshot"]["merchants"][0]
    obs = service.observation(service.db.arena(arena["id"]), arena["snapshot"], merchant, arena["snapshot"]["market"])
    with pytest.raises(LeaseLost):
        service.agents.negotiator.run({"observation": obs, "decision": rule_decision(obs, service.db.strategy(merchant["strategy_id"])).model_dump(), "mode": "rule", "thread_id": "old-worker"}, job)
    with service.db.connect() as conn:
        assert not conn.execute("SELECT 1 FROM supplier_reservations").fetchone()


def test_buyer_model_cannot_expand_an_approved_purchase_quantity(client, arena_config, model_server):
    configure(client, model_server)
    ModelHandler.invalid_buyer_quantity = True
    arena_config["merchants"][0]["mode"] = "llm"
    arena = configured(client, arena_config)
    response = client.post(f"/api/arenas/{arena['id']}/step", json={"expected_round": 0})
    assert response.status_code == 200, response.text
    negotiation = response.json()["decisions"][0]["trace"]["negotiation"]
    assert not negotiation["contracts"]
    assert all(session["messages"][-1]["action"] == "reject" for session in negotiation["messages"])
