import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  Beaker,
  Download,
  FlaskConical,
  Play,
  Plus,
  Trophy,
  Trash2,
} from "lucide-react";
import { api, date, money, signedMoney, useResource } from "../api";
import { AgentOptionsFields } from "../features/decisions/AgentOptionsFields";
import { ExperimentVisual } from "../features/experiments/ExperimentVisual";
import { StrategySelection } from "../features/experiments/StrategySelection";
import type {
  Catalog,
  Experiment,
  ExperimentVariant,
  Mode,
  ModelProfile,
  Strategy,
} from "../types";
import {
  Avatar,
  Button,
  Empty,
  ErrorState,
  Loading,
  Modal,
  StatusBadge,
  useToast,
} from "../components/ui";

export function ExperimentsPage({ catalog }: { catalog: Catalog }) {
  const { data, error, reload } = useResource<Experiment[]>("/experiments");
  const strategies = useResource<Strategy[]>("/strategies");
  const profiles = useResource<ModelProfile[]>("/model-profiles");
  const [creating, setCreating] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const [name, setName] = useState("策略对照实验");
  const [scenario, setScenario] = useState("neighborhood");
  const [rounds, setRounds] = useState(12);
  const [seeds, setSeeds] = useState("11, 23, 37");
  const [strategyIds, setStrategyIds] = useState([
    "balanced",
    "discount",
    "premium",
  ]);
  const [mode, setMode] = useState<Mode>("rule");
  const [comparison, setComparison] = useState(false);
  const [split, setSplit] = useState("holdout");
  const [variants, setVariants] = useState<ExperimentVariant[]>([
    {
      name: "标准决策",
      strategy_id: "balanced",
      mode: "rule",
      workflow: "direct",
      model_profile_id: "default",
    },
    {
      name: "试算与审核",
      strategy_id: "balanced",
      mode: "rule",
      workflow: "reviewed",
      model_profile_id: "default",
    },
  ]);
  const updateVariant = (index: number, values: Partial<ExperimentVariant>) =>
    setVariants((items) =>
      items.map((item, position) =>
        position === index ? { ...item, ...values } : item,
      ),
    );
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  useEffect(() => {
    if (!data?.some((item) => item.status === "running")) return;
    const timer = setInterval(reload, 1800);
    return () => clearInterval(timer);
  }, [data, reload]);
  if (error) return <ErrorState message={error} retry={reload} />;
  if (!data || !strategies.data) return <Loading />;
  const availableStrategies = strategies.data;
  const active = data.find((item) => item.id === selected) || data[0];
  const start = async (id: number) => {
    setBusy(true);
    try {
      await api(`/experiments/${id}/run`, { method: "POST" });
      reload();
    } catch (cause) {
      toast((cause as Error).message, true);
    } finally {
      setBusy(false);
    }
  };
  const open = () => {
    setName("策略对照实验");
    setStrategyIds(["balanced", "discount", "premium"]);
    setCreating(true);
  };
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">THE RESEARCH LAB</div>
          <h1>
            策略实验室
            <span className="title-dot" />
          </h1>
        </div>
        <Button onClick={open}>
          <Plus size={17} />
          新建实验
        </Button>
      </div>
      {data.length === 0 ? (
        <div className="experiment-empty">
          <div className="experiment-empty-art">
            <FlaskConical size={75} strokeWidth={1} />
            <span className="experiment-bubble bubble-one" />
            <span className="experiment-bubble bubble-two" />
          </div>
          <span className="eyebrow">OBSERVE. COMPARE. EVOLVE.</span>
          <h2>让结果，为策略说话。</h2>
          <p>多组种子，轮换席位，同场对照。</p>
          <Button onClick={open}>
            <Beaker size={17} />
            创建第一个实验
          </Button>
        </div>
      ) : (
        <div className="experiment-layout">
          <aside className="experiment-list">
            {data.map((item) => (
              <button
                key={item.id}
                className={active.id === item.id ? "selected" : ""}
                onClick={() => setSelected(item.id)}
              >
                <FlaskConical size={18} />
                <span>
                  <strong>{item.name}</strong>
                  <small>
                    {date(item.created_at)} · {item.completed}/
                    {item.arenas.length} 场完成
                  </small>
                </span>
                <i className={`experiment-state ${item.status}`} />
              </button>
            ))}
          </aside>
          <div className="experiment-main">
            <section className="panel experiment-overview">
              <div className="panel-heading">
                <div>
                  <span className="eyebrow">
                    EXPERIMENT {String(active.id).padStart(3, "0")}
                  </span>
                  <h2>{active.name}</h2>
                </div>
                <div className="heading-actions">
                  <a
                    href={`/api/experiments/${active.id}/export`}
                    download
                    className="button button-secondary"
                  >
                    <Download size={15} />
                    导出
                  </a>
                  {active.status !== "completed" && (
                    <Button
                      busy={busy}
                      disabled={active.status === "running"}
                      onClick={() => start(active.id)}
                    >
                      <Play size={15} fill="currentColor" />
                      {active.status === "running" ? "实验进行中" : "运行实验"}
                    </Button>
                  )}
                </div>
              </div>
              <div className="experiment-facts">
                <span>
                  市场
                  <strong>
                    {
                      catalog.scenarios.find(
                        (item) => item.id === active.config.scenario,
                      )?.name
                    }
                  </strong>
                </span>
                <span>
                  每场回合<strong>{active.config.rounds}</strong>
                </span>
                <span>
                  市场种子<strong>{active.config.seeds.join(" / ")}</strong>
                </span>
                <span>
                  决策引擎
                  <strong>
                    {active.config.variants?.length
                      ? "独立对照方案"
                      : active.config.mode === "llm"
                        ? "LLM Agent"
                        : "策略引擎"}
                  </strong>
                </span>
                <span>
                  数据用途
                  <strong>
                    {active.config.split === "development"
                      ? "策略开发"
                      : "保留集验收"}
                  </strong>
                </span>
              </div>
              <div className="experiment-progress">
                <span
                  style={{
                    width: `${(active.arenas.reduce((sum, arena) => sum + arena.current_round, 0) / (active.config.rounds * active.arenas.length)) * 100}%`,
                  }}
                />
              </div>
            </section>
            <StrategySelection
              experiment={active}
              onCreated={(id) => {
                setSelected(id);
                reload();
              }}
            />
            <section className="panel experiment-scores">
              <div className="panel-heading">
                <h2>策略表现</h2>
                <span>{active.completed} 场已结算</span>
              </div>
              <ExperimentVisual experiment={active} />
              <details className="experiment-metrics-detail">
                <summary>完整指标与统计明细</summary>
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>经营策略</th>
                        <th className="text-right">平均净收益</th>
                        <th className="text-right">收益波动</th>
                        <th className="text-right">胜率</th>
                        <th className="text-right">样本</th>
                        <th className="text-right">95% 均值区间</th>
                        <th className="text-right">Token</th>
                        <th className="text-right">模型成本估算</th>
                        <th className="text-right">每轮耗时</th>
                        <th className="text-right">最大回撤均值</th>
                        <th className="text-right">断货率</th>
                        <th className="text-right">库存周转</th>
                        <th className="text-right">模型工具调用</th>
                        <th className="text-right">提供经验</th>
                        <th className="text-right">预测误差</th>
                        <th className="text-right">谈判采购差额</th>
                      </tr>
                    </thead>
                    <tbody>
                      {active.scores.map((score, index) => (
                        <tr key={score.strategy_id}>
                          <td>
                            <span className="score-strategy">
                              <Avatar
                                name={score.name}
                                color={score.color}
                                small
                              />
                              {score.name}
                              {index === 0 && score.samples > 0 && (
                                <Trophy size={14} className="gold" />
                              )}
                            </span>
                            {score.model && (
                              <small className="model-tag">
                                {score.model} ·{" "}
                                {score.workflow === "adaptive"
                                  ? "自主规划"
                                  : score.workflow === "reviewed"
                                    ? "审核"
                                    : "标准"}
                              </small>
                            )}
                          </td>
                          <td
                            className={`text-right numeric ${score.average_profit >= 0 ? "positive" : "negative"}`}
                          >
                            {score.samples
                              ? signedMoney(score.average_profit)
                              : "—"}
                          </td>
                          <td className="text-right numeric">
                            {score.samples
                              ? `±¥${money(score.deviation)}`
                              : "—"}
                          </td>
                          <td className="text-right numeric">
                            {score.samples ? `${score.win_rate}%` : "—"}
                          </td>
                          <td className="text-right numeric">
                            {score.samples}
                          </td>
                          <td className="text-right numeric">
                            {score.confidence_interval
                              ? `¥${money(score.confidence_interval[0])} ～ ¥${money(score.confidence_interval[1])}`
                              : "—"}
                          </td>
                          <td className="text-right numeric">
                            {score.total_tokens?.toLocaleString() ?? "—"}
                          </td>
                          <td className="text-right numeric">
                            {score.estimated_model_cost != null
                              ? `¥${score.estimated_model_cost.toFixed(4)}`
                              : "—"}
                          </td>
                          <td className="text-right numeric">
                            {score.samples
                              ? `${((score.average_duration_ms || 0) / 1000).toFixed(2)} s`
                              : "—"}
                          </td>
                          <td className="text-right numeric">
                            {score.samples ? `${score.average_drawdown}%` : "—"}
                          </td>
                          <td className="text-right numeric">
                            {score.samples ? `${score.stockout_rate}%` : "—"}
                          </td>
                          <td className="text-right numeric">
                            {score.samples
                              ? `${score.inventory_turnover} 次`
                              : "—"}
                          </td>
                          <td className="text-right numeric">
                            {score.tool_calls ?? "—"}
                          </td>
                          <td className="text-right numeric">
                            {score.memory_references ?? "—"}
                          </td>
                          <td className="text-right numeric">
                            {score.prediction_mae != null
                              ? `¥${money(score.prediction_mae)}`
                              : "—"}
                          </td>
                          <td className="text-right numeric">
                            {score.negotiation_savings != null
                              ? signedMoney(score.negotiation_savings)
                              : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            </section>
            {!!active.comparisons?.length && (
              <section className="panel paired-comparisons">
                <div className="panel-heading">
                  <h2>相对基线收益</h2>
                  <span>按种子配对 · 95% 差值区间</span>
                </div>
                {active.comparisons.map((item) => (
                  <article key={item.variant}>
                    <div>
                      <strong>{item.variant}</strong>
                      <small>
                        对比 {item.baseline} · {item.samples} 组
                      </small>
                    </div>
                    <b
                      className={
                        item.average_difference >= 0 ? "positive" : "negative"
                      }
                    >
                      {item.samples
                        ? signedMoney(item.average_difference)
                        : "—"}
                    </b>
                    <span>
                      {item.confidence_interval
                        ? `¥${money(item.confidence_interval[0])} ～ ¥${money(item.confidence_interval[1])}`
                        : "—"}
                    </span>
                  </article>
                ))}
              </section>
            )}
            <section className="panel">
              <div className="panel-heading">
                <h2>实验对局</h2>
                <span>{active.arenas.length} 场</span>
              </div>
              <div className="experiment-matches">
                {active.arenas.map((arena) => (
                  <Link key={arena.id} to={`/arenas/${arena.id}`}>
                    <span className="round-tag">S{arena.seed}</span>
                    <div>
                      <strong>{arena.name}</strong>
                      <small>
                        回合 {arena.current_round}/{arena.total_rounds}
                      </small>
                    </div>
                    <StatusBadge status={arena.status} />
                    <span className="experiment-match-profit">
                      {arena.current_round ? `${arena.leader} 领跑` : "—"}
                    </span>
                    <ArrowRight size={16} />
                  </Link>
                ))}
              </div>
            </section>
          </div>
        </div>
      )}
      <Modal
        title="新建策略实验"
        open={creating}
        onClose={() => setCreating(false)}
        wide
      >
        <form
          onSubmit={async (event) => {
            event.preventDefault();
            setBusy(true);
            try {
              const experiment = await api<Experiment>("/experiments", {
                method: "POST",
                body: JSON.stringify({
                  name,
                  scenario,
                  rounds,
                  seeds: seeds
                    .split(/[,，\s]+/)
                    .filter(Boolean)
                    .map(Number),
                  strategy_ids: strategyIds,
                  mode,
                  split,
                  ...(comparison ? { variants, strategy_ids: [] } : {}),
                }),
              });
              await api(`/experiments/${experiment.id}/run`, {
                method: "POST",
              });
              setSelected(experiment.id);
              setCreating(false);
              reload();
            } catch (cause) {
              toast((cause as Error).message, true);
            } finally {
              setBusy(false);
            }
          }}
        >
          <div className="modal-body">
            <div className="experiment-kind">
              <button
                type="button"
                className={!comparison ? "selected" : ""}
                onClick={() => setComparison(false)}
              >
                策略对照
              </button>
              <button
                type="button"
                className={comparison ? "selected" : ""}
                onClick={() => setComparison(true)}
              >
                模型与流程对照
              </button>
            </div>
            <label className="field">
              实验名称
              <input
                value={name}
                required
                maxLength={60}
                onChange={(event) => setName(event.target.value)}
              />
            </label>
            <div className="form-grid three">
              <label className="field">
                实验市场
                <select
                  value={scenario}
                  onChange={(event) => setScenario(event.target.value)}
                >
                  {catalog.scenarios.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                每场回合
                <input
                  type="number"
                  min={3}
                  max={30}
                  required
                  value={rounds}
                  onChange={(event) => setRounds(+event.target.value)}
                />
              </label>
              <label className="field">
                决策引擎
                <select
                  value={mode}
                  disabled={comparison}
                  onChange={(event) => setMode(event.target.value as Mode)}
                >
                  <option value="rule">策略引擎</option>
                  <option value="llm">LLM Agent</option>
                </select>
              </label>
            </div>
            <label className="field">
              市场种子
              <input
                value={seeds}
                required
                onChange={(event) => setSeeds(event.target.value)}
                placeholder="11, 23, 37"
              />
            </label>
            <label className="field">
              数据用途
              <select
                value={split}
                onChange={(event) => setSplit(event.target.value)}
              >
                <option value="holdout">保留集验收</option>
                <option value="development">策略开发</option>
              </select>
            </label>
            {comparison ? (
              <div className="experiment-variants">
                {variants.map((variant, index) => (
                  <section className="experiment-variant" key={index}>
                    <div className="section-heading small">
                      <h3>{index === 0 ? "基线方案" : `对照方案 ${index}`}</h3>
                      <button
                        type="button"
                        className="icon-button"
                        aria-label={`移除方案 ${index + 1}`}
                        disabled={variants.length <= 2}
                        onClick={() =>
                          setVariants(
                            variants.filter(
                              (_, position) => position !== index,
                            ),
                          )
                        }
                      >
                        <Trash2 size={15} />
                      </button>
                    </div>
                    <div className="form-grid">
                      <label className="field">
                        方案名称
                        <input
                          aria-label={`方案 ${index + 1} 名称`}
                          required
                          maxLength={40}
                          value={variant.name}
                          onChange={(event) =>
                            updateVariant(index, { name: event.target.value })
                          }
                        />
                      </label>
                      <label className="field">
                        经营策略
                        <select
                          aria-label={`方案 ${index + 1} 策略`}
                          value={variant.strategy_id}
                          onChange={(event) =>
                            updateVariant(index, {
                              strategy_id: event.target.value,
                            })
                          }
                        >
                          {availableStrategies.map((strategy) => (
                            <option key={strategy.id} value={strategy.id}>
                              {strategy.name}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="field">
                        决策引擎
                        <select
                          aria-label={`方案 ${index + 1} 引擎`}
                          value={variant.mode}
                          onChange={(event) =>
                            updateVariant(index, {
                              mode: event.target.value as Mode,
                            })
                          }
                        >
                          <option value="rule">策略引擎</option>
                          <option value="llm">LLM Agent</option>
                        </select>
                      </label>
                      <label className="field">
                        决策流程
                        <select
                          aria-label={`方案 ${index + 1} 流程`}
                          value={variant.workflow}
                          onChange={(event) =>
                            updateVariant(index, {
                              workflow: event.target
                                .value as ExperimentVariant["workflow"],
                            })
                          }
                        >
                          <option value="direct">{variant.mode === "llm" ? "标准决策" : "按规则决策"}</option>
                          <option value="reviewed">{variant.mode === "llm" ? "试算与审核" : "规则试算与风险检查"}</option>
                          <option value="adaptive">{variant.mode === "llm" ? "自主规划与动态审核" : "按风险触发规则试算"}</option>
                        </select>
                      </label>
                      {variant.mode === "llm" && (
                        <label className="field">
                          模型连接
                          <select
                            aria-label={`方案 ${index + 1} 模型`}
                            value={variant.model_profile_id || "default"}
                            onChange={(event) =>
                              updateVariant(index, {
                                model_profile_id: event.target.value,
                              })
                            }
                          >
                            {profiles.data
                              ?.filter((profile) => profile.enabled)
                              .map((profile) => (
                                <option key={profile.id} value={profile.id}>
                                  {profile.name} · {profile.model}
                                </option>
                              ))}
                          </select>
                        </label>
                      )}
                    </div>
                    <AgentOptionsFields
                      label={`方案 ${index + 1} `}
                      mode={variant.mode}
                      value={variant.agent_options}
                      onChange={(agent_options) =>
                        updateVariant(index, { agent_options })
                      }
                    />
                  </section>
                ))}
                {variants.length < 4 && (
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={() =>
                      setVariants([
                        ...variants,
                        {
                          name: `对照方案 ${variants.length}`,
                          strategy_id: "balanced",
                          mode: "rule",
                          workflow: "direct",
                          model_profile_id: "default",
                        },
                      ])
                    }
                  >
                    <Plus size={14} />
                    添加对照方案
                  </Button>
                )}
              </div>
            ) : (
              <div className="field">
                <span>参与策略 · {strategyIds.length} 项</span>
                <div className="strategy-checkboxes">
                  {strategies.data.map((strategy) => (
                    <label
                      key={strategy.id}
                      className={
                        strategyIds.includes(strategy.id) ? "selected" : ""
                      }
                    >
                      <input
                        type="checkbox"
                        checked={strategyIds.includes(strategy.id)}
                        onChange={(event) =>
                          setStrategyIds(
                            event.target.checked
                              ? [...strategyIds, strategy.id]
                              : strategyIds.filter((id) => id !== strategy.id),
                          )
                        }
                      />
                      <Avatar
                        name={strategy.name}
                        color={strategy.color}
                        small
                      />
                      <span>{strategy.name}</span>
                    </label>
                  ))}
                </div>
              </div>
            )}
          </div>
          <div className="modal-footer">
            <Button
              variant="secondary"
              type="button"
              onClick={() => setCreating(false)}
            >
              取消
            </Button>
            <Button
              type="submit"
              disabled={
                !comparison &&
                (strategyIds.length < 2 || strategyIds.length > 4)
              }
              busy={busy}
            >
              <Play size={15} />
              创建并运行
            </Button>
          </div>
        </form>
      </Modal>
    </>
  );
}
