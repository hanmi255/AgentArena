import type { DecisionEvent } from "../../types";

const NODES = [
  ["observe", "观察环境", 90, 55],
  ["route", "规划行动", 310, 55],
  ["decide", "生成方案", 530, 55],
  ["simulate", "候选试算", 750, 55],
  ["commit_plan", "提交方案", 90, 210],
  ["negotiate", "供应商协商", 310, 210],
  ["approval", "人工审批", 530, 210],
  ["review", "风险审核", 750, 210],
] as const;
const EDGES = [
  ["observe", "route", "M170 55H230"],
  ["route", "decide", "M390 55H450"],
  ["decide", "simulate", "M610 55H670"],
  ["simulate", "review", "M750 85V180"],
  ["review", "approval", "M670 210H610"],
  ["approval", "negotiate", "M450 210H390"],
  ["negotiate", "commit_plan", "M230 210H170"],
  ["simulate", "approval", "M715 85Q625 125 570 180"],
];

export function DecisionFlow({ events }: { events: DecisionEvent[] }) {
  const active = events[events.length - 1];
  const previousNode = [...events]
    .reverse()
    .find(
      (event) => event.node !== active?.node && event.status === "completed",
    )?.node;
  const rejected =
    active?.node === "review" &&
    active.payload.reviews?.at(-1)?.approved === false;
  return (
    <div className="flow-scroll" aria-label="实时决策流程">
      <svg
        className="decision-flow"
        viewBox="0 0 860 285"
        role="img"
        aria-label={active ? `当前：${active.label}` : "等待经营决策"}
      >
        <defs>
          <marker
            id="flow-arrow"
            viewBox="0 0 10 10"
            refX="8"
            refY="5"
            markerWidth="5"
            markerHeight="5"
            orient="auto-start-reverse"
          >
            <path d="M0 0L10 5L0 10Z" fill="currentColor" />
          </marker>
        </defs>
        {EDGES.map(([from, to, path]) => (
          <path
            key={path}
            d={path}
            className={`flow-edge ${active?.status !== "completed" && active?.node === to && previousNode === from ? "flow-moving" : ""}`}
            markerEnd="url(#flow-arrow)"
          />
        ))}
        <path
          d="M715 180Q640 112 570 90"
          className={`flow-edge flow-return ${rejected ? "flow-moving rejected" : ""}`}
          markerEnd="url(#flow-arrow)"
        />
        <text x="620" y="131" className="flow-caption">
          驳回后重新规划
        </text>
        {NODES.map(([key, label, x, y]) => {
          const last = events.filter((event) => event.node === key).at(-1);
          const running =
            active?.node === key &&
            ![
              "completed",
              "resolved",
              "reserved",
              "skipped",
              "failed",
            ].includes(active.status);
          return (
            <g
              key={key}
              transform={`translate(${x - 80},${y - 30})`}
              className={`flow-node ${last ? "visited" : ""} ${running ? "active" : ""} ${last?.status === "failed" || (key === "review" && rejected) ? "rejected" : ""}`}
            >
              <rect width="160" height="60" rx="15" />
              <circle cx="20" cy="30" r="4" />
              <text x="36" y="28">
                {label}
              </text>
              <text x="36" y="46" className="flow-caption">
                {running
                  ? active.status === "waiting"
                    ? "等待你的决定"
                    : "正在执行"
                  : last
                    ? last.status === "failed"
                      ? "执行中断"
                      : last.status === "skipped"
                        ? "本轮跳过"
                        : "已执行"
                    : "按条件执行"}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
