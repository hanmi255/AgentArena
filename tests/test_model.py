import json
import threading
import time
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from arena.domain.models import Decision
from arena.cli.live_test import main as live_test


def sample_plan():
    return {"products": [{"product_id": "coffee", "price": 2100, "purchase_quantity": 35},
                         {"product_id": "oats", "price": 1500, "purchase_quantity": 25},
                         {"product_id": "bar", "price": 1100, "purchase_quantity": 40}],
            "marketing_budget": 6000, "summary": "根据本店库存与市场预测小批量补货，保持现金缓冲。", "memory": "下一轮关注咖啡周转与竞争价格。"}


def role_value(name, payload):
    if name == "RoutingPlan":
        return {"objective": "控制预算并提高净资产", "reason": "当前信息足够，仅检查库存", "tools": ["inspect_store"], "review_required": False}
    if name == "NegotiationAction":
        data = json.loads(next(item["content"] for item in reversed(payload["messages"]) if item["role"] == "user"))
        prior = data["messages"][-1]
        if "floor" in data["private"]:
            return {"action": "offer", "unit_price": data["private"]["opening"], "quantity": prior["quantity"], "reason": "现货报价"}
        if ModelHandler.invalid_buyer_quantity:
            return {"action": "offer", "unit_price": prior["unit_price"], "quantity": 250, "reason": "超额采购测试"}
        return {"action": "accept", "unit_price": prior["unit_price"], "quantity": prior["quantity"], "reason": "符合采购预算"}
    return None


class ModelHandler(BaseHTTPRequestHandler):
    requests = []
    reject = False
    review_rejections = 0
    fail_after_inspection = False
    repeat_reads = False
    invalid_buyer_quantity = False
    json_suffix = ""

    def log_message(self, format, *args):
        pass

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.requests.append(payload)
        if self.reject:
            self.send_response(429)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": {"message": "model rejected llm-test-secret", "type": "rate_limit_error", "code": "rate_limit_exceeded"}}).encode())
            return
        if payload.get("response_format", {}).get("type") == "json_object":
            available = {item["function"]["name"] for item in payload.get("tools", [])}
            used = {call["function"]["name"] for item in payload["messages"] for call in item.get("tool_calls", [])}
            tool_name = next((name for name in ["inspect_store", "observe_market", "review_history"] if name in available and name not in used), None)
            if tool_name:
                message = {"role": "assistant", "content": None, "tool_calls": [{"id": "call-" + tool_name, "type": "function", "function": {"name": tool_name, "arguments": "{}"}}]}
                finish_reason = "tool_calls"
            else:
                system = str(payload["messages"][0]["content"])
                value = sample_plan()
                if '"title": "CandidatePlans"' in system:
                    value = {"candidates": [value, {**value, "marketing_budget": 2000, "summary": "现金优先方案"}]}
                elif '"title": "PlanReview"' in system:
                    value = {"approved": True, "reason": "预算与现金缓冲通过", "issues": []}
                for name in ["RoutingPlan", "NegotiationAction"]:
                    if f'"title": "{name}"' in system:
                        value = role_value(name, payload)
                message = {"role": "assistant", "content": json.dumps(value) + self.json_suffix}
                finish_reason = "stop"
        elif not payload.get("tools"):
            message = {"role": "assistant", "content": "OK"}
            finish_reason = "stop"
        elif payload["tools"][0]["function"]["name"] == "connection_probe":
            if any(message["role"] == "tool" for message in payload["messages"]):
                message = {"role": "assistant", "content": "OK"}
                finish_reason = "stop"
            else:
                message = {"role": "assistant", "content": None, "reasoning_content": "private protocol state",
                           "tool_calls": [{"id": "probe", "type": "function", "function": {"name": "connection_probe", "arguments": '{"status":"ok"}'}}]}
                finish_reason = "tool_calls"
        else:
            used = {call["function"]["name"] for message in payload["messages"] for call in message.get("tool_calls", [])}
            available = {item["function"]["name"] for item in payload["tools"]}
            final_name = next(name for name in ["Decision", "CandidatePlans", "PlanReview", "RoutingPlan", "NegotiationAction"] if name in available)
            tool_name = next((name for name in ["inspect_store", "observe_market", "review_history"] if name not in used and name in available), final_name)
            if self.fail_after_inspection and "inspect_store" in used:
                type(self).fail_after_inspection = False
                self.send_response(429)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error":{"message":"temporary limit","type":"rate_limit_error"}}')
                return
            plan = sample_plan()
            arguments = {}
            if tool_name == "Decision":
                arguments = plan
            elif tool_name == "CandidatePlans":
                arguments = {"candidates": [plan, {**plan, "marketing_budget": 2000, "summary": "低营销预算方案"}]}
            elif tool_name == "PlanReview":
                reject = type(self).review_rejections > 0
                type(self).review_rejections -= int(reject)
                arguments = {"approved": not reject, "issues": ["需要比较更低的营销预算"] if reject else [], "reason": "检查现金与库存风险"}
            elif tool_name in ["RoutingPlan", "NegotiationAction"]:
                arguments = role_value(tool_name, payload)
            message = {"role": "assistant", "content": None,
                       "tool_calls": [{"id": "call-" + tool_name, "type": "function", "function": {"name": tool_name, "arguments": json.dumps(arguments)}}]}
            finish_reason = "tool_calls"
        message["reasoning_content"] = "private protocol state"
        if self.repeat_reads and message.get("tool_calls") and message["tool_calls"][0]["function"]["name"] == "inspect_store":
            message["tool_calls"].append({"id": "duplicate-read", "type": "function", "function": {"name": "inspect_store", "arguments": "{}"}})
        if payload.get("thinking", {}).get("type") == "enabled":
            assert payload.get("tool_choice", "auto") == "auto"
            assert all(item.get("reasoning_content") for item in payload["messages"] if item["role"] == "assistant")
        response = {"id": f"completion-{len(self.requests)}", "object": "chat.completion", "created": 1700000000,
                    "model": "arena-test", "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
                    "usage": {"prompt_tokens": 120, "completion_tokens": 40, "total_tokens": 160}}
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(response).encode())


@pytest.fixture
def model_server():
    ModelHandler.requests = []
    ModelHandler.reject = False
    ModelHandler.review_rejections = 0
    ModelHandler.fail_after_inspection = False
    ModelHandler.repeat_reads = False
    ModelHandler.invalid_buyer_quantity = False
    ModelHandler.json_suffix = ""
    server = ThreadingHTTPServer(("127.0.0.1", 0), ModelHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/v1"
    server.shutdown()
    server.server_close()
    thread.join()


def configure(client, base_url):
    response = client.put("/api/settings", json={"base_url": base_url, "model": "arena-test", "api_key": "llm-test-secret",
                                               "temperature": 0.4, "timeout": 5, "max_steps": 15})
    assert response.status_code == 200


def test_langchain_agent_calls_tools_and_commits_structured_decision(client, arena_config, model_server):
    configure(client, model_server)
    assert client.post("/api/settings/test").status_code == 200
    arena_config["merchants"][0]["mode"] = "llm"
    arena_id = client.post("/api/arenas", json=arena_config).json()["id"]
    response = client.post(f"/api/arenas/{arena_id}/step", json={"expected_round": 0})
    assert response.status_code == 200, response.text
    decision = response.json()["decisions"][0]
    Decision.model_validate(decision["plan"])
    assert decision["input_tokens"] == 480 and decision["output_tokens"] == 160
    assert decision["mode"] == "llm"
    assert len(decision["tools"]) == 3
    assert {item["name"] for item in decision["tools"]} == {"inspect_store", "observe_market", "review_history"}
    assert len(ModelHandler.requests) == 6
    assert "llm-test-secret" not in response.text
    assert [item["node"] for item in decision["stages"]] == ["observe", "route", "decide", "simulate", "commit_plan"]
    state = client.app.state.service.agents.graph.get_state({"configurable": {"thread_id": f"arena-{arena_id}/round-1/merchant-{decision['merchant_id']}"}})
    assert state.values["decision"] == decision["plan"]
    replayed = client.app.state.service.agents.run(arena_id, 1, decision["merchant_id"], decision["observation"],
                                                  client.app.state.database.strategy("balanced"), "llm")
    assert replayed["plan"] == decision["plan"]
    assert len(ModelHandler.requests) == 6  # Reuse the committed checkpoint, with no extra model request.


def test_provider_failure_pauses_without_fake_decisions_or_ledger(client, arena_config, model_server):
    configure(client, model_server)
    ModelHandler.reject = True
    arena_config["merchants"][0]["mode"] = "llm"
    arena_id = client.post("/api/arenas", json=arena_config).json()["id"]
    client.post(f"/api/arenas/{arena_id}/run", json={"interval": 0})
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        arena = client.get(f"/api/arenas/{arena_id}").json()
        if arena["error"]:
            break
        time.sleep(0.03)
    assert arena["status"] == "paused" and arena["current_round"] == 0
    assert "llm-test-secret" not in arena["error"]
    assert arena["decisions"] == []
    assert client.get(f"/api/arenas/{arena_id}/ledger").json() == []


def test_live_check_exports_replay_and_verifies_ledger(tmp_path, model_server, monkeypatch):
    report = tmp_path / "live-report.json"
    monkeypatch.setenv("LIVE_MODEL_API_KEY", "llm-test-secret")
    monkeypatch.setattr(sys, "argv", ["live_test", "--base-url", model_server, "--model", "arena-test", "--report", str(report)])
    live_test()
    result = json.loads(report.read_text(encoding="utf-8"))
    assert result["status"] == "completed" and len(result["decisions"]) == 3
    assert "llm-test-secret" not in report.read_text(encoding="utf-8")
