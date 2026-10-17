import { CheckCircle2, RotateCcw } from "lucide-react";
import { money, signedMoney } from "../../api";
import type { WorkflowTrace } from "../../types";

export function WorkflowTracePanel({ trace }: { trace: WorkflowTrace }) {
  if (
    !trace.candidates?.length &&
    !trace.negotiation?.messages?.length &&
    !trace.memory?.length
  )
    return null;
  const selected = [...(trace.candidates || [])].sort(
    (a, b) => b.score - a.score,
  )[0]?.index;
  const products: Record<string, string> = {
    coffee: "咖啡",
    oats: "燕麦",
    bar: "能量棒",
  };
  return (
    <section className="planning-trace">
      {!!trace.candidates?.length && (
        <>
          <div className="section-heading small">
            <h3>候选方案试算</h3>
            <span>三种需求情景 · 预测值</span>
          </div>
          {!!trace.candidates?.length && (
            <p className="candidate-explanation">
              结合基准与低需求情景收益比较，同时惩罚预算和现金风险。人工修改后以最终提交方案为准。
            </p>
          )}
          <div className="projection-list">
            {trace.candidates?.map((candidate) => (
              <article
                key={candidate.index}
                className={
                  selected === candidate.index
                    ? "projection-card selected"
                    : "projection-card"
                }
              >
                <div className="section-heading small">
                  <h4>方案 {candidate.index + 1}</h4>
                  {selected === candidate.index && (
                    <span className="positive">
                      <CheckCircle2 size={13} />
                      试算推荐
                    </span>
                  )}
                </div>
                <p>{candidate.summary}</p>
                {candidate.plan && (
                  <div className="candidate-actions">
                    {candidate.plan.products.map((item) => (
                      <span key={item.product_id}>
                        {
                          { coffee: "咖啡", oats: "燕麦", bar: "能量棒" }[
                            item.product_id
                          ]
                        }{" "}
                        ¥{money(item.price)} / 补 {item.purchase_quantity} 件
                      </span>
                    ))}
                    <span>营销 ¥{money(candidate.plan.marketing_budget)}</span>
                  </div>
                )}
                <div className="projection-metrics">
                  <span>
                    基准净收益
                    <strong>{signedMoney(candidate.expected_profit)}</strong>
                  </span>
                  <span>
                    最低现金<strong>¥{money(candidate.worst_cash)}</strong>
                  </span>
                </div>
                <details>
                  <summary>情景明细</summary>
                  {candidate.supply_assumption && <p>{candidate.supply_assumption}</p>}
                  <div className="scenario-projections">
                    {candidate.scenarios.map((scenario) => (
                      <div key={scenario.name}>
                        <b>{scenario.name}</b>
                        <span>收益 {signedMoney(scenario.profit)}</span>
                        <span>售出 {scenario.sold} 件</span>
                        <span>余货 {scenario.inventory} 件</span>
                      </div>
                    ))}
                  </div>
                </details>
                {candidate.risks.length > 0 && (
                  <p className="negative">{candidate.risks.join("；")}</p>
                )}
              </article>
            ))}
          </div>
        </>
      )}
      {!!trace.reviews?.length && (
        <>
          <div className="section-heading small">
            <h3>独立审核</h3>
            <span>
              <RotateCcw size={13} />
              修订 {trace.revisions || 0} 次
            </span>
          </div>
          <div className="review-list">
            {trace.reviews?.map((review, index) => (
              <article key={index}>
                <span className={review.approved ? "positive" : "negative"}>
                  {review.approved ? "已通过" : "退回修订"}
                </span>
                <div>
                  <p>{review.reason}</p>
                  {review.issues.length > 0 && (
                    <small>{review.issues.join("；")}</small>
                  )}
                </div>
              </article>
            ))}
          </div>
        </>
      )}
      {(trace.iterations?.length || 0) > 1 && (
        <details className="context-data">
          <summary>修订历史</summary>
          {trace.iterations?.map((iteration) => (
            <div className="revision-history" key={iteration.revision}>
              <b>第 {iteration.revision + 1} 版</b>
              {iteration.candidates.map((candidate) => (
                <p key={candidate.index}>
                  方案 {candidate.index + 1} · {candidate.summary} · 预计{" "}
                  {signedMoney(candidate.expected_profit)}
                  {candidate.risks.length
                    ? ` · ${candidate.risks.join("；")}`
                    : ""}
                </p>
              ))}
            </div>
          ))}
        </details>
      )}
      {!!trace.negotiation?.messages?.length && (
        <section className="negotiation-panel">
          <div className="section-heading small">
            <h3>供应商谈判</h3>
            <span>独立买卖双方 · 最多三轮</span>
          </div>
          {trace.negotiation.messages.map((session) => {
            const contract = trace.negotiation?.contracts?.find((item) => item.product_id === session.product_id);
            const outcome = !session.agreed ? "谈判未达成" : !contract ? "价格谈妥" :
              contract.status === "pending_allocation" ? "价格谈妥 · 待分货" :
              contract.quantity === 0 ? "未进货 · 无可交付货量" :
              contract.status === "fulfilled" ? `已到货 ${contract.quantity} 件` : `已预留 ${contract.quantity} 件`;
            return (
            <details key={session.product_id}>
              <summary>
                {{ coffee: "咖啡", oats: "燕麦", bar: "能量棒" }[
                  session.product_id as "coffee"
                ] || session.product_id}{" "}
                · {outcome}
              </summary>
              <div className="negotiation-messages">
                {session.messages.map((message, i) => (
                  <div
                    key={i}
                    className={`negotiation-message ${message.sender}`}
                  >
                    <b>{message.sender === "supplier" ? "供应商" : "采购方"}</b>
                    <span>
                      {{
                        rfq: "询价",
                        offer: "报价",
                        accept: "接受",
                        reject: "拒绝",
                      }[message.action as "offer"] || message.action}{" "}
                      · {message.quantity} 件
                      {message.unit_price
                        ? ` · ¥${money(message.unit_price)}/件`
                        : ""}
                    </span>
                    <p>{message.reason}</p>
                  </div>
                ))}
              </div>
            </details>
            );
          })}
          <div className="contract-list">
            {trace.negotiation.contracts?.map((contract) => (
              <p key={contract.product_id}>
                <strong>
                  {products[contract.product_id] || contract.product_id}
                </strong>{" "}
                {contract.status === "pending_allocation" ? `待分货 ${contract.requested_quantity} 件` :
                  `${contract.status === "fulfilled" ? "到货" : "预留"} ${contract.quantity}/${contract.requested_quantity} 件`} ·
                {contract.quantity > 0 && contract.status !== "pending_allocation" ? "进价" : "报价"} ¥{money(contract.unit_price)} · 市场参考 ¥
                {money(contract.reference_price)}
              </p>
            ))}
          </div>
        </section>
      )}
      {!!trace.memory?.length && (
        <section className="experience-panel">
          <div className="section-heading small">
            <h3>本次引用的历史经验</h3>
            <span>本店已结算事实</span>
          </div>
          {trace.memory.map((memory) => (
            <details key={memory.evidence_id}>
              <summary>
                证据 #{memory.evidence_id} · 第 {memory.round} 轮 · 实际收益{" "}
                {signedMoney(memory.outcome.profit)}
              </summary>
              <p>{memory.lesson}</p>
              <p>
                销量 {memory.outcome.sold} · 缺货品类 {memory.outcome.missed} ·{" "}
                {memory.outcome.prediction_error === null
                  ? "当时未记录预测"
                  : `预测偏差 ${signedMoney(memory.outcome.prediction_error)}`}
              </p>
              <p>{memory.action.summary}</p>
            </details>
          ))}
        </section>
      )}
    </section>
  );
}
