"""Separate executed tools from budget rejections, including older saved traces."""

BUDGET_EXHAUSTED = "该工具本轮额度已用完，请使用已有结果提交最终方案。"


def tool_records(records):
    return [{**record, "executed": record.get("executed", record["result"] != BUDGET_EXHAUSTED)}
            for record in records]
