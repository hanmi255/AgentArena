import type { AgentOptions, Mode } from "../../types";

export function AgentOptionsFields({
  value,
  onChange,
  label,
  mode,
}: {
  value?: AgentOptions;
  onChange: (value: AgentOptions) => void;
  label: string;
  mode: Mode;
}) {
  const options = value || {
    memory: "recent",
    negotiation: false,
    tool_budget: 6,
  };
  return (
    <div className={`agent-options-grid ${mode === "rule" ? "rule-options" : ""}`}>
      <label className="field">
        经验记忆
        <select
          aria-label={`${label}记忆`}
          value={options.memory}
          onChange={(event) =>
            onChange({
              ...options,
              memory: event.target.value as AgentOptions["memory"],
            })
          }
        >
          <option value="none">关闭记忆</option>
          <option value="recent">最近五轮</option>
          <option value="episodic">检索历史经验</option>
        </select>
      </label>
      <label className="field">
        {mode === "llm" ? "供应商谈判" : "规则议价"}
        <select
          aria-label={`${label}谈判`}
          value={options.negotiation ? "on" : "off"}
          onChange={(event) =>
            onChange({ ...options, negotiation: event.target.value === "on" })
          }
        >
          <option value="off">关闭</option>
          <option value="on">开启</option>
        </select>
      </label>
      {mode === "llm" && <label className="field">
        工具调用预算
        <input
          aria-label={`${label}工具预算`}
          type="number"
          min="1"
          max="10"
          value={options.tool_budget}
          onChange={(event) =>
            onChange({ ...options, tool_budget: +event.target.value })
          }
        />
      </label>}
    </div>
  );
}
