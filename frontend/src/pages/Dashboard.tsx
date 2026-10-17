import { useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  BarChart3,
  CircleDot,
  Flag,
  Plus,
  ShoppingBag,
  Trophy,
  Zap,
} from "lucide-react";
import { count, date, money, signedMoney, useResource } from "../api";
import type { Catalog, Overview } from "../types";
import { CreateArena } from "../components/CreateArena";
import {
  Avatar,
  Button,
  Empty,
  ErrorState,
  Loading,
  Metric,
  StatusBadge,
} from "../components/ui";

export function Dashboard({ catalog }: { catalog: Catalog }) {
  const { data, error, reload } = useResource<Overview>("/overview");
  const [creating, setCreating] = useState(false);
  const [filter, setFilter] = useState("all");
  if (error) return <ErrorState message={error} retry={reload} />;
  if (!data) return <Loading />;
  const matches = data.arenas.filter(
    (arena) =>
      filter === "all" ||
      (filter === "live"
        ? arena.status !== "completed"
        : arena.status === "completed"),
  );
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">THE PLAYING FIELD</div>
          <h1>
            竞技场
            <span className="title-dot" />
          </h1>
        </div>
        <Button onClick={() => setCreating(true)}>
          <Plus size={17} />
          创建对局
        </Button>
      </div>
      <div className="dashboard-hero">
        <div className="hero-copy">
          <span className="hero-chip">
            <i />
            AGENT ECONOMY
          </span>
          <h2>
            让 Agent 开店，
            <br />
            看决策如何变成<span>收益。</span>
          </h2>
          <div className="hero-facts">
            <span>
              ¥10,000 <small>初始资金 / 店</small>
            </span>
            <span>
              20 <small>经营回合</small>
            </span>
            <span>
              3 <small>参赛商店</small>
            </span>
          </div>
          <div className="hero-actions">
            <Button variant="dark" onClick={() => setCreating(true)}>
              开启一场竞争
              <ArrowUpRight size={17} />
            </Button>
            {data.arenas.some((arena) => arena.current_round > 0) && (
              <Link
                className="hero-watch"
                to={`/arenas/${data.arenas.find((arena) => arena.current_round > 0)!.id}`}
              >
                观看经营回放 <ArrowRight size={16} />
              </Link>
            )}
          </div>
        </div>
        <div className="hero-illustration" aria-hidden="true">
          <div className="orbit orbit-one" />
          <div className="orbit orbit-two" />
          <div className="hero-building building-back">
            <div className="building-roof" />
            <span>A</span>
            <div className="building-window" />
          </div>
          <div className="hero-building building-front">
            <div className="building-roof" />
            <span>B</span>
            <div className="building-window" />
          </div>
          <div className="hero-building building-side">
            <div className="building-roof" />
            <span>C</span>
            <div className="building-window" />
          </div>
          <span className="floating-label float-profit">
            <ArrowUpRight size={14} />
            利润增长
          </span>
          <span className="floating-label float-live">
            <i />
            市场开放
          </span>
          <span className="hero-grid-line" />
        </div>
      </div>
      <div className="metric-grid dashboard-metrics">
        <Metric
          label="累计对局"
          value={data.stats.arenas.toString().padStart(2, "0")}
          suffix={
            <>
              <span className="positive">{data.stats.active} 场进行中</span>
              <span>全部市场</span>
            </>
          }
          icon={<Flag size={17} />}
        />
        <Metric
          label="已完成回合"
          value={count(data.stats.rounds)}
          suffix={
            <>
              <span>{data.stats.completed} 场已完赛</span>
              <BarChart3 size={15} />
            </>
          }
          icon={<CircleDot size={17} />}
        />
        <Metric
          label="市场累计营收"
          value={
            <>
              <span className="currency">¥</span>
              {money(data.stats.revenue)}
            </>
          }
          suffix={
            <>
              <span>所有商店销售合计</span>
              <ArrowUpRight size={15} />
            </>
          }
          icon={<ShoppingBag size={17} />}
        />
        <Metric
          label="可用策略"
          value={data.strategies.length.toString().padStart(2, "0")}
          suffix={
            <Link to="/strategies">
              进入策略库
              <ArrowRight size={14} />
            </Link>
          }
          icon={<Zap size={17} />}
        />
      </div>
      <div className="section-heading">
        <h2>
          我的对局<span className="number-chip">{data.arenas.length}</span>
        </h2>
        <div className="segmented">
          {[
            ["all", "全部"],
            ["live", "未完赛"],
            ["completed", "已完赛"],
          ].map(([key, label]) => (
            <button
              key={key}
              className={filter === key ? "active" : ""}
              onClick={() => setFilter(key)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <div className="arena-grid">
        {matches.map((arena) => (
          <Link
            to={`/arenas/${arena.id}`}
            className="arena-card"
            key={arena.id}
          >
            <div className="arena-card-top">
              <StatusBadge status={arena.status} />
              <span className="card-date">
                {date(arena.created_at)}
                <ArrowUpRight size={17} />
              </span>
            </div>
            <h3>{arena.name}</h3>
            <p className="arena-card-meta">
              {
                catalog.scenarios.find((item) => item.id === arena.scenario)
                  ?.name
              }
              <span />
              {arena.merchants.length} 家商店
              <span />
              种子 {arena.seed}
            </p>
            <div className="arena-card-stores">
              {arena.merchants.map((merchant) => (
                <div key={merchant.id}>
                  <Avatar name={merchant.name} color={merchant.color} small />
                  <span>{merchant.name}</span>
                  <small
                    className={merchant.profit >= 0 ? "positive" : "negative"}
                  >
                    {signedMoney(merchant.profit)}
                  </small>
                </div>
              ))}
            </div>
            <div className="arena-progress">
              <div
                style={{
                  width: `${(arena.current_round / arena.total_rounds) * 100}%`,
                }}
              />
            </div>
            <div className="arena-card-bottom">
              <span>
                回合 <b>{arena.current_round}</b> / {arena.total_rounds}
              </span>
              <span>
                <Trophy size={13} />
                {arena.current_round > 0 ? `${arena.leader} 领跑` : "等待开赛"}
              </span>
            </div>
          </Link>
        ))}
        <button className="create-arena-tile" onClick={() => setCreating(true)}>
          <span>
            <Plus size={26} />
          </span>
          <strong>新的市场，新的可能</strong>
          <small>
            创建对局
            <ArrowRight size={14} />
          </small>
        </button>
      </div>
      {matches.length === 0 && data.arenas.length > 0 && (
        <Empty title="暂无此类对局" />
      )}
      <div className="bottom-notes">
        <span>
          <i />
          ALL SYSTEMS OPERATIONAL
        </span>
        <span>AgentArena / Market Simulation</span>
      </div>
      <CreateArena
        open={creating}
        close={() => setCreating(false)}
        strategies={data.strategies}
        catalog={catalog}
      />
    </>
  );
}
