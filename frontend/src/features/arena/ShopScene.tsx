import {
  ArrowDown,
  ArrowRight,
  ArrowUp,
  Bot,
  Check,
  ChevronRight,
  Coffee,
  Cookie,
  Cpu,
  Eye,
  Package,
  ShoppingBag,
  Sprout,
  Truck,
  Users,
} from "lucide-react";
import { money, signedMoney } from "../../api";
import type { DecisionEvent, Merchant, ProductId } from "../../types";
import { AnimatedValue } from "../decisions/AnimatedValue";
import { actionLabel, PRODUCTS } from "./sceneState";

const ICONS = { coffee: Coffee, oats: Sprout, bar: Cookie };
const PHASES = [
  "observe",
  "route",
  "decide",
  "simulate",
  "review",
  "approval",
  "negotiate",
  "commit_plan",
  "settle",
];

export function ShopScene({
  merchant,
  before,
  events,
  round,
  onDetail,
}: {
  merchant: Merchant;
  before: Merchant;
  events: DecisionEvent[];
  round: number;
  onDetail: () => void;
}) {
  const last = events.at(-1);
  const settlement = events.find((event) => event.node === "settle");
  const proposals = events.flatMap((event) =>
    event.payload.plan || event.payload.decision
      ? [event.payload.plan ?? event.payload.decision!]
      : [],
  );
  const plan = proposals.at(-1);
  const candidates = events.filter((event) => event.payload.evaluations).at(-1)
    ?.payload.evaluations;
  const quotes = events.filter(
    (event) =>
      event.node === "negotiate" &&
      ["offer", "accept", "reject"].includes(event.payload.message?.action ?? ""),
  );
  const quote = quotes.at(-1);
  const productQuotes = quote
    ? quotes.filter(
        (event) =>
          event.payload.product_id === quote.payload.product_id &&
          event.payload.message!.action !== "reject" &&
          event.payload.message!.unit_price! > 0,
      )
    : [];
  const prices = productQuotes.map(
    (event) => event.payload.message!.unit_price!,
  );
  const minPrice = Math.min(...prices),
    maxPrice = Math.max(...prices);
  const pricePosition = (value: number) =>
    8 + ((value - minPrice) / Math.max(1, maxPrice - minPrice)) * 84;
  const started =
    last &&
    ["started", "model_started", "tool_started", "waiting"].includes(
      last.status,
    );
  const phase = PHASES.indexOf(last?.node ?? "");
  const metrics = settlement?.payload.metrics;
  const purchased = metrics?.purchased ?? 0;
  const sold = metrics?.sold ?? 0;
  const tools = events.filter(
    (event) => event.status === "tool_completed",
  ).length;
  const tokens = events.reduce(
    (sum, event) =>
      sum +
      (event.payload.input_tokens ?? 0) +
      (event.payload.output_tokens ?? 0),
    0,
  );
  return (
    <article
      className={`theatre-shop store-${merchant.color} ${started ? "shop-working" : ""} ${settlement ? "shop-settled" : ""}`}
      aria-label={`${merchant.name}商店`}
    >
      <header className="shop-identity">
        <span className="shop-agent">
          {merchant.mode === "llm" ? <Bot size={20} /> : <Cpu size={20} />}
        </span>
        <div>
          <h3>{merchant.name}</h3>
          <small>
            {merchant.mode === "llm"
              ? merchant.model_config?.model
              : merchant.strategy_name}
          </small>
        </div>
        <button
          className="icon-button"
          onClick={onDetail}
          aria-label={`查看${merchant.name}决策详情`}
        >
          <Eye size={17} />
        </button>
      </header>
      <div
        className="shop-action"
        role="status"
        key={`${round}-${last?.id ?? 0}`}
      >
        <i className={started ? "action-pulse" : ""} />
        <strong>{merchant.bankrupt ? "已退出经营" : actionLabel(last)}</strong>
        {last?.status === "completed" && <Check size={14} />}
      </div>
      <div
        className="shop-phase-track"
        aria-label={`当前阶段：${actionLabel(last)}`}
      >
        {PHASES.map((node, index) => (
          <i
            key={node}
            className={
              index === phase
                ? "current"
                : events.some((event) => event.node === node)
                  ? "visited"
                  : ""
            }
          />
        ))}
      </div>
      <div className="shop-building">
        <div className="store-awning">
          <span />
          <span />
          <span />
          <span />
          <span />
          <span />
          <span />
        </div>
        <div className="store-window">
          {merchant.inventory.map((stock) => {
            const Icon = ICONS[stock.product_id];
            const action = plan?.products.find(
              (item) => item.product_id === stock.product_id,
            );
            const planned = action && !settlement;
            const price = planned ? action.price : stock.price;
            const delivery = settlement && merchant.procurement?.find(
              (item) => item.product_id === stock.product_id,
            );
            const delta =
              stock.quantity -
              before.inventory.find(
                (item) => item.product_id === stock.product_id,
              )!.quantity;
            return (
              <div className="visual-product" key={stock.product_id}>
                <div className="product-caption">
                  <Icon size={15} />
                  <span>{stock.name}</span>
                  <b
                    key={price}
                    title={planned ? "计划对顾客销售的单价，结算时生效" : "对顾客销售的单价"}
                  >
                    {planned ? "拟售价" : "售价"} ¥{money(price)}
                  </b>
                </div>
                <div
                  className="product-shelf"
                  aria-label={`${stock.name}库存 ${stock.quantity} 件`}
                >
                  {Array.from({ length: 10 }, (_, i) => (
                    <span
                      className={
                        i < Math.ceil(stock.quantity / 15) ? "filled" : ""
                      }
                      key={i}
                    >
                      <Icon size={16} />
                    </span>
                  ))}
                </div>
                <div className="stock-caption">
                  <strong>
                    <AnimatedValue
                      value={stock.quantity}
                      format={(value) => `库存 ${value} 件`}
                    />
                  </strong>
                  {settlement ? (
                    <span className={delta >= 0 ? "positive" : "negative"}>
                      {delta >= 0 ? (
                        <ArrowUp size={11} />
                      ) : (
                        <ArrowDown size={11} />
                      )}
                      {Math.abs(delta)}
                    </span>
                  ) : action ? (
                    <span className="planned-action">
                      计划进货 {action.purchase_quantity} 件
                    </span>
                  ) : (
                    null
                  )}
                </div>
                {delivery && (
                  <div className="product-delivery" aria-label={`${stock.name}采购结果`}>
                    {delivery.quantity > 0 ? (
                      <>
                        <b>进价 ¥{money(delivery.unit_price!)}</b>
                        <span>到货 {delivery.quantity}/{delivery.requested_quantity} 件</span>
                      </>
                    ) : (
                      <>
                        <b>{delivery.status === "not_ordered" ? "未计划进货" : "未进货"}</b>
                        <span>{delivery.status === "rejected" ? "谈判未达成" :
                          delivery.status === "not_ordered" ? "" : "无可交付货量"}</span>
                        {delivery.requested_quantity > 0 && <span>到货 0/{delivery.requested_quantity} 件</span>}
                        {delivery.status !== "not_ordered" && delivery.unit_price !== null && (
                          <span>报价 ¥{money(delivery.unit_price)}</span>
                        )}
                      </>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
        <div className="store-door">
          <span />
          <i /> <small>{merchant.bankrupt ? "CLOSED" : "OPEN"}</small>
        </div>
        {settlement && (
          <div
            className="shop-trade-motion"
            key={settlement.id}
            aria-hidden="true"
          >
            {purchased > 0 && <Truck className="arriving-truck" size={25} />}
            {sold > 0 && (
              <>
                <span className="customer customer-one">
                  <Users size={21} />
                </span>
                <span className="customer customer-two">
                  <ShoppingBag size={18} />
                </span>
              </>
            )}
          </div>
        )}
      </div>
      <div className="shop-wallet">
        <span>可用现金</span>
        <strong>
          <AnimatedValue
            value={merchant.cash}
            format={(value) => `¥${money(value)}`}
          />
        </strong>
      </div>
      <div
        className="shop-result"
        key={`${round}-${settlement?.id ?? "pending"}`}
      >
        {metrics ? (
          <>
            <span>
              <Truck size={14} />
              进货 <b>{purchased}</b>
            </span>
            <span>
              <ShoppingBag size={14} />
              售出 <b>{sold}</b>
            </span>
            <strong className={metrics.profit >= 0 ? "positive" : "negative"}>
              {signedMoney(metrics.profit)}
              <small>本轮净收益</small>
            </strong>
          </>
        ) : (
          <>
            <Package size={16} />
            <span>
              {plan
                ? `计划采购 ${plan.products.reduce((sum, item) => sum + item.purchase_quantity, 0)} 件`
                : "等待经营方案"}
            </span>
            <small>尚未结算</small>
          </>
        )}
      </div>
      {settlement && metrics ? (
        <div className="shop-profit-breakdown" aria-label="本轮收益构成">
          <span>销售毛利 <b>{signedMoney(metrics.revenue - metrics.cost_of_goods)}</b></span>
          <span>营销 <b>−¥{money(metrics.marketing)}</b></span>
          <span>租金及持有费 <b>−¥{money(metrics.operating_cost)}</b></span>
        </div>
      ) : quote ? (
        <div className="quote-visual">
          <div className="quote-strip" key={quote.id}>
            <span>
              {PRODUCTS[quote.payload.product_id as ProductId]} ·{" "}
              {quote.payload.message!.sender === "supplier"
                ? "供应商"
                : "采购方"}
            </span>
            {quote.payload.message!.action !== "reject" && (
              <strong>报价 ¥{money(quote.payload.message!.unit_price!)}</strong>
            )}
            <ArrowRight size={14} />
            <span title={quote.payload.message!.reason}>
              {quote.payload.message!.action === "accept"
                ? "价格谈妥"
                : quote.payload.message!.action === "reject"
                  ? "拒绝交易"
                  : "协商中"}
            </span>
          </div>
          <div className="quote-axis" aria-label="本商品协商报价轨迹">
            {productQuotes.map((event, index) => (
              <i
                key={event.id}
                className={event.payload.message!.sender}
                style={{
                  left: `${pricePosition(event.payload.message!.unit_price!)}%`,
                  opacity: (index + 1) / productQuotes.length,
                }}
                title={`${event.payload.message!.sender === "buyer" ? "采购方" : "供应商"} ¥${money(event.payload.message!.unit_price!)}`}
              />
            ))}
          </div>
        </div>
      ) : candidates?.length ? (
        <div className="candidate-mini" aria-label="候选方案预计收益">
          {candidates.map((candidate) => (
            <div key={candidate.index} title={candidate.summary}>
              <span>
                {candidates.length === 1
                  ? "预计净收益"
                  : `方案 ${candidate.index + 1} · 预计`}
              </span>
              <strong>{signedMoney(candidate.expected_profit)}</strong>
              <i
                style={{
                  width: `${Math.max(8, (Math.abs(candidate.expected_profit) / Math.max(...candidates.map((item) => Math.abs(item.expected_profit)), 1)) * 100)}%`,
                }}
              />
            </div>
          ))}
        </div>
      ) : (
        <div className="shop-hint">
          {merchant.mode === "llm"
            ? "模型按市场信息自主经营"
            : "规则策略 · 可复现对照"}
        </div>
      )}
      <footer className="shop-telemetry">
        {merchant.mode === "llm" ? <>
          <span>{tools} 次模型工具调用</span>
          <span>{tokens.toLocaleString()} tokens</span>
        </> : <span>规则执行 · 无模型调用</span>}
        <button onClick={onDetail}>
          详情 <ChevronRight size={12} />
        </button>
      </footer>
    </article>
  );
}
