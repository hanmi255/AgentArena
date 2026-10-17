import { useState } from "react";
import { api } from "../../api";
import { Button, useToast } from "../../components/ui";
import type { Experiment } from "../../types";

export function StrategySelection({
  experiment,
  onCreated,
}: {
  experiment: Experiment;
  onCreated: (id: number) => void;
}) {
  const [seeds, setSeeds] = useState("101, 211, 307");
  const [budget, setBudget] = useState(180);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  if (
    experiment.config.split !== "development" ||
    experiment.status !== "completed"
  )
    return null;
  return (
    <section className="panel branch-panel">
      <h3>筛选策略并独立验证</h3>
      <p>
        从无破产记录的方案中选出开发集平均收益最高者，再与基线在未使用的种子上比较。开发集名次不能替代验证结果。
      </p>
      <div className="form-grid">
        <label className="field">
          独立验证种子
          <input
            aria-label="独立验证种子"
            value={seeds}
            onChange={(event) => setSeeds(event.target.value)}
          />
        </label>
        <label className="field">
          验证预算（商店回合）
          <input
            aria-label="验证预算"
            type="number"
            min="6"
            max="600"
            value={budget}
            onChange={(event) => setBudget(+event.target.value)}
          />
        </label>
      </div>
      <Button
        busy={busy}
        onClick={async () => {
          setBusy(true);
          try {
            const result = await api<Experiment>(
              `/experiments/${experiment.id}/select`,
              {
                method: "POST",
                body: JSON.stringify({
                  seeds: seeds
                    .split(/[,，\s]+/)
                    .filter(Boolean)
                    .map(Number),
                  round_budget: budget,
                }),
              },
            );
            onCreated(result.id);
          } catch (error) {
            toast((error as Error).message, true);
          } finally {
            setBusy(false);
          }
        }}
      >
        筛选并运行独立验证
      </Button>
    </section>
  );
}
