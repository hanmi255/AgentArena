import copy
import json

import pytest
from fastapi.testclient import TestClient

from arena.agents import engine
from arena.agents.structured import parse_model_response
from arena.api.app import create_app
from arena.domain.models import CandidatePlans, Decision, NegotiationAction, PlanReview, RoutingPlan
from arena.infrastructure.events import event_scope
from tests import test_model
from tests.test_decision_upgrade import configured
from tests.test_model import ModelHandler, configure, sample_plan


@pytest.mark.parametrize("schema,data,role", [
    (Decision, sample_plan(), "decide"),
    (CandidatePlans, {"candidates": [sample_plan(), sample_plan()]}, "decide"),
    (RoutingPlan, {"objective": "保留现金", "reason": "现金紧张", "tools": [], "review_required": True}, "route"),
    (PlanReview, {"approved": True, "issues": [], "reason": "预算足够"}, "review"),
    (NegotiationAction, {"action": "reject", "unit_price": 0, "quantity": 0, "reason": "退出"}, "negotiate"),
])
@pytest.mark.parametrize("suffix", ["", '], "review": "模型附加评语"}'])
def test_complete_json_is_validated_and_trailing_content_is_observable(schema, data, role, suffix):
    events = []
    with event_scope(lambda *event: events.append(event)):
        result = parse_model_response(schema, " \n" + json.dumps(data) + suffix, role)
    assert result.model_dump() == data
    if suffix:
        assert events == [(role, "response_normalized", "已读取完整 JSON，忽略末尾附加内容",
                           {"schema": schema.__name__, "ignored_characters": len(suffix)})]
    else:
        assert events == []


@pytest.mark.parametrize("content", ['{"candidates":[', '{"candidates":}', '评语在前 {"candidates":[]}', ''])
def test_incomplete_json_is_not_invented_or_exposed(content):
    with pytest.raises(ValueError, match="JSON 不完整或格式有误") as error:
        parse_model_response(CandidatePlans, content, "decide")
    assert "input_value" not in str(error.value)
    assert "errors.pydantic" not in str(error.value)


@pytest.mark.parametrize("invalid", ["missing_product", "negative_price", "too_few_candidates"])
def test_trailing_content_does_not_relax_business_validation(invalid):
    plans = [copy.deepcopy(sample_plan()), sample_plan()]
    if invalid == "missing_product":
        plans[0]["products"].pop()
    elif invalid == "negative_price":
        plans[0]["products"][0]["price"] = -1
    else:
        plans.pop()
    text = json.dumps({"candidates": plans}) + '], "review": "不能用评语绕过校验"}'
    with pytest.raises(ValueError, match="未通过数据校验") as error:
        parse_model_response(CandidatePlans, text, "decide")
    assert "candidates" in str(error.value)
    assert "input_value" not in str(error.value)


def test_failed_planner_checkpoint_resumes_and_all_roles_accept_complete_json(tmp_path, arena_config, model_server, monkeypatch):
    original = test_model.role_value

    def require_review(name, payload):
        value = original(name, payload)
        if name == "RoutingPlan":
            value["review_required"] = True
        return value

    monkeypatch.setattr(test_model, "role_value", require_review)
    ModelHandler.json_suffix = '], "review": "作为保守备选。"}'
    arena_config["merchants"][0]["mode"] = "llm"

    def legacy_parser(schema, content, role):
        return schema.model_validate_json(content)

    def planner_requests():
        return [item for item in ModelHandler.requests if '"title": "CandidatePlans"' in str(item["messages"][0]["content"])]

    with TestClient(create_app(tmp_path, seed_demo=False)) as client:
        configure(client, model_server)
        settings = client.get("/api/settings").json()
        assert client.put("/api/settings", json={**settings, "provider": "deepseek"}).status_code == 200
        arena = configured(client, arena_config)
        initial_cash = {item["id"]: item["cash"] for item in arena["snapshot"]["merchants"]}
        path = f"/api/arenas/{arena['id']}"
        with monkeypatch.context() as legacy:
            legacy.setattr(engine, "parse_model_response", legacy_parser)
            response = client.post(path + "/step", json={"expected_round": 0})
        assert response.status_code == 400
        assert "trailing characters" in response.text
        assert client.get(path).json()["current_round"] == 0
        assert client.get(path + "/ledger").json() == []
        planner_calls = len(planner_requests())
        assert planner_calls > 0

    with TestClient(create_app(tmp_path, seed_demo=False)) as client:
        response = client.post(path + "/step", json={"expected_round": 0})
        assert response.status_code == 200, response.text
        arena = response.json()
        assert arena["current_round"] == 1 and arena["error"] is None
        assert len(planner_requests()) == planner_calls
        decision = next(item for item in arena["decisions"] if item["mode"] == "llm")
        assert len(decision["tools"]) == 1
        assert decision["trace"]["reviews"][0]["approved"]
        assert len(decision["trace"]["negotiation"]["contracts"]) == 3
        events = client.get(path + "/timeline?limit=1000").json()
        assert {event["node"] for event in events if event["status"] == "response_normalized"} == {"route", "decide", "review", "negotiate"}
        ledger = client.get(path + "/ledger").json()
        for merchant in arena["snapshot"]["merchants"]:
            assert merchant["cash"] == initial_cash[merchant["id"]] + sum(item["amount"] for item in ledger if item["merchant_id"] == merchant["id"])
        assert client.post(path + "/step", json={"expected_round": 0}).status_code == 409
        assert client.get(path + "/ledger").json() == ledger
