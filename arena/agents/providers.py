"""Provider compatibility and tool-capability checks shared by settings and matches."""

import json
import time

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI
from openai import APIConnectionError, APIError, APITimeoutError

from arena.domain.models import ModelSettings


class DeepSeekChat(ChatOpenAI):
    """Round-trip provider reasoning inside protocol messages, never in UI traces."""

    def _create_chat_result(self, response, generation_info=None):
        result = super()._create_chat_result(response, generation_info)
        payload = response if isinstance(response, dict) else response.model_dump()
        for generation, choice in zip(result.generations, payload["choices"]):
            reasoning = choice["message"].get("reasoning_content")
            if reasoning is not None:
                generation.message.additional_kwargs["reasoning_content"] = reasoning
        return result

    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        # Send JSON mode through the ordinary completion endpoint. SDK parse()
        # requires strict tools, which DeepSeek's normal endpoint does not use.
        if payload.get("response_format", {}).get("type") == "json_object":
            payload.setdefault("extra_body", {})["response_format"] = payload.pop("response_format")
        messages = self._convert_input(input_).to_messages()
        for message, encoded in zip(messages, payload["messages"]):
            if isinstance(message, AIMessage) and "reasoning_content" in message.additional_kwargs:
                encoded["reasoning_content"] = message.additional_kwargs["reasoning_content"]
        if (self.extra_body or {}).get("thinking", {}).get("type") == "enabled" and payload.get("tool_choice"):
            payload["tool_choice"] = "auto"
        return payload


def is_deepseek(settings):
    return settings.get("provider") == "deepseek" or "deepseek.com" in settings["base_url"]


def build_model(settings, json_mode=False):
    config = ModelSettings.model_validate(settings).model_dump()
    deepseek = is_deepseek(config)
    model_type = DeepSeekChat if deepseek else ChatOpenAI
    parameters = {
        "model": config["model"], "api_key": config["api_key"], "base_url": config["base_url"],
        "timeout": config["timeout"], "max_retries": 0, "max_tokens": config["max_tokens"],
        "use_responses_api": False,
    }
    if deepseek:
        parameters["extra_body"] = {"thinking": {"type": config["thinking"]}}
    if not deepseek or config["thinking"] == "disabled":
        parameters["temperature"] = config["temperature"]
    if json_mode:
        parameters["model_kwargs"] = {"response_format": {"type": "json_object"}}
    return model_type(**parameters)


def model_error(error, secrets=()):
    if isinstance(error, APITimeoutError):
        message = "模型请求超时，请检查网络或调高请求超时"
    elif isinstance(error, APIConnectionError):
        message = "无法连接模型服务，请检查 API 地址和网络"
    elif isinstance(error, APIError):
        body = error.body or {}
        detail = body.get("message") or body.get("error", {})
        if isinstance(detail, dict):
            detail = detail.get("message", "")
        status = getattr(error, "status_code", "")
        labels = {401: "API Key 无效或已过期", 402: "账户余额不足", 403: "没有访问该模型的权限",
                  404: "模型或 API 地址不存在", 429: "模型请求限流或额度不足"}
        message = labels.get(status, "模型请求失败") + (f"（HTTP {status}）" if status else "")
        if detail:
            message += f"：{detail}"
    else:
        message = str(error)
    for secret in secrets:
        if secret:
            message = message.replace(secret, "[redacted]")
    return message[:700]


def test_connection(config):
    if not config["api_key"] or not config["model"]:
        raise ValueError("请填写模型名称和 API Key")
    started = time.monotonic()
    model = build_model(config)
    schema = {"name": "connection_probe", "description": "返回连接校验结果", "parameters": {
        "type": "object", "properties": {"status": {"type": "string", "enum": ["ok"]}}, "required": ["status"]}}
    messages = [HumanMessage(content="Call connection_probe with status ok, then reply OK after receiving its result.")]
    response = model.bind_tools([schema]).invoke(messages)
    if not response.tool_calls or response.tool_calls[0]["name"] != "connection_probe":
        raise ValueError("模型连接成功，但未完成工具调用；请检查该模型是否支持 Function Calling")
    call = response.tool_calls[0]
    messages.append(response)
    for item in response.tool_calls:
        messages.append(ToolMessage(content=json.dumps({"status": "ok"}), tool_call_id=item["id"]))
    final = model.bind_tools([schema]).invoke(messages)
    if final.tool_calls:
        raise ValueError("模型未完成工具结果回传校验，请重试或检查模型工具兼容性")
    return {"status": "connected", "model": config["model"], "tool_calling": True,
            "latency_ms": round((time.monotonic() - started) * 1000), "thinking": config.get("thinking", "disabled")}
