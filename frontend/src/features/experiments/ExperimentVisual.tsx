import { useState } from "react";
import { signedMoney } from "../../api";
import { COLORS } from "../../components/Charts";
import type { Experiment } from "../../types";

export function ExperimentVisual({ experiment }: { experiment: Experiment }) {
  const [metric, setMetric] = useState<"tokens" | "latency">("tokens");
  const scores = experiment.scores.filter((score) => score.samples > 0);
  if (!scores.length)
    return (
      <div className="experiment-visual-empty">
        首场结算后显示收益与调用开销。
      </div>
    );
  const costs = scores.map((score) =>
    metric === "tokens"
      ? (score.total_tokens ?? 0) / (score.samples * experiment.config.rounds)
      : (score.average_duration_ms ?? 0) / 1000,
  );
  const maxCost = Math.max(1, ...costs);
  const hasCost = costs.some((cost) => cost > 0);
  const low = Math.min(0, ...scores.map((score) => score.average_profit));
  const high = Math.max(100, ...scores.map((score) => score.average_profit));
  const x = (value: number) => 72 + (value / maxCost) * 440;
  const y = (value: number) => 205 - ((value - low) / (high - low)) * 165;
  return (
    <div className="experiment-visual">
      <div className="visual-heading">
        <div>
          <h3>收益值得这份开销吗？</h3>
          <p>
            {hasCost
              ? "越靠左上，平均收益越高、每轮开销越少。"
              : "规则策略不消耗模型 Token，先比较经营收益。"}
          </p>
        </div>
        <div className="segmented">
          <button
            className={metric === "tokens" ? "active" : ""}
            onClick={() => setMetric("tokens")}
          >
            Token
          </button>
          <button
            className={metric === "latency" ? "active" : ""}
            onClick={() => setMetric("latency")}
          >
            耗时
          </button>
        </div>
      </div>
      {hasCost ? (
        <svg
          viewBox="0 0 580 255"
          role="img"
          aria-label={`平均收益与每轮${metric === "tokens" ? "Token" : "耗时"}对比`}
        >
          {[0, 0.5, 1].map((ratio) => (
            <g key={ratio}>
              <line
                x1="72"
                x2="530"
                y1={y(low + (high - low) * ratio)}
                y2={y(low + (high - low) * ratio)}
                stroke="#e6ece6"
                strokeDasharray="4 4"
              />
              <text
                x="64"
                y={y(low + (high - low) * ratio) + 4}
                textAnchor="end"
                className="chart-label"
              >
                {signedMoney(Math.round(low + (high - low) * ratio))}
              </text>
              <text
                x={x(maxCost * ratio)}
                y="228"
                textAnchor="middle"
                className="chart-label"
              >
                {Math.round(maxCost * ratio).toLocaleString()}
              </text>
            </g>
          ))}
          <text x="295" y="249" textAnchor="middle" className="chart-label">
            {metric === "tokens"
              ? "平均每商店回合 Token"
              : "平均每商店回合耗时 / 秒"}
          </text>
          {scores.map((score, index) => (
            <g key={score.strategy_id}>
              <circle
                cx={x(costs[index])}
                cy={y(score.average_profit)}
                r="8"
                fill={COLORS[score.color]}
                stroke="white"
                strokeWidth="3"
              >
                <title>
                  {score.name}：{signedMoney(score.average_profit)}，
                  {costs[index].toFixed(1)}{" "}
                  {metric === "tokens" ? "tokens" : "秒"}
                </title>
              </circle>
              <text
                x={x(costs[index])}
                y={y(score.average_profit) - 13 - index * 12}
                textAnchor="middle"
                fill={COLORS[score.color]}
                fontSize="11"
              >
                {index + 1}
              </text>
            </g>
          ))}
        </svg>
      ) : (
        <div className="profit-comparison-bars">
          {scores.map((score) => (
            <div key={score.strategy_id}>
              <span>{score.name}</span>
              <div>
                <i
                  style={{
                    width: `${(Math.abs(score.average_profit) / Math.max(...scores.map((item) => Math.abs(item.average_profit)), 1)) * 100}%`,
                    background: COLORS[score.color],
                  }}
                />
              </div>
              <strong>{signedMoney(score.average_profit)}</strong>
            </div>
          ))}
        </div>
      )}
      <div className="experiment-visual-cards">
        {scores.map((score, index) => (
          <article
            key={score.strategy_id}
            style={{ borderTopColor: COLORS[score.color] }}
          >
            <strong>
              {index + 1}. {score.name}
            </strong>
            <b>{signedMoney(score.average_profit)}</b>
            <small>平均净收益 · {score.samples} 场</small>
            <div>
              <span>
                胜率 <b>{score.win_rate}%</b>
              </span>
              <span>
                缺货 <b>{score.stockout_rate}%</b>
              </span>
            </div>
            <p>
              {score.confidence_interval
                ? `95% 均值区间 ${signedMoney(score.confidence_interval[0])} ～ ${signedMoney(score.confidence_interval[1])}`
                : "样本不足，暂不计算均值区间"}
            </p>
          </article>
        ))}
      </div>
      <p className="experiment-visual-note">
        收益为沙盘结算结果。收益与成本分别展示；能力是否有效，结合配对区间和独立验证判断。
      </p>
    </div>
  );
}
