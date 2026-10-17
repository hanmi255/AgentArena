import json

import pytest
from fastapi.testclient import TestClient
from pydantic import Field, ValidationError

from arena.api.app import create_app
from arena.agents import negotiation
from arena.agents.structured import role_call
from arena.domain.models import NegotiationAction
from tests import test_model
from tests.test_decision_upgrade import configured


@pytest.mark.parametrize("action", ["offer", "accept", "reject"])
def test_zero_price_is_only_valid_for_rejection(action):
    data = {"action": action, "unit_price": 0, "quantity": 0, "reason": "退出交易"}
    if action == "reject":
        assert NegotiationAction.model_validate(data).model_dump() == data
    else:
        with pytest.raises(ValidationError, match="进货单价必须大于 0"):
            NegotiationAction.model_validate(data)


def reject_bar(monkeypatch, sender):
    original = test_model.role_value

    def response(name, payload):
        if name == "NegotiationAction":
            data = json.loads(next(item["content"] for item in reversed(payload["messages"]) if item["role"] == "user"))
            supplier = "floor" in data["private"]
            # The three products have distinct order quantities in the mock plan.
            if data["messages"][0]["quantity"] == 40 and supplier == (sender == "supplier"):
                return {"action": "reject", "unit_price": 0, "quantity": 0, "reason": "本轮退出交易"}
        return original(name, payload)

    monkeypatch.setattr(test_model, "role_value", response)


def assert_rejected_product_not_purchased(client, path, arena, sender):
    decision = next(item for item in arena["decisions"] if item["mode"] == "llm")
    result = decision["trace"]["negotiation"]
    assert {item["product_id"] for item in result["contracts"]} == {"coffee", "oats"}
    rejected = next(item for item in result["messages"] if item["product_id"] == "bar")
    assert not rejected["agreed"]
    assert rejected["messages"][-1] == {
        "sender": sender, "action": "reject", "unit_price": 0, "quantity": 0, "reason": "本轮退出交易",
    }
    merchant_id = decision["merchant_id"]
    ledger = client.get(path + f"/ledger?round=1&merchant={merchant_id}").json()
    assert not any(item["kind"] == "purchase" and item["product_id"] == "bar" for item in ledger)
    merchant = next(item for item in arena["snapshot"]["merchants"] if item["id"] == merchant_id)
    before = next(item for item in decision["observation"]["store"]["inventory"] if item["product_id"] == "bar")
    after = next(item for item in merchant["inventory"] if item["product_id"] == "bar")
    sold = sum(item["quantity"] for item in ledger if item["kind"] == "sale" and item["product_id"] == "bar")
    assert after["quantity"] == before["quantity"] - sold
    assert merchant["cash"] == decision["observation"]["store"]["cash"] + sum(item["amount"] for item in ledger)
    with client.app.state.database.connect() as conn:
        assert not conn.execute("SELECT 1 FROM supplier_reservations WHERE merchant_id=? AND product_id='bar'", (merchant_id,)).fetchone()


@pytest.mark.parametrize("sender", ["buyer", "supplier"])
@pytest.mark.parametrize("provider", ["compatible", "deepseek"])
def test_rejection_settles_without_purchase(client, arena_config, model_server, monkeypatch, sender, provider):
    test_model.configure(client, model_server)
    settings = client.get("/api/settings").json()
    assert client.put("/api/settings", json={**settings, "provider": provider}).status_code == 200
    reject_bar(monkeypatch, sender)
    arena_config["merchants"][0]["mode"] = "llm"
    arena = configured(client, arena_config)
    path = f"/api/arenas/{arena['id']}"
    response = client.post(path + "/step", json={"expected_round": 0})
    assert response.status_code == 200, response.text
    assert response.json()["current_round"] == 1
    assert_rejected_product_not_purchased(client, path, response.json(), sender)


def test_failed_zero_price_checkpoint_resumes_after_restart_without_model_call(tmp_path, arena_config, model_server, monkeypatch):
    class LegacyNegotiationAction(NegotiationAction):
        model_config = {"title": "NegotiationAction"}
        unit_price: int = Field(ge=1, le=10000)

    def legacy_call(settings, schema, *args):
        return role_call(settings, LegacyNegotiationAction, *args)

    reject_bar(monkeypatch, "buyer")
    with TestClient(create_app(tmp_path, seed_demo=False)) as client:
        test_model.configure(client, model_server)
        settings = client.get("/api/settings").json()
        client.put("/api/settings", json={**settings, "provider": "deepseek"})
        arena_config["merchants"][0]["mode"] = "llm"
        arena = configured(client, arena_config)
        path = f"/api/arenas/{arena['id']}"
        with monkeypatch.context() as legacy:
            legacy.setattr(negotiation, "role_call", legacy_call)
            response = client.post(path + "/step", json={"expected_round": 0})
        assert response.status_code == 400
        assert "未通过数据校验" in response.json()["detail"]
        assert client.get(path + "/ledger").json() == []
        calls = len(test_model.ModelHandler.requests)

    with TestClient(create_app(tmp_path, seed_demo=False)) as client:
        response = client.post(path + "/step", json={"expected_round": 0})
        assert response.status_code == 200, response.text
        assert response.json()["current_round"] == 1
        assert response.json()["error"] is None
        assert len(test_model.ModelHandler.requests) == calls
        assert_rejected_product_not_purchased(client, path, response.json(), "buyer")
        ledger = client.get(path + "/ledger").json()
        assert client.post(path + "/step", json={"expected_round": 0}).status_code == 409
        assert client.get(path + "/ledger").json() == ledger
