import { Download } from "lucide-react";
import { useEffect, useState } from "react";
import { money, signedMoney, useResource } from "../../api";
import { Button, Empty, ErrorState, Loading } from "../../components/ui";
import type { LedgerEntry, Merchant } from "../../types";

const PRODUCT_NAMES: Record<string, string> = {
  coffee: "冷萃咖啡",
  oats: "燕麦早餐",
  bar: "能量棒",
};

export function LedgerPanel({
  arenaId,
  round,
  merchants,
}: {
  arenaId: number;
  round: number | null;
  merchants: Merchant[];
}) {
  const [merchant, setMerchant] = useState("");
  const [page, setPage] = useState(0);
  const query = new URLSearchParams();
  if (round !== null) query.set("round", String(round));
  if (merchant) query.set("merchant", merchant);
  const { data, error, reload } = useResource<LedgerEntry[]>(
    `/arenas/${arenaId}/ledger?${query.toString()}`,
  );
  useEffect(() => setPage(0), [round, merchant]);
  if (error) return <ErrorState message={error} retry={reload} />;
  if (!data) return <Loading />;
  const labels = {
    purchase: "商品采购",
    sale: "商品销售",
    marketing: "营销投入",
    operations: "经营费用",
  };
  return (
    <div className="ledger-panel">
      <div className="ledger-toolbar">
        <span>{data.length} 笔交易</span>
        <select
          aria-label="账本商店筛选"
          value={merchant}
          onChange={(event) => setMerchant(event.target.value)}
        >
          <option value="">全部商店</option>
          {merchants.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
        <a
          href={`/api/arenas/${arenaId}/export?format=csv`}
          download
          className="text-button"
        >
          <Download size={15} />
          导出 CSV
        </a>
      </div>
      {data.length === 0 ? (
        <Empty title="暂无交易" />
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>回合</th>
                <th>商店</th>
                <th>交易类型</th>
                <th>商品 / 数量</th>
                <th className="text-right">交易金额</th>
                <th className="text-right">现金余额</th>
              </tr>
            </thead>
            <tbody>
              {data.slice(page * 30, (page + 1) * 30).map((item) => (
                <tr key={item.id}>
                  <td>
                    <span className="round-tag">
                      R{String(item.round_number).padStart(2, "0")}
                    </span>
                  </td>
                  <td>{item.merchant_name}</td>
                  <td>
                    <span
                      className={`transaction-type transaction-${item.kind}`}
                    >
                      {labels[item.kind]}
                    </span>
                  </td>
                  <td>
                    {item.product_id
                      ? `${PRODUCT_NAMES[item.product_id]} × ${item.quantity}`
                      : "—"}
                  </td>
                  <td
                    className={`text-right numeric ${item.amount >= 0 ? "positive" : ""}`}
                  >
                    {signedMoney(item.amount)}
                  </td>
                  <td className="text-right numeric">¥{money(item.balance)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data.length > 30 && (
        <div className="pagination">
          <span>
            {page * 30 + 1}–{Math.min((page + 1) * 30, data.length)} /{" "}
            {data.length}
          </span>
          <Button
            variant="secondary"
            disabled={page === 0}
            onClick={() => setPage(page - 1)}
          >
            上一页
          </Button>
          <Button
            variant="secondary"
            disabled={(page + 1) * 30 >= data.length}
            onClick={() => setPage(page + 1)}
          >
            下一页
          </Button>
        </div>
      )}
    </div>
  );
}
