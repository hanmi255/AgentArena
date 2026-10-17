import { useState } from "react";
import {
  Copy,
  FileCode2,
  Pencil,
  Plus,
  SlidersHorizontal,
  Sparkles,
  Target,
  Wallet,
  Zap,
} from "lucide-react";
import { api, money, useResource } from "../api";
import type { Color, Strategy } from "../types";
import {
  Avatar,
  Button,
  ErrorState,
  Loading,
  Modal,
  useToast,
} from "../components/ui";

const APPROACHES = {
  balanced: "稳健经营",
  discount: "价格竞争",
  premium: "品牌溢价",
  adaptive: "动态调整",
};
const BLANK: Omit<Strategy, "id"> = {
  name: "我的新策略",
  description: "",
  approach: "adaptive",
  margin: 0.85,
  stock_days: 1.3,
  marketing_budget: 8000,
  prompt: "根据市场需求、库存周转和现金流，制定每轮的采购、定价与营销方案。",
  color: "blue",
};

export function StrategiesPage() {
  const { data, error, reload } = useResource<Strategy[]>("/strategies");
  const [editing, setEditing] = useState(false);
  const [id, setId] = useState<string | null>(null);
  const [form, setForm] = useState<Omit<Strategy, "id">>(BLANK);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  if (error) return <ErrorState message={error} retry={reload} />;
  if (!data) return <Loading />;
  const open = (strategy?: Strategy, copy = false) => {
    setId(strategy && !copy ? strategy.id : null);
    setForm(
      strategy
        ? { ...strategy, name: strategy.name + (copy ? " · 副本" : "") }
        : { ...BLANK },
    );
    setEditing(true);
  };
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">THE STRATEGY ROOM</div>
          <h1>
            策略库
            <span className="title-dot" />
          </h1>
        </div>
        <Button onClick={() => open()}>
          <Plus size={17} />
          创建策略
        </Button>
      </div>
      <div className="strategy-banner">
        <div>
          <span className="eyebrow">YOUR EDGE IN THE MARKET</span>
          <h2>同一市场，不同解法。</h2>
        </div>
        <div className="strategy-banner-stat">
          <strong>{String(data.length).padStart(2, "0")}</strong>
          <span>可用经营策略</span>
        </div>
        <div className="strategy-banner-art" aria-hidden="true">
          <Target size={90} strokeWidth={0.7} />
          <Sparkles size={30} />
        </div>
      </div>
      <div className="strategy-grid">
        {data.map((strategy) => (
          <article
            className={`strategy-card strategy-${strategy.color}`}
            key={strategy.id}
          >
            <div className="strategy-card-header">
              <Avatar name={strategy.name} color={strategy.color} />
              <span className="subtle-chip">
                {strategy.built_in ? "预设策略" : "自定义"}
              </span>
              <button
                className="icon-button"
                aria-label={`复制${strategy.name}`}
                onClick={() => open(strategy, true)}
              >
                <Copy size={16} />
              </button>
            </div>
            <h2>{strategy.name}</h2>
            <p>{strategy.description}</p>
            <span className="approach-tag">
              <Zap size={12} />
              {APPROACHES[strategy.approach]}
            </span>
            <div className="strategy-parameters">
              <span>
                <Target size={14} />
                目标加价率<b>{Math.round(strategy.margin * 100)}%</b>
              </span>
              <span>
                <SlidersHorizontal size={14} />
                目标备货<b>{strategy.stock_days} 回合</b>
              </span>
              <span>
                <Wallet size={14} />
                每轮营销<b>¥{money(strategy.marketing_budget)}</b>
              </span>
            </div>
            <div className="strategy-prompt">
              <FileCode2 size={15} />
              <p>{strategy.prompt}</p>
            </div>
            <Button variant="secondary" onClick={() => open(strategy)}>
              <Pencil size={14} />
              编辑策略
            </Button>
          </article>
        ))}
      </div>
      <Modal
        title={id ? "编辑策略" : "创建策略"}
        open={editing}
        onClose={() => setEditing(false)}
        wide
      >
        <form
          onSubmit={async (event) => {
            event.preventDefault();
            setBusy(true);
            try {
              await api(`/strategies${id ? `/${id}` : ""}`, {
                method: id ? "PUT" : "POST",
                body: JSON.stringify(form),
              });
              setEditing(false);
              reload();
              toast("策略已保存");
            } catch (cause) {
              toast((cause as Error).message, true);
            } finally {
              setBusy(false);
            }
          }}
        >
          <div className="modal-body">
            <div className="form-grid">
              <label className="field">
                策略名称
                <input
                  required
                  maxLength={30}
                  value={form.name}
                  onChange={(event) =>
                    setForm({ ...form, name: event.target.value })
                  }
                />
              </label>
              <label className="field">
                经营方式
                <select
                  value={form.approach}
                  onChange={(event) =>
                    setForm({
                      ...form,
                      approach: event.target.value as Strategy["approach"],
                    })
                  }
                >
                  {Object.entries(APPROACHES).map(([key, label]) => (
                    <option key={key} value={key}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <label className="field">
              策略摘要
              <input
                maxLength={120}
                value={form.description}
                onChange={(event) =>
                  setForm({ ...form, description: event.target.value })
                }
              />
            </label>
            <div className="form-grid three">
              <label className="field">
                目标加价率（%）
                <input
                  type="number"
                  required
                  min={10}
                  max={180}
                  value={Math.round(form.margin * 100)}
                  onChange={(event) =>
                    setForm({ ...form, margin: +event.target.value / 100 })
                  }
                />
              </label>
              <label className="field">
                目标备货回合
                <input
                  type="number"
                  required
                  min={0.5}
                  max={3}
                  step={0.1}
                  value={form.stock_days}
                  onChange={(event) =>
                    setForm({ ...form, stock_days: +event.target.value })
                  }
                />
              </label>
              <label className="field">
                每轮营销（元）
                <input
                  type="number"
                  required
                  min={0}
                  max={300}
                  value={form.marketing_budget / 100}
                  onChange={(event) =>
                    setForm({
                      ...form,
                      marketing_budget: Math.round(+event.target.value * 100),
                    })
                  }
                />
              </label>
            </div>
            <label className="field">
              Agent 策略指令
              <textarea
                required
                rows={6}
                maxLength={6000}
                value={form.prompt}
                onChange={(event) =>
                  setForm({ ...form, prompt: event.target.value })
                }
              />
            </label>
            <div className="field">
              <span>策略标识</span>
              <div className="color-options">
                {(["violet", "orange", "teal", "blue"] as Color[]).map(
                  (color) => (
                    <label
                      key={color}
                      className={`color-option color-${color} ${form.color === color ? "selected" : ""}`}
                    >
                      <input
                        aria-label={`${color} 标识`}
                        type="radio"
                        name="strategy-color"
                        checked={form.color === color}
                        onChange={() => setForm({ ...form, color })}
                      />
                      <span />
                    </label>
                  ),
                )}
              </div>
            </div>
          </div>
          <div className="modal-footer">
            <Button
              type="button"
              variant="secondary"
              onClick={() => setEditing(false)}
            >
              取消
            </Button>
            <Button type="submit" busy={busy}>
              保存策略
            </Button>
          </div>
        </form>
      </Modal>
    </>
  );
}
