import type { DecisionEvent, HistoryPoint, Merchant } from "../../types";

export const ACTIONS: Record<string, string> = {
  observe: "观察市场",
  route: "规划行动",
  decide: "制定方案",
  simulate: "比较方案",
  review: "检查风险",
  approval: "等待批准",
  negotiate: "协商进货",
  commit_plan: "等待结算",
  settle: "结算完成",
};
export const TOOLS: Record<string, string> = {
  inspect_store: "查看库存",
  observe_market: "查看市场",
  review_history: "复盘经营",
  evaluate_plan: "试算方案",
  recall_experience: "检索经验",
};
export const PRODUCTS = { coffee: "咖啡", oats: "燕麦", bar: "能量棒" };

// A replay has one cursor for the entire market. No merchant can see a later event.
export function storeAtEvent(
  before: Merchant,
  after: Merchant,
  events: DecisionEvent[],
): Merchant {
  const settlement = events.find(
    (event) => event.node === "settle" && event.status === "completed",
  );
  if (!settlement) return before;
  const settled = settlement.payload.merchant ?? after;
  return { ...settled, procurement: settled.procurement ?? after.procurement };
}

export function actionLabel(event?: DecisionEvent): string {
  if (!event) return "等待本轮行动";
  if (event.status === "failed") return "执行中断";
  if (event.status === "skipped") return "继续下一步";
  if (event.payload.tool)
    return TOOLS[event.payload.tool] ?? event.payload.tool;
  return ACTIONS[event.node] ?? event.label;
}

export interface Highlight {
  round: number;
  label: string;
  kind: "lead" | "loss" | "market";
}
export function highlights(history: HistoryPoint[]): Highlight[] {
  const result: Highlight[] = [];
  for (let index = 1; index < history.length; index++) {
    const point = history[index];
    const previous = history[index - 1];
    const leader = [...point.merchants].sort((a, b) => b.profit - a.profit)[0];
    const oldLeader = [...previous.merchants].sort(
      (a, b) => b.profit - a.profit,
    )[0];
    if (index > 1 && leader.id !== oldLeader.id)
      result.push({ round: point.round, label: "排名反超", kind: "lead" });
    else if (
      point.merchants.some(
        (store) =>
          store.profit <
          previous.merchants.find((old) => old.id === store.id)!.profit,
      )
    ) {
      result.push({ round: point.round, label: "出现回合亏损", kind: "loss" });
    } else if (point.event !== previous.event)
      result.push({ round: point.round, label: point.event, kind: "market" });
  }
  return result;
}
