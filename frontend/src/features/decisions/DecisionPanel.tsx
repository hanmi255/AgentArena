import {
  ArrowRight,
  Check,
  ChevronRight,
  Layers3,
  Package,
  Sparkles,
  Workflow,
  Ban,
} from "lucide-react";
import { useState } from "react";
import { money } from "../../api";
import { Avatar, Empty } from "../../components/ui";
import type { Decision } from "../../types";
import { WorkflowTracePanel } from "./WorkflowTracePanel";

const PRODUCT_NAMES: Record<string, string> = {
  coffee: "冷萃咖啡",
  oats: "燕麦早餐",
  bar: "能量棒",
};
const TOOL_NAMES: Record<string, string> = {
  inspect_store: "查看本店经营数据",
  observe_market: "观察市场与对手",
  review_history: "回顾历史表现",
};

export function DecisionPanel({ decisions }: { decisions: Decision[] }) {
  const [selected, setSelected] = useState<number | null>(null);
  if (!decisions.length) return <Empty title="等待第一轮决策" />;
  const decision =
    decisions.find((item) => item.merchant_id === selected) || decisions[0];
  return (
    <div className="decision-layout">
      <aside className="decision-merchants">
        {decisions.map((item) => (
          <button
            key={item.id}
            className={decision.id === item.id ? "selected" : ""}
            onClick={() => setSelected(item.merchant_id)}
          >
            <Avatar name={item.name} color={item.color} small />
            <span>
              {item.name}
              <small>{item.mode === "llm" ? "LLM Agent" : "策略引擎"}</small>
            </span>
            <ChevronRight size={15} />
          </button>
        ))}
      </aside>
      <div className="decision-detail">
        <div className="decision-title">
          <div>
            <span className="eyebrow">
              DECISION TRACE / ROUND{" "}
              {decision.round_number.toString().padStart(2, "0")}
            </span>
            <h3>{decision.name}的经营决策</h3>
            {decision.model_config?.model && (
              <span className="model-tag">
                {decision.model_config.model} ·{" "}
                {decision.trace?.workflow === "adaptive"
                  ? "自主规划"
                  : decision.trace?.workflow === "reviewed"
                    ? "试算与审核"
                    : "标准决策"}
              </span>
            )}
          </div>
          <span className="trace-duration">
            {decision.duration_ms} ms ·{" "}
            {decision.input_tokens + decision.output_tokens} tokens
          </span>
        </div>
        <div className="workflow-line">
          {decision.stages.map((stage, index) => (
            <div key={`${stage.node}-${index}`}>
              <span>
                <Check size={13} />
              </span>
              <b>{stage.label}</b>
              {index < decision.stages.length - 1 && <ArrowRight size={16} />}
            </div>
          ))}
        </div>
        <div className="decision-summary">
          <Sparkles size={18} />
          <p>{decision.plan.summary}</p>
        </div>
        <WorkflowTracePanel trace={decision.trace || {}} />
        <div className="section-heading small">
          <h3>经营方案</h3>
          <span>
            营销投入 <b>¥{money(decision.plan.marketing_budget)}</b>
          </span>
        </div>
        <div className="decision-actions">
          {decision.plan.products.map((product) => (
            <div key={product.product_id}>
              <Package size={18} />
              <strong>{PRODUCT_NAMES[product.product_id]}</strong>
              <span>
                定价<b>¥{money(product.price)}</b>
              </span>
              <span>
                计划补货<b>{product.purchase_quantity} 件</b>
              </span>
            </div>
          ))}
        </div>
        {(decision.mode === "llm" || decision.tools.length > 0) && <>
        <div className="section-heading small">
          <h3>
            {decision.mode === "llm" ? "模型工具执行" : "历史规则数据读取"}<span className="number-chip">{decision.tools.filter((tool) => tool.executed !== false).length}</span>
          </h3>
          <Workflow size={16} />
        </div>
        <div className="tool-list">
          {decision.tools.map((tool, index) => (
            <details key={`${tool.name}-${index}`}>
              <summary>
                <span className="tool-index">
                  {String(index + 1).padStart(2, "0")}
                </span>
                {tool.executed === false ? <Ban size={14} /> : <Check size={14} />}
                <strong>{TOOL_NAMES[tool.name] || tool.name}</strong>
                {tool.executed === false && <span>预算拦截 · 未执行</span>}
                <code>{tool.name}()</code>
                <ChevronRight size={15} />
              </summary>
              <pre>
                {typeof tool.result === "string"
                  ? tool.result
                  : JSON.stringify(tool.result, null, 2)}
              </pre>
            </details>
          ))}
        </div>
        </>}
        <div className="agent-memory">
          <span>
            <Layers3 size={15} />
            经营记忆
          </span>
          <p>{decision.plan.memory}</p>
        </div>
        <details className="context-data">
          <summary>
            决策上下文
            <ChevronRight size={14} />
          </summary>
          <pre>{JSON.stringify(decision.observation, null, 2)}</pre>
        </details>
      </div>
    </div>
  );
}
