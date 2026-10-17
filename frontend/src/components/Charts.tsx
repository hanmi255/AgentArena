import { useState } from "react";
import { money } from "../api";
import type { HistoryPoint, Merchant } from "../types";

export const COLORS = {
  violet: "#8063e5",
  orange: "#e9a157",
  teal: "#4aa58b",
  blue: "#6399d7",
};

export function ProfitChart({
  history,
  merchants,
  selectedRound,
  tall = false,
}: {
  history: HistoryPoint[];
  merchants: Merchant[];
  selectedRound?: number;
  tall?: boolean;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const width = 740,
    height = tall ? 280 : 220,
    left = 58,
    right = 20,
    top = 24,
    bottom = 32;
  const values = history.flatMap((point) =>
    point.merchants.map((merchant) => merchant.profit),
  );
  const low = Math.min(0, ...values),
    high = Math.max(10000, ...values);
  const range = high - low;
  const min = low - range * 0.12,
    max = high + range * 0.15;
  const x = (index: number) =>
    left + (index / Math.max(1, history.length - 1)) * (width - left - right);
  const y = (value: number) =>
    top + ((max - value) / (max - min)) * (height - top - bottom);
  const active = hover ?? selectedRound;
  return (
    <div className="profit-chart" onMouseLeave={() => setHover(null)}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label="各商店累计净收益趋势"
      >
        {[0, 1, 2, 3].map((index) => {
          const value = min + ((max - min) * index) / 3;
          return (
            <g key={index}>
              <line
                x1={left}
                x2={width - right}
                y1={y(value)}
                y2={y(value)}
                stroke="#eeedf3"
                strokeDasharray="4 5"
              />
              <text
                x={left - 10}
                y={y(value) + 4}
                textAnchor="end"
                className="chart-label"
              >
                {money(Math.round(value), true)}
              </text>
            </g>
          );
        })}
        {history
          .filter(
            (point, index) =>
              index === 0 ||
              index === history.length - 1 ||
              point.round % Math.max(1, Math.ceil(history.length / 6)) === 0,
          )
          .map((point) => (
            <text
              key={point.round}
              x={x(point.round)}
              y={height - 9}
              textAnchor="middle"
              className="chart-label"
            >
              {point.round === 0 ? "开赛" : `R${point.round}`}
            </text>
          ))}
        {merchants.map((merchant) => {
          const path = history
            .map(
              (point, index) =>
                `${index === 0 ? "M" : "L"}${x(index)},${y(point.merchants.find((item) => item.id === merchant.id)!.profit)}`,
            )
            .join(" ");
          const last = history
            .at(-1)!
            .merchants.find((item) => item.id === merchant.id)!;
          return (
            <g key={merchant.id}>
              <path
                d={path}
                fill="none"
                stroke={COLORS[merchant.color]}
                strokeWidth="2.7"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <circle
                cx={x(history.length - 1)}
                cy={y(last.profit)}
                r="3.5"
                fill={COLORS[merchant.color]}
              />
            </g>
          );
        })}
        {active !== undefined && active !== null && history[active] && (
          <g>
            <line
              x1={x(active)}
              x2={x(active)}
              y1={top}
              y2={height - bottom}
              stroke="#bdb6d3"
              strokeDasharray="3 4"
            />
            {history[active].merchants.map((item) => (
              <circle
                key={item.id}
                cx={x(active)}
                cy={y(item.profit)}
                r="4.5"
                fill={
                  COLORS[
                    merchants.find((merchant) => merchant.id === item.id)!.color
                  ]
                }
                stroke="white"
                strokeWidth="2"
              />
            ))}
          </g>
        )}
        <rect
          x={left}
          y={top}
          width={width - left - right}
          height={height - top - bottom}
          fill="transparent"
          onMouseMove={(event) => {
            const rect = event.currentTarget.getBoundingClientRect();
            setHover(
              Math.round(
                ((event.clientX - rect.left) / rect.width) *
                  (history.length - 1),
              ),
            );
          }}
        />
      </svg>
      {hover !== null && history[hover] && (
        <div className="chart-tooltip">
          <strong>第 {hover} 回合</strong>
          {history[hover].merchants.map((item) => {
            const merchant = merchants.find((entry) => entry.id === item.id)!;
            return (
              <span key={item.id}>
                <i style={{ background: COLORS[merchant.color] }} />
                {merchant.name}
                <b>¥{money(item.profit)}</b>
              </span>
            );
          })}
        </div>
      )}
      <div className="chart-legend">
        {merchants.map((merchant) => (
          <span key={merchant.id}>
            <i style={{ background: COLORS[merchant.color] }} />
            {merchant.name}
          </span>
        ))}
      </div>
    </div>
  );
}

export function Sparkline({
  values,
  color,
}: {
  values: number[];
  color: string;
}) {
  const min = Math.min(0, ...values),
    max = Math.max(1, ...values),
    range = max - min;
  return (
    <svg viewBox="0 0 120 34" className="sparkline" aria-hidden="true">
      <path
        d={values
          .map(
            (value, index) =>
              `${index ? "L" : "M"}${(index / Math.max(1, values.length - 1)) * 120},${30 - ((value - min) / range) * 25}`,
          )
          .join(" ")}
        fill="none"
        stroke={color}
        strokeWidth="2.5"
        strokeLinecap="round"
      />
    </svg>
  );
}
