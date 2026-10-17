"""Retire completed read tools so planning has a bounded tool budget."""

from collections import Counter
from collections.abc import Callable

from langchain.agents.middleware import ModelRequest, ModelResponse, wrap_model_call, wrap_tool_call
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from contextvars import ContextVar
from arena.infrastructure.events import emit
from arena.agents.tool_records import BUDGET_EXHAUSTED

tool_budget = ContextVar("arena_tool_budget", default=6)


@wrap_model_call
def bounded_tools(request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]) -> ModelResponse:
    calls = Counter(call["name"] for message in request.messages if isinstance(message, AIMessage) for call in message.tool_calls)
    total = sum(calls.values())
    tools = []
    for item in request.tools:
        name = item.name if hasattr(item, "name") else item.get("name", item.get("function", {}).get("name"))
        limit = 2 if name == "evaluate_plan" else 1
        if calls[name] < limit and total < tool_budget.get():
            tools.append(item)
    emit("decide", "model_started", "等待规划模型响应")
    result = handler(request.override(tools=tools, messages=[*request.messages, HumanMessage(content="工具额度已用完，请立即按指定结构提交最终经营方案。")]) if not tools else request.override(tools=tools))
    usage = [message.usage_metadata or {} for message in result.result if isinstance(message, AIMessage)]
    emit("decide", "model_completed", "规划模型已响应",
         input_tokens=sum(item.get("input_tokens", 0) for item in usage),
         output_tokens=sum(item.get("output_tokens", 0) for item in usage))
    return result


@wrap_tool_call
def budgeted_execution(request, handler):
    name = request.tool_call["name"]
    limit = 2 if name == "evaluate_plan" else 1
    calls = [call for message in request.state["messages"] if isinstance(message, AIMessage) for call in message.tool_calls if call["name"] == name]
    position = next(index for index, call in enumerate(calls) if call["id"] == request.tool_call["id"])
    all_calls = [call for message in request.state["messages"] if isinstance(message, AIMessage) for call in message.tool_calls]
    total_position = next(index for index, call in enumerate(all_calls) if call["id"] == request.tool_call["id"])
    if position >= limit or total_position >= tool_budget.get():
        return ToolMessage(content=BUDGET_EXHAUSTED, tool_call_id=request.tool_call["id"], name=name)
    emit("decide", "tool_started", "调用经营工具", tool=name, arguments=request.tool_call["args"])
    result = handler(request)
    emit("decide", "tool_completed", "经营工具已返回", tool=name, result=result.content)
    return result
