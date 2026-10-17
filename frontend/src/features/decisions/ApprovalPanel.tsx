import { ShieldCheck } from "lucide-react";
import { useState } from "react";
import { api, money } from "../../api";
import { Button, useToast } from "../../components/ui";
import type { Approval, Arena, Decision } from "../../types";

function ApprovalCard({
  approval,
  arenaId,
  onUpdate,
}: {
  approval: Approval;
  arenaId: number;
  onUpdate: (arena: Arena) => void;
}) {
  const [plan, setPlan] = useState<Decision["plan"]>(
    structuredClone(approval.proposal.plan),
  );
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const send = async (action: "approve" | "modify" | "reject") => {
    setBusy(true);
    try {
      onUpdate(
        await api<Arena>(`/arenas/${arenaId}/approvals/${approval.id}`, {
          method: "POST",
          body: JSON.stringify({
            action,
            version: approval.version,
            reason,
            ...(action === "modify" ? { plan } : {}),
          }),
        }),
      );
    } catch (error) {
      toast((error as Error).message, true);
    } finally {
      setBusy(false);
    }
  };
  return (
    <article className="approval-card">
      <div className="section-heading small">
        <h3>
          <ShieldCheck size={18} />
          {approval.name}需要你的决定
        </h3>
        <span>第 {approval.round_number} 轮</span>
      </div>
      <p>{approval.proposal.plan.summary}</p>
      <p className="muted">
        预计支出 ¥{money(approval.proposal.spend)} · 当前现金 ¥
        {money(approval.proposal.cash)}
      </p>
      <details>
        <summary>修改本轮方案</summary>
        <div className="approval-edit">
          {plan.products.map((action, index) => (
            <div key={action.product_id}>
              <strong>
                {
                  { coffee: "咖啡", oats: "燕麦", bar: "能量棒" }[
                    action.product_id
                  ]
                }
              </strong>
              <label>
                定价（元）
                <input
                  type="number"
                  min="1"
                  max="100"
                  step="0.01"
                  aria-label={`${action.product_id}审批定价`}
                  value={action.price / 100}
                  onChange={(event) =>
                    setPlan({
                      ...plan,
                      products: plan.products.map((item, i) =>
                        i === index
                          ? {
                              ...item,
                              price: Math.round(+event.target.value * 100),
                            }
                          : item,
                      ),
                    })
                  }
                />
              </label>
              <label>
                补货
                <input
                  type="number"
                  min="0"
                  max="250"
                  aria-label={`${action.product_id}审批补货`}
                  value={action.purchase_quantity}
                  onChange={(event) =>
                    setPlan({
                      ...plan,
                      products: plan.products.map((item, i) =>
                        i === index
                          ? { ...item, purchase_quantity: +event.target.value }
                          : item,
                      ),
                    })
                  }
                />
              </label>
            </div>
          ))}
          <label>
            营销预算（元）
            <input
              type="number"
              min="0"
              max="300"
              step="1"
              value={plan.marketing_budget / 100}
              onChange={(event) =>
                setPlan({
                  ...plan,
                  marketing_budget: Math.round(+event.target.value * 100),
                })
              }
            />
          </label>
        </div>
      </details>
      <label className="field">
        审批意见
        <input
          value={reason}
          maxLength={400}
          onChange={(event) => setReason(event.target.value)}
          placeholder="退回时可说明希望调整的方向"
        />
      </label>
      <div className="heading-actions">
        <Button busy={busy} onClick={() => send("approve")}>
          批准并继续
        </Button>
        <Button
          variant="secondary"
          disabled={busy}
          onClick={() => send("modify")}
        >
          采用修改并继续
        </Button>
        <Button variant="ghost" disabled={busy} onClick={() => send("reject")}>
          退回重新规划
        </Button>
      </div>
    </article>
  );
}
export function ApprovalPanel({
  arena,
  onUpdate,
}: {
  arena: Arena;
  onUpdate: (arena: Arena) => void;
}) {
  return (
    <div className="approval-list">
      {arena.approvals?.map((item) => (
        <ApprovalCard
          key={`${item.id}-${item.version}`}
          approval={item}
          arenaId={arena.id}
          onUpdate={onUpdate}
        />
      ))}
    </div>
  );
}
