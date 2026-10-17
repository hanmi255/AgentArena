import { Pause, Play, Radio, SkipBack, SkipForward } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { money, signedMoney } from "../../api";
import { Avatar, Button } from "../../components/ui";
import type { Arena, DecisionEvent, WorkflowTrace } from "../../types";
import { DecisionFlow } from "./DecisionFlow";
import { WorkflowTracePanel } from "./WorkflowTracePanel";

const NAMES: Record<string, string> = {
  coffee: "咖啡",
  oats: "燕麦",
  bar: "能量棒",
};

export function DecisionStage({
  arena,
  round,
  events,
  connected,
  error,
}: {
  arena: Arena;
  round: number | null;
  events: DecisionEvent[];
  connected: boolean;
  error: string;
}) {
  const [selected, setSelected] = useState<number | null>(null);
  const [cursor, setCursor] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [now, setNow] = useState(Date.now());
  const currentRound =
    round ?? Math.max(arena.current_round, events.at(-1)?.round_number || 1);
  const roundEvents = useMemo(
    () => events.filter((event) => event.round_number === currentRound),
    [events, currentRound],
  );
  const merchantId =
    selected ??
    roundEvents.at(-1)?.merchant_id ??
    arena.snapshot.merchants[0].id;
  const ownEvents = useMemo(
    () => roundEvents.filter((event) => event.merchant_id === merchantId),
    [roundEvents, merchantId],
  );
  useEffect(() => {
    setCursor(null);
    setPlaying(false);
  }, [arena.id, merchantId, currentRound]);
  useEffect(() => {
    if (!playing) return;
    const timer = setInterval(
      () =>
        setCursor((value) => {
          const next = (value ?? -1) + 1;
          if (next >= ownEvents.length - 1) {
            setPlaying(false);
            return Math.max(0, ownEvents.length - 1);
          }
          return next;
        }),
      800 / speed,
    );
    return () => clearInterval(timer);
  }, [playing, speed, ownEvents.length]);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const visible = cursor === null ? ownEvents : ownEvents.slice(0, cursor + 1);
  const current = visible.at(-1);
  const planEvents = visible.filter(
    (event) => event.node === "decide" && event.status === "completed",
  );
  const planTimeline = visible.flatMap((event) => {
    const value = event.payload.decision || event.payload.plan;
    return value ? [value] : [];
  });
  const plan = planTimeline.at(-1);
  const previous = [...planTimeline]
    .reverse()
    .find((value) => JSON.stringify(value) !== JSON.stringify(plan));
  const evidence = visible.find((event) => event.payload.evidence)?.payload
    .evidence;
  const routing = visible.find((event) => event.payload.routing)?.payload
    .routing;
  const simulation = [...visible]
    .reverse()
    .find((event) => event.payload.evaluations)?.payload.evaluations;
  const reviews = [...visible].reverse().find((event) => event.payload.reviews)
    ?.payload.reviews;
  const negotiated = visible.find((event) => event.payload.negotiation)?.payload
    .negotiation;
  const settled = visible.find((event) => event.node === "settle");
  const liveNegotiation: NonNullable<WorkflowTrace["negotiation"]> = {
    messages: [],
  };
  for (const event of visible) {
    if (
      event.node !== "negotiate" ||
      !event.payload.message ||
      !event.payload.product_id
    )
      continue;
    let session = liveNegotiation.messages!.find(
      (item) => item.product_id === event.payload.product_id,
    );
    if (!session) {
      session = {
        product_id: event.payload.product_id,
        messages: [],
        agreed: false,
      };
      liveNegotiation.messages!.push(session);
    }
    session.messages.push(event.payload.message);
    session.agreed = event.payload.message.action === "accept";
  }
  const trace: WorkflowTrace = {
    candidates: simulation,
    reviews,
    revisions: Math.max(0, planEvents.length - 1),
    negotiation: negotiated || liveNegotiation,
    memory: evidence?.experiences,
  };
  const waiting =
    current &&
    ["started", "model_started", "tool_started", "waiting"].includes(
      current.status,
    );
  const elapsed = waiting
    ? Math.max(
        0,
        Math.floor((now - new Date(current.created_at).getTime()) / 1000),
      )
    : 0;
  return (
    <section className="panel decision-theatre">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">DECISION LIVE</span>
          <h2>
            决策现场 <small>第 {currentRound} 轮</small>
          </h2>
        </div>
        <span className={`stream-badge ${connected ? "connected" : ""}`}>
          <Radio size={13} />
          {cursor === null && round === null ? "跟随真实执行" : "历史事件回放"}
        </span>
      </div>
      {error && <p className="stream-error">{error}</p>}
      <div className="decision-theatre-body">
        <aside className="live-store-list">
          {arena.snapshot.merchants.map((merchant) => {
            const last = roundEvents
              .filter((event) => event.merchant_id === merchant.id)
              .at(-1);
            return (
              <button
                key={merchant.id}
                className={merchantId === merchant.id ? "selected" : ""}
                onClick={() => setSelected(merchant.id)}
              >
                <Avatar name={merchant.name} color={merchant.color} small />
                <span>
                  <strong>{merchant.name}</strong>
                  <small>{last?.label || "等待执行"}</small>
                  <small>{merchant.model_config?.model || "确定性策略"}</small>
                </span>
              </button>
            );
          })}
          <button
            className="text-button"
            onClick={() => {
              setSelected(null);
              setCursor(null);
              setPlaying(false);
            }}
          >
            跟随当前商店
          </button>
        </aside>
        <div className="live-decision-content">
          <DecisionFlow events={visible} />
          <div
            className={`active-decision ${waiting ? "is-working" : ""}`}
            role="status"
          >
            <i />
            <strong>{current?.label || "等待这一轮开始"}</strong>
            {waiting && cursor === null && <span>已等待 {elapsed} 秒</span>}
            {current?.payload.duration_ms !== undefined && (
              <span>{current.payload.duration_ms} ms</span>
            )}
          </div>
          {evidence && (
            <div className="decision-facts">
              <span>观察现金 ¥{money(evidence.cash)}</span>
              <span>{evidence.market_event}</span>
              {evidence.inventory.map((stock) => (
                <span key={stock.product_id}>
                  {NAMES[stock.product_id]}库存 {stock.quantity}
                </span>
              ))}
            </div>
          )}
          {routing && (
            <div className="decision-evidence">
              <strong>目标：{routing.objective}</strong>
              <p>{routing.reason}</p>
              <small>
                允许工具：{routing.tools.join("、") || "已有信息足够"} ·{" "}
                {routing.review_required
                  ? "需要独立审核"
                  : "按风险决定是否审核"}
              </small>
            </div>
          )}
          {plan && (
            <div className="decision-summary">
              <p>{plan.summary}</p>
            </div>
          )}
          {previous && plan && (
            <div className="decision-diff">
              <h3>方案修改</h3>
              {plan.products.map((action) => {
                const old = previous.products.find(
                  (item) => item.product_id === action.product_id,
                )!;
                return (
                  <p key={action.product_id}>
                    <b>{NAMES[action.product_id]}</b>
                    <span
                      className={
                        old.price !== action.price ? "changed-value" : ""
                      }
                    >
                      定价 ¥{money(old.price)} → ¥{money(action.price)}
                    </span>
                    <span
                      className={
                        old.purchase_quantity !== action.purchase_quantity
                          ? "changed-value"
                          : ""
                      }
                    >
                      补货 {old.purchase_quantity} → {action.purchase_quantity}
                    </span>
                  </p>
                );
              })}
              <p>
                营销 ¥{money(previous.marketing_budget)} → ¥
                {money(plan.marketing_budget)}
              </p>
            </div>
          )}
          <WorkflowTracePanel trace={trace} />
          {settled?.payload.metrics && (
            <div className="forecast-actual">
              <span>
                预测净收益
                <strong>
                  {settled.payload.projection
                    ? signedMoney(settled.payload.projection.expected_profit)
                    : "未记录"}
                </strong>
              </span>
              <span>
                实际净收益
                <strong>{signedMoney(settled.payload.metrics.profit)}</strong>
              </span>
              <span>
                预测偏差
                <strong>
                  {settled.payload.projection
                    ? signedMoney(
                        settled.payload.metrics.profit -
                          settled.payload.projection.expected_profit,
                      )
                    : "—"}
                </strong>
              </span>
            </div>
          )}
          <div className="event-replay-controls">
            <Button
              variant="ghost"
              disabled={!ownEvents.length}
              onClick={() => {
                setPlaying(false);
                setCursor(Math.max(0, (cursor ?? ownEvents.length - 1) - 1));
              }}
            >
              <SkipBack size={15} />
            </Button>
            <Button
              variant="secondary"
              disabled={!ownEvents.length}
              onClick={() => {
                if (
                  !playing &&
                  (cursor === null || cursor >= ownEvents.length - 1)
                )
                  setCursor(0);
                setPlaying(!playing);
              }}
            >
              {playing ? <Pause size={14} /> : <Play size={14} />}
              {playing ? "暂停事件回放" : "播放事件回放"}
            </Button>
            <Button
              variant="ghost"
              disabled={!ownEvents.length}
              onClick={() => {
                setPlaying(false);
                setCursor(Math.min(ownEvents.length - 1, (cursor ?? -1) + 1));
              }}
            >
              <SkipForward size={15} />
            </Button>
            <select
              aria-label="事件回放速度"
              value={speed}
              onChange={(event) => setSpeed(+event.target.value)}
            >
              <option value={0.5}>0.5×</option>
              <option value={1}>1×</option>
              <option value={2}>2×</option>
            </select>
            <button
              className="text-button"
              onClick={() => {
                setCursor(null);
                setPlaying(false);
              }}
            >
              返回最新
            </button>
          </div>
          <input
            className="event-slider"
            type="range"
            aria-label="执行事件位置"
            min="0"
            max={Math.max(0, ownEvents.length - 1)}
            value={cursor ?? Math.max(0, ownEvents.length - 1)}
            onChange={(event) => {
              setCursor(+event.target.value);
              setPlaying(false);
            }}
          />
          <div className="event-log" aria-label="执行事件记录">
            {visible
              .slice(-80)
              .reverse()
              .map((event) => (
                <EventRow
                  key={event.id}
                  event={event}
                  onSelect={() => {
                    setCursor(ownEvents.indexOf(event));
                    setPlaying(false);
                  }}
                />
              ))}
          </div>
          {!ownEvents.length && (
            <p className="empty-note">
              开始比赛后，真实的节点与工具事件将在这里出现。旧比赛仍可查看下方已保存的决策记录。
            </p>
          )}
        </div>
      </div>
    </section>
  );
}

function EventRow({
  event,
  onSelect,
}: {
  event: DecisionEvent;
  onSelect: () => void;
}) {
  return (
    <details className="event-row">
      <summary>
        <button
          className="event-time"
          onClick={(e) => {
            e.preventDefault();
            onSelect();
          }}
        >
          {new Date(event.created_at).toLocaleTimeString("zh-CN", {
            hour12: false,
          })}
        </button>
        <span className={`event-dot event-${event.status}`} />
        <strong>{event.label}</strong>
        <small>{event.payload.tool || event.node}</small>
      </summary>
      <pre>{JSON.stringify(event.payload, null, 2)}</pre>
    </details>
  );
}
