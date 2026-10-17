import copy
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import ValidationError

from arena.domain.catalog import PRODUCTS
from arena.domain.market import conditions, settle
from arena.domain.models import Decision
from arena.application.service import ConflictError


def test_settlement_money_inventory_and_idempotency(client, arena_config):
    created = client.post("/api/arenas", json=arena_config)
    assert created.status_code == 201
    arena = created.json()
    arena_id = arena["id"]
    initial = {merchant["id"]: merchant for merchant in arena["snapshot"]["merchants"]}
    for number in range(5):
        response = client.post(f"/api/arenas/{arena_id}/step", json={"expected_round": number})
        assert response.status_code == 200, response.text
        arena = response.json()
        assert arena["current_round"] == number + 1
        assert len(arena["decisions"]) == 3
        assert all([stage["node"] for stage in item["stages"]] == ["observe", "route", "decide", "simulate", "commit_plan"] for item in arena["decisions"])
        assert all(item["input_tokens"] == 0 for item in arena["decisions"])
    assert arena["status"] == "completed"
    ledger = client.get(f"/api/arenas/{arena_id}/ledger").json()
    for merchant in arena["snapshot"]["merchants"]:
        own = [item for item in ledger if item["merchant_id"] == merchant["id"]]
        assert initial[merchant["id"]]["cash"] + sum(item["amount"] for item in own) == merchant["cash"]
        assert merchant["equity"] == merchant["cash"] + sum(item["book_value"] for item in merchant["inventory"])
        assert merchant["profit"] == merchant["equity"] - arena_config["initial_capital"]
        assert merchant["cash"] >= 0
        for stock in merchant["inventory"]:
            beginning = next(item for item in PRODUCTS if item["id"] == stock["product_id"])["initial_stock"]
            purchased = sum(item["quantity"] for item in own if item["kind"] == "purchase" and item["product_id"] == stock["product_id"])
            sold = sum(item["quantity"] for item in own if item["kind"] == "sale" and item["product_id"] == stock["product_id"])
            assert beginning + purchased - sold == stock["quantity"]
            assert stock["quantity"] >= 0 and stock["book_value"] >= 0
    duplicate = client.post(f"/api/arenas/{arena_id}/step", json={"expected_round": 4})
    assert duplicate.status_code == 409
    assert len(client.get(f"/api/arenas/{arena_id}/ledger").json()) == len(ledger)


def test_identical_seed_and_configuration_reproduce_results(client, arena_config):
    ids = [client.post("/api/arenas", json=arena_config).json()["id"] for _ in range(2)]
    outcomes = []
    for arena_id in ids:
        for number in range(5):
            result = client.post(f"/api/arenas/{arena_id}/step", json={"expected_round": number}).json()
        outcomes.append([(item["cash"], item["profit"], item["inventory"]) for item in result["snapshot"]["merchants"]])
    assert outcomes[0] == outcomes[1]


def test_supplier_stock_and_cash_are_enforced(client, arena_config):
    arena = client.post("/api/arenas", json=arena_config).json()
    previous = arena["snapshot"]
    original = copy.deepcopy(previous)
    market = conditions("supply-shock", 42, 7)
    for product in market["products"]:
        product["supply"] = 3
    plans = {merchant["id"]: {"products": [{"product_id": item["id"], "price": 10000, "purchase_quantity": 250} for item in PRODUCTS],
                               "marketing_budget": 30000, "summary": "测试", "memory": "测试"} for merchant in previous["merchants"]}
    snapshot, ledger = settle(previous, plans, market, arena_config["initial_capital"], 42)
    for product in PRODUCTS:
        assert sum(item["quantity"] for item in ledger if item["kind"] == "purchase" and item["product_id"] == product["id"]) <= 3
    assert all(item["cash"] >= 0 for item in snapshot["merchants"])
    assert previous == original


def test_private_observations_do_not_expose_competitor_balances(client, arena_config):
    arena_id = client.post("/api/arenas", json=arena_config).json()["id"]
    result = client.post(f"/api/arenas/{arena_id}/step", json={"expected_round": 0}).json()
    for decision in result["decisions"]:
        observation = decision["observation"]
        assert observation["store"]["id"] == decision["merchant_id"]
        assert all(set(item) == {"name", "prices"} for item in observation["competitors"])
        assert len(observation["competitors"]) == 2
        assert "api_key" not in str(observation)


def test_duplicate_products_are_rejected():
    plan = {"products": [{"product_id": "coffee", "price": 2000, "purchase_quantity": 20}] * 3,
            "marketing_budget": 0, "summary": "test", "memory": "test"}
    with pytest.raises(ValidationError):
        Decision.model_validate(plan)


def test_concurrent_round_cannot_charge_twice(client, arena_config):
    arena_id = client.post("/api/arenas", json=arena_config).json()["id"]

    def advance():
        try:
            client.app.state.service.advance(arena_id, 0)
            return "settled"
        except ConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: advance(), range(2)))
    assert sorted(outcomes) == ["conflict", "settled"]
    export = client.get(f"/api/arenas/{arena_id}/export").json()
    assert len(export["snapshots"]) == 2 and len(export["decisions"]) == 3


def test_insolvent_store_exits_without_negative_cash(client, arena_config):
    previous = client.post("/api/arenas", json=arena_config).json()["snapshot"]
    for merchant in previous["merchants"]:
        merchant.update(cash=1, equity=1)
        for stock in merchant["inventory"]:
            stock.update(quantity=0, book_value=0)
    plans = {merchant["id"]: {"products": [{"product_id": item["id"], "price": 10000, "purchase_quantity": 250} for item in PRODUCTS],
                               "marketing_budget": 30000, "memory": "退出"} for merchant in previous["merchants"]}
    result, ledger = settle(previous, plans, conditions("neighborhood", 42, 1), arena_config["initial_capital"], 42)
    assert all(item["bankrupt"] and item["cash"] == 0 for item in result["merchants"])
    second, next_ledger = settle(result, plans, conditions("neighborhood", 42, 2), arena_config["initial_capital"], 42)
    assert next_ledger == []
    assert all(item["cash"] == 0 for item in second["merchants"])
