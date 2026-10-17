import { Bot, TrendingUp, Zap } from "lucide-react";
import { count, money, signedMoney } from "../../api";
import { COLORS, Sparkline } from "../../components/Charts";
import { Avatar } from "../../components/ui";
import type { Arena, Merchant } from "../../types";

export function StoreCard({
  merchant,
  arena,
}: {
  merchant: Merchant;
  arena: Arena;
}) {
  const trend = arena.history
    .filter((point) => point.round <= arena.snapshot.round)
    .map(
      (point) =>
        point.merchants.find((item) => item.id === merchant.id)!.profit,
    );
  return (
    <article className={`store-card store-${merchant.color}`}>
      <div className="store-heading">
        <Avatar name={merchant.name} color={merchant.color} />
        <div>
          <h3>{merchant.name}</h3>
          <span>{merchant.strategy_name}</span>
          {merchant.model_config?.model && (
            <small className="model-tag">{merchant.model_config.model}</small>
          )}
        </div>
        <span className="engine-badge">
          {merchant.bankrupt ? (
            "已退场"
          ) : merchant.mode === "llm" ? (
            <>
              <Bot size={12} />
              LLM
            </>
          ) : (
            <>
              <Zap size={12} />
              策略
            </>
          )}
        </span>
      </div>
      <div className="store-profit">
        <div>
          <span>累计净收益</span>
          <strong className={merchant.profit >= 0 ? "positive" : "negative"}>
            {signedMoney(merchant.profit)}
          </strong>
        </div>
        <Sparkline values={trend} color={COLORS[merchant.color]} />
      </div>
      <div className="store-financials">
        <span>
          可用现金<b>¥{money(merchant.cash)}</b>
        </span>
        <span>
          总资产<b>¥{money(merchant.equity)}</b>
        </span>
        <span>
          本轮销量
          <b>
            {merchant.metrics.sold}
            <small> 件</small>
          </b>
        </span>
      </div>
      <div className="inventory-table">
        <div className="inventory-labels">
          <span>商品</span>
          <span>库存</span>
          <span>售价</span>
        </div>
        {merchant.inventory.map((stock) => (
          <div key={stock.product_id}>
            <span>
              <i className={`product-dot product-${stock.product_id}`} />
              {stock.name}
            </span>
            <span className={stock.quantity === 0 ? "negative" : ""}>
              {stock.quantity}
              <small> 件</small>
            </span>
            <b>¥{money(stock.price)}</b>
          </div>
        ))}
      </div>
      <div className="store-footer">
        <span className={merchant.roi >= 0 ? "positive" : "negative"}>
          <TrendingUp size={13} />
          {merchant.roi >= 0 ? "+" : ""}
          {merchant.roi}%
        </span>
        <span>累计售出 {count(merchant.total_sold)} 件</span>
      </div>
    </article>
  );
}
