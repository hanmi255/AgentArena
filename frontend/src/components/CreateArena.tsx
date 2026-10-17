import { useEffect, useState } from "react";
import { ArrowRight, Plus, Trash2, WandSparkles } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { api, useResource } from "../api";
import type {
  Arena,
  ArenaInput,
  Catalog,
  Color,
  Mode,
  Strategy,
  ModelProfile,
} from "../types";
import { Avatar, Button, Modal, useToast } from "./ui";
import { AgentOptionsFields } from "../features/decisions/AgentOptionsFields";

const INITIAL: ArenaInput = {
  name: "新的商业对局",
  scenario: "neighborhood",
  total_rounds: 20,
  seed: 42,
  initial_capital: 1000000,
  merchants: [
    {
      name: "北辰商店",
      strategy_id: "balanced",
      mode: "rule",
      color: "violet",
    },
    {
      name: "橙子补给",
      strategy_id: "discount",
      mode: "rule",
      color: "orange",
    },
    { name: "青禾市集", strategy_id: "premium", mode: "rule", color: "teal" },
  ],
};
const DEFAULT_OPTIONS = {
  memory: "episodic" as const,
  negotiation: true,
  tool_budget: 6,
};
INITIAL.merchants = INITIAL.merchants.map((merchant) => ({
  ...merchant,
  workflow: "adaptive",
  agent_options: { ...DEFAULT_OPTIONS },
}));

export function CreateArena({
  open,
  close,
  strategies,
  catalog,
}: {
  open: boolean;
  close: () => void;
  strategies: Strategy[];
  catalog: Catalog;
}) {
  const [form, setForm] = useState<ArenaInput>(INITIAL);
  const [busy, setBusy] = useState(false);
  const profiles = useResource<ModelProfile[]>("/model-profiles");
  const toast = useToast(),
    navigate = useNavigate();
  useEffect(() => {
    if (open) setForm(structuredClone(INITIAL));
  }, [open]);
  const updateMerchant = (index: number, field: string, value: string) =>
    setForm({
      ...form,
      merchants: form.merchants.map((merchant, item) =>
        item === index
          ? {
              ...merchant,
              [field]: value,
              ...(field === "mode" && value === "llm"
                ? {
                    agent_options: {
                      ...DEFAULT_OPTIONS,
                      negotiation: false,
                      tool_budget: 3,
                    },
                  }
                : {}),
            }
          : merchant,
      ),
    });
  return (
    <Modal title="创建对局" open={open} onClose={close} wide>
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          setBusy(true);
          try {
            const arena = await api<Arena>("/arenas", {
              method: "POST",
              body: JSON.stringify(form),
            });
            close();
            navigate(`/arenas/${arena.id}`);
          } catch (error) {
            toast((error as Error).message, true);
          } finally {
            setBusy(false);
          }
        }}
      >
        <div className="modal-body">
          <label className="field">
            对局名称
            <input
              value={form.name}
              maxLength={60}
              required
              onChange={(event) =>
                setForm({ ...form, name: event.target.value })
              }
            />
          </label>
          <div className="field">
            <span>选择市场</span>
            <div className="scenario-options">
              {catalog.scenarios.map((scenario) => (
                <label
                  key={scenario.id}
                  className={`scenario-option ${form.scenario === scenario.id ? "selected" : ""}`}
                >
                  <input
                    type="radio"
                    name="scenario"
                    value={scenario.id}
                    checked={form.scenario === scenario.id}
                    onChange={() => setForm({ ...form, scenario: scenario.id })}
                  />
                  <span className="scenario-icon">
                    <WandSparkles size={18} />
                  </span>
                  <strong>{scenario.name}</strong>
                  <small>{scenario.tag}</small>
                </label>
              ))}
            </div>
          </div>
          <div className="form-grid three">
            <label className="field">
              回合数
              <input
                type="number"
                min={3}
                max={60}
                value={form.total_rounds}
                onChange={(event) =>
                  setForm({ ...form, total_rounds: +event.target.value })
                }
                required
              />
            </label>
            <label className="field">
              初始资金（元）
              <input
                type="number"
                min={3000}
                max={100000}
                step={1000}
                value={form.initial_capital / 100}
                onChange={(event) =>
                  setForm({
                    ...form,
                    initial_capital: Math.round(+event.target.value * 100),
                  })
                }
                required
              />
            </label>
            <label className="field">
              市场种子
              <input
                type="number"
                min={1}
                max={1000000}
                value={form.seed}
                onChange={(event) =>
                  setForm({ ...form, seed: +event.target.value })
                }
                required
              />
            </label>
          </div>
          <div className="section-label">
            参赛商店<span>{form.merchants.length} / 4</span>
          </div>
          <label className="field">
            人工审批
            <select
              value={form.approval_policy || "off"}
              onChange={(event) =>
                setForm({
                  ...form,
                  approval_policy: event.target
                    .value as ArenaInput["approval_policy"],
                })
              }
            >
              <option value="off">自动执行</option>
              <option value="risk">大额采购或现金风险时审批</option>
              <option value="all">每轮方案都需审批</option>
            </select>
          </label>
          <div className="merchant-form-list">
            {form.merchants.map((merchant, index) => (
              <div className="merchant-form" key={index}>
                <Avatar name={merchant.name} color={merchant.color} />
                <label className="field merchant-name">
                  商店 {index + 1} 名称
                  <input
                    aria-label={`商店 ${index + 1} 名称`}
                    value={merchant.name}
                    maxLength={20}
                    required
                    onChange={(event) =>
                      updateMerchant(index, "name", event.target.value)
                    }
                  />
                </label>
                <label className="field merchant-strategy">
                  经营策略
                  <select
                  aria-label={`商店 ${index + 1} 策略`}
                  value={merchant.strategy_id}
                  onChange={(event) =>
                    updateMerchant(index, "strategy_id", event.target.value)
                  }
                >
                  {strategies.map((strategy) => (
                    <option key={strategy.id} value={strategy.id}>
                      {strategy.name}
                    </option>
                  ))}
                  </select>
                </label>
                <label className="field merchant-engine">
                  决策引擎
                  <select
                  aria-label={`商店 ${index + 1} 决策引擎`}
                  value={merchant.mode}
                  onChange={(event) =>
                    updateMerchant(index, "mode", event.target.value as Mode)
                  }
                >
                  <option value="rule">策略引擎</option>
                  <option value="llm">LLM Agent</option>
                  </select>
                </label>
                <button
                  type="button"
                  className="icon-button"
                  disabled={form.merchants.length <= 2}
                  aria-label={`移除商店 ${index + 1}`}
                  onClick={() =>
                    setForm({
                      ...form,
                      merchants: form.merchants.filter(
                        (_, item) => item !== index,
                      ),
                    })
                  }
                >
                  <Trash2 size={16} />
                </button>
                <div className="merchant-model-fields">
                  {merchant.mode === "llm" && (
                    <label className="field">
                      模型连接
                      <select
                        required
                        aria-label={`商店 ${index + 1} 模型`}
                        value={merchant.model_profile_id || "default"}
                        onChange={(event) =>
                          updateMerchant(
                            index,
                            "model_profile_id",
                            event.target.value,
                          )
                        }
                      >
                        {(profiles.data || [])
                          .filter((profile) => profile.enabled)
                          .map((profile) => (
                            <option key={profile.id} value={profile.id}>
                              {profile.name} · {profile.model || "未配置"}
                            </option>
                          ))}
                      </select>
                    </label>
                  )}
                  <label className="field">
                    决策流程
                    <select
                      aria-label={`商店 ${index + 1} 决策流程`}
                      value={merchant.workflow || "direct"}
                      onChange={(event) =>
                        updateMerchant(index, "workflow", event.target.value)
                      }
                    >
                      <option value="direct">{merchant.mode === "llm" ? "标准决策" : "按规则决策"}</option>
                      <option value="reviewed">{merchant.mode === "llm" ? "试算与审核" : "规则试算与风险检查"}</option>
                      <option value="adaptive">{merchant.mode === "llm" ? "自主规划与动态审核" : "按风险触发规则试算"}</option>
                    </select>
                  </label>
                  <p className="model-cost-hint">
                    {merchant.mode === "llm"
                      ? "按回合调用模型 · 默认关闭多轮谈判以节省 Token"
                      : "按固定规则经营，可启用历史经验和规则议价；不调用模型，不消耗 Token。"}
                  </p>
                  <AgentOptionsFields
                    label={`商店 ${index + 1} `}
                    mode={merchant.mode}
                    value={merchant.agent_options}
                    onChange={(agent_options) =>
                      setForm({
                        ...form,
                        merchants: form.merchants.map((item, i) =>
                          i === index ? { ...item, agent_options } : item,
                        ),
                      })
                    }
                  />
                </div>
              </div>
            ))}
          </div>
          {form.merchants.length < 4 && (
            <Button
              variant="ghost"
              type="button"
              onClick={() =>
                setForm({
                  ...form,
                  merchants: [
                    ...form.merchants,
                    {
                      name: "蓝鲸便利",
                      strategy_id: "adaptive",
                      mode: "rule",
                      color: "blue" as Color,
                      workflow: "adaptive",
                      agent_options: { ...DEFAULT_OPTIONS },
                    },
                  ],
                })
              }
            >
              <Plus size={16} />
              添加商店
            </Button>
          )}
        </div>
        <div className="modal-footer">
          <Button variant="secondary" type="button" onClick={close}>
            取消
          </Button>
          <Button type="submit" busy={busy}>
            创建对局
            <ArrowRight size={16} />
          </Button>
        </div>
      </form>
    </Modal>
  );
}
