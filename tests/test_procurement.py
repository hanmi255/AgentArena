import copy
import json
import sqlite3
from itertools import permutations

import pytest

from arena.agents.engine import rule_decision
from arena.domain.market import settle
from arena.domain.models import ArenaInput
from arena.domain.models import ExperimentInput
from arena.domain.procurement import LEGACY_POLICY, POLICY, allocate_orders
from arena.domain.simulation import simulate_plan
from tests.test_decision_upgrade import configured
from tests.test_model import configure, ModelHandler


def example(client, arena_config, quantities=(100, 80, 60), supply=120):
    arena = client.post("/api/arenas", json=arena_config).json()
    market = copy.deepcopy(arena["snapshot"]["market"])
    for product in market["products"]:
        product["supply"] = supply if product["id"] == "coffee" else 0
    plans = {}
    for merchant, quantity in zip(arena["snapshot"]["merchants"], quantities):
        plans[merchant["id"]] = {"products": [{"product_id": p["id"], "price": 10000, "purchase_quantity": quantity if p["id"] == "coffee" else 0} for p in market["products"]],
                                 "marketing_budget": 2000, "summary": "测试", "memory": "测试"}
    return arena, market, plans


def test_proportional_example_is_independent_of_execution_order(client, arena_config):
    arena, market, plans = example(client, arena_config)
    ids = list(plans)
    agreements = {i: {"coffee": {"quantity": q, "unit_price": price, "expires_round": 1}}
                  for i, q, price in zip(ids, [100, 80, 60], [880, 860, 890])}
    before = copy.deepcopy(agreements)
    for order in permutations(arena["snapshot"]["merchants"]):
        previous = {**arena["snapshot"], "merchants": list(order)}
        allocated = allocate_orders(previous, plans, market, agreements, 42)
        assert [allocated[i]["coffee"]["quantity"] for i in ids] == [50, 40, 30]
        assert [allocated[i]["coffee"]["quantity"] * allocated[i]["coffee"]["unit_price"] for i in ids] == [44000, 34400, 26700]
    assert agreements == before


def test_remainders_rotate_and_mixed_modes_share_one_pool(client, arena_config):
    arena, market, plans = example(client, arena_config, (1, 1, 1), 1)
    ids = list(plans)
    winners = []
    for number in [1, 2, 3]:
        market["round"] = number
        agreements = {ids[0]: {"coffee": {"quantity": 1, "unit_price": 900, "expires_round": number}}}
        allocated = allocate_orders(arena["snapshot"], plans, market, agreements, 42)
        assert sum(items["coffee"]["quantity"] for items in allocated.values()) == 1
        winners.append(next(i for i, items in allocated.items() if items["coffee"]["quantity"]))
    assert set(winners) == set(ids)


def test_rejection_zero_supply_bankruptcy_and_oversized_requests(client, arena_config):
    arena, market, plans = example(client, arena_config, (250, 250, 250), 4)
    ids = list(plans)
    arena["snapshot"]["merchants"][2]["bankrupt"] = True
    allocated = allocate_orders(arena["snapshot"], plans, market, {ids[0]: {}}, 42)
    assert allocated[ids[0]] == allocated[ids[2]] == {}
    assert allocated[ids[1]]["coffee"]["quantity"] == 4
    assert allocated[ids[1]]["coffee"]["requested_quantity"] == 4
    market["products"][0]["supply"] = 0
    assert all(not items for items in allocate_orders(arena["snapshot"], plans, market, {}, 42).values())


def test_final_price_budget_reserves_marketing_and_rent(client, arena_config):
    arena, market, plans = example(client, arena_config, (100, 0, 0))
    merchant = arena["snapshot"]["merchants"][0]
    merchant["cash"] = market["rent"] + 2000 + 4500
    agreements = {merchant["id"]: {"coffee": {"quantity": 100, "unit_price": 1500, "expires_round": 1}}}
    allocated = allocate_orders(arena["snapshot"], plans, market, agreements, 42)
    assert allocated[merchant["id"]]["coffee"]["quantity"] == 3
    result, ledger = settle(arena["snapshot"], plans, market, arena["initial_capital"], 42, allocated, reserve_marketing=True)
    own = [e for e in ledger if e["merchant_id"] == merchant["id"]]
    assert next(e for e in own if e["kind"] == "marketing")["amount"] == -2000
    assert next(e for e in own if e["kind"] == "operations")["amount"] <= -market["rent"]
    assert result["merchants"][0]["cash"] >= 0
    agreements[merchant["id"]]["coffee"]["quantity"] = 101
    with pytest.raises(ValueError, match="批准"):
        allocate_orders(arena["snapshot"], plans, market, agreements, 42)
    agreements[merchant["id"]]["coffee"].update(quantity=100, expires_round=0)
    with pytest.raises(ValueError, match="过期"):
        allocate_orders(arena["snapshot"], plans, market, agreements, 42)


def test_negotiation_only_saves_intents_and_zero_supply_skips_model(client, arena_config, model_server):
    configure(client, model_server)
    arena = configured(client, arena_config)
    service = client.app.state.service
    states = []
    for merchant in arena["snapshot"]["merchants"]:
        market = copy.deepcopy(arena["snapshot"]["market"])
        for product in market["products"]:
            product["supply"] = 3
        obs = service.observation(service.db.arena(arena["id"]), arena["snapshot"], merchant, market)
        plan = rule_decision(obs, service.db.strategy(merchant["strategy_id"])).model_dump()
        for action in plan["products"]:
            action["purchase_quantity"] = 3
        states.append({"observation": obs, "decision": plan, "mode": "rule", "thread_id": f"intent-{merchant['id']}"})
    results = [service.agents.negotiator.run(state) for state in states]
    assert all(c["quantity"] == 3 and c["status"] == "pending_allocation" for r in results for c in r["contracts"])
    with service.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM supplier_reservations").fetchone()[0] == 0
    assert service.agents.negotiator.run(states[0]) == results[0]
    fresh = configured(client, arena_config)
    merchant = fresh["snapshot"]["merchants"][0]
    market = fresh["snapshot"]["market"]
    for product in market["products"]:
        product["supply"] = 0
    state = copy.deepcopy(states[0])
    state.update(mode="llm", observation=service.observation(service.db.arena(fresh["id"]), fresh["snapshot"], merchant, market))
    calls = len(ModelHandler.requests)
    assert service.agents.negotiator.run(state)["contracts"] == []
    assert len(ModelHandler.requests) == calls


def test_allocation_and_ledger_rollback_together_and_retry_once(client, arena_config):
    arena = configured(client, arena_config)
    db = client.app.state.database
    with db.connect() as conn:
        conn.execute("CREATE TRIGGER fail_settlement BEFORE INSERT ON ledger BEGIN SELECT RAISE(ABORT, 'interrupted settlement'); END")
    with pytest.raises(sqlite3.IntegrityError, match="interrupted settlement"):
        client.app.state.service.advance(arena["id"], 0)
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM supplier_reservations").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM ledger").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM negotiation_sessions").fetchone()[0] == 3
        conn.execute("DROP TRIGGER fail_settlement")
    path = f"/api/arenas/{arena['id']}"
    response = client.post(path + "/step", json={"expected_round": 0})
    assert response.status_code == 200, response.text
    snapshot = response.json()["snapshot"]
    ledger = client.get(path + "/ledger").json()
    for merchant in snapshot["merchants"]:
        for delivery in merchant["procurement"]:
            entries = [e for e in ledger if e["merchant_id"] == merchant["id"] and e["kind"] == "purchase" and e["product_id"] == delivery["product_id"]]
            assert delivery["quantity"] == sum(e["quantity"] for e in entries)
            if entries:
                assert -entries[0]["amount"] == delivery["quantity"] * delivery["unit_price"]
        metrics = merchant["metrics"]
        assert metrics["profit"] == metrics["revenue"] - metrics["cost_of_goods"] - metrics["marketing"] - metrics["operating_cost"]
    assert client.post(path + "/step", json={"expected_round": 0}).status_code == 409
    assert client.get(path + "/ledger").json() == ledger
    for merchant in snapshot["merchants"]:
        checkpoint = client.app.state.service.agents.graph.get_state({"configurable": {
            "thread_id": f"arena-{arena['id']}/round-1/merchant-{merchant['id']}"}})
        assert all(c["status"] == "pending_allocation" for c in checkpoint.values["negotiation"]["contracts"])


def test_legacy_policy_survives_restart_fork_and_read_only_enrichment(client, arena_config):
    service = client.app.state.service
    arena = service.create(ArenaInput(**arena_config), supply_policy=LEGACY_POLICY)
    service.advance(arena["id"], 0)
    with service.db.connect() as conn:
        snapshot = json.loads(conn.execute("SELECT snapshot FROM rounds WHERE arena_id=? AND number=1", (arena["id"],)).fetchone()[0])
        for merchant in snapshot["merchants"]:
            merchant.pop("procurement")
        raw = json.dumps(snapshot)
        conn.execute("UPDATE rounds SET snapshot=? WHERE arena_id=? AND number=1", (raw, arena["id"]))
    service.db.initialize()
    detail = service.detail(arena["id"])
    assert detail["supply_policy"] == LEGACY_POLICY
    assert all(len(m["procurement"]) == 3 for m in detail["snapshot"]["merchants"])
    with service.db.connect() as conn:
        assert conn.execute("SELECT snapshot FROM rounds WHERE arena_id=? AND number=1", (arena["id"],)).fetchone()[0] == raw
    fork = client.post(f"/api/arenas/{arena['id']}/fork", json={"round": 1}).json()
    assert fork["supply_policy"] == LEGACY_POLICY
    assert service.fork(arena["id"])["supply_policy"] == POLICY


def test_shared_supply_projection_does_not_assume_entire_market(client, arena_config):
    arena, market, plans = example(client, arena_config, (120, 120, 120))
    service = client.app.state.service
    merchant = arena["snapshot"]["merchants"][0]
    obs = service.observation(service.db.arena(arena["id"]), arena["snapshot"], merchant, market)
    plan = plans[merchant["id"]]
    new = simulate_plan(obs, plan)
    old = simulate_plan({**obs, "supply_policy": LEGACY_POLICY}, plan)
    assert new["scenarios"][1]["inventory"] < old["scenarios"][1]["inventory"]
    assert "估计" in new["supply_assumption"]


def test_independent_validation_keeps_development_allocation_policy(client):
    service = client.app.state.service
    experiment = service.create_experiment(ExperimentInput(name="旧规则开发集", rounds=3, seeds=[111], split="development",
        variants=[{"name": "基线", "strategy_id": "balanced"}, {"name": "对照", "strategy_id": "discount"}]), supply_policy=LEGACY_POLICY)
    for arena in experiment["arenas"]:
        for number in range(3):
            service.advance(arena["id"], number)
    response = client.post(f"/api/experiments/{experiment['id']}/select", json={"seeds": [211], "round_budget": 6})
    assert response.status_code == 201, response.text
    assert response.json()["config"]["supply_policy"] == LEGACY_POLICY
    assert all(arena["supply_policy"] == LEGACY_POLICY for arena in response.json()["arenas"])
