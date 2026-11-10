"use client";

import { useId, useMemo, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";

import { formatDay, formatNumber, niceTicks } from "@/lib/analytics-format";

/*
 * Chart tokens (dataviz reference palette, validated on the white card surface):
 * series 1 blue = Facebook Page, series 2 orange = Instagram. Colour follows the
 * platform, never the position in the list.
 */
export const VIZ_STYLE = `
.viz-root { --surface-1: #ffffff; --text-primary: #0b0b0b; --text-secondary: #52514e; --text-muted: #898781;
  --series-1: #2a78d6; --series-2: #eb6834; --series-3: #1baf7a; --series-4: #eda100; --grid: #e1e0d9; --axis: #c3c2b7; }
`;

export type ChartSeries = {
  key: string;
  label: string;
  color: string;
  points: { date: string; value: number | null }[];
};

type ChartCardProps = {
  title: string;
  metricName: string;
  rangeLabel: string;
  unit: string;
  definition?: string | null;
  loading: boolean;
  error: string | null;
  empty: boolean;
  emptyMessage?: string;
  hasPreviousData?: boolean;
  children: ReactNode;
};

export function ChartCard({ title, metricName, rangeLabel, unit, definition, loading, error, empty, emptyMessage, hasPreviousData, children }: ChartCardProps) {
  const unitLabel = unit === "percent" ? "percent" : unit === "milliseconds" ? "milliseconds" : "count";
  return (
    <section className="viz-root rounded-2xl border border-slate-200 bg-white p-5" aria-busy={loading}>
      <style>{VIZ_STYLE}</style>
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h3 className="font-semibold text-slate-900">{title}</h3>
          <p className="text-xs text-slate-500">
            {metricName} · {rangeLabel} · unit: {unitLabel}
          </p>
        </div>
        {definition && (
          <details className="text-xs text-slate-600">
            <summary className="cursor-pointer select-none text-indigo-700">Definition</summary>
            <p className="mt-1 max-w-md">{definition}</p>
          </details>
        )}
      </header>
      {error ? (
        <p role="alert" className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-800">
          {error}
        </p>
      ) : loading && !hasPreviousData ? (
        <p className="mt-4 text-sm text-slate-500">Loading chart…</p>
      ) : empty ? (
        <p className="mt-4 rounded-lg bg-slate-50 p-3 text-sm text-slate-600">{emptyMessage ?? "No data is available for this range."}</p>
      ) : (
        <div className={loading ? "mt-4 opacity-60 transition-opacity" : "mt-4"}>{children}</div>
      )}
    </section>
  );
}

const WIDTH = 720;
const HEIGHT = 240;
const PAD = { top: 16, right: 56, bottom: 28, left: 48 };

type LineChartProps = { series: ChartSeries[]; unit?: string; ariaLabel: string };

export function LineChart({ series, unit = "count", ariaLabel }: LineChartProps) {
  const id = useId();
  const [hover, setHover] = useState<number | null>(null);
  const [showTable, setShowTable] = useState(false);
  const dates = useMemo(() => {
    const set = new Set<string>();
    series.forEach((entry) => entry.points.forEach((point) => set.add(point.date)));
    return [...set].sort();
  }, [series]);
  const max = useMemo(() => Math.max(0, ...series.flatMap((entry) => entry.points.map((point) => point.value ?? 0))), [series]);
  const ticks = niceTicks(max);
  const top = ticks[ticks.length - 1] || 1;
  const plotWidth = WIDTH - PAD.left - PAD.right;
  const plotHeight = HEIGHT - PAD.top - PAD.bottom;
  const x = (index: number) => PAD.left + (dates.length > 1 ? (index / (dates.length - 1)) * plotWidth : plotWidth / 2);
  const y = (value: number) => PAD.top + plotHeight - (value / top) * plotHeight;

  const paths = series.map((entry) => {
    const byDate = new Map(entry.points.map((point) => [point.date, point.value]));
    let d = "";
    let pen = false;
    dates.forEach((date, index) => {
      const value = byDate.get(date);
      if (value === null || value === undefined) {
        pen = false;
        return;
      }
      d += `${pen ? "L" : "M"}${x(index).toFixed(1)},${y(value).toFixed(1)} `;
      pen = true;
    });
    const lastIndex = [...dates].map((date, index) => ({ date, index })).reverse().find(({ date }) => byDate.get(date) !== null && byDate.get(date) !== undefined)?.index;
    return { entry, d, byDate, lastIndex };
  });

  const nearest = (clientX: number, target: SVGSVGElement) => {
    const rect = target.getBoundingClientRect();
    const relative = ((clientX - rect.left) / rect.width) * WIDTH;
    let best = 0;
    let bestDistance = Infinity;
    dates.forEach((_date, index) => {
      const distance = Math.abs(x(index) - relative);
      if (distance < bestDistance) {
        bestDistance = distance;
        best = index;
      }
    });
    return best;
  };

  const onKey = (event: KeyboardEvent<SVGSVGElement>) => {
    if (event.key === "ArrowRight") setHover((current) => Math.min(dates.length - 1, (current ?? -1) + 1));
    else if (event.key === "ArrowLeft") setHover((current) => Math.max(0, (current ?? dates.length) - 1));
    else if (event.key === "Escape") setHover(null);
    else return;
    event.preventDefault();
  };

  const tableId = `${id}-table`;
  const hoverLeft = hover !== null ? (x(hover) / WIDTH) * 100 : 0;
  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="h-auto w-full"
        role="img"
        aria-label={ariaLabel}
        aria-describedby={tableId}
        tabIndex={0}
        onPointerMove={(event: PointerEvent<SVGSVGElement>) => setHover(nearest(event.clientX, event.currentTarget))}
        onPointerLeave={() => setHover(null)}
        onBlur={() => setHover(null)}
        onKeyDown={onKey}
      >
        {ticks.map((tick) => (
          <g key={tick}>
            <line x1={PAD.left} x2={WIDTH - PAD.right} y1={y(tick)} y2={y(tick)} stroke="var(--grid)" strokeWidth={1} />
            <text x={PAD.left - 8} y={y(tick) + 3} textAnchor="end" fontSize={10} fill="var(--text-muted)" style={{ fontVariantNumeric: "tabular-nums" }}>
              {formatNumber(tick, unit)}
            </text>
          </g>
        ))}
        <line x1={PAD.left} x2={WIDTH - PAD.right} y1={y(0)} y2={y(0)} stroke="var(--axis)" strokeWidth={1} />
        {dates.map((date, index) =>
          dates.length <= 8 || index === 0 || index === dates.length - 1 || index % Math.ceil(dates.length / 6) === 0 ? (
            <text key={date} x={x(index)} y={HEIGHT - 8} textAnchor="middle" fontSize={10} fill="var(--text-muted)">
              {formatDay(date)}
            </text>
          ) : null,
        )}
        {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={PAD.top + plotHeight} stroke="var(--axis)" strokeWidth={1} />}
        {paths.map(({ entry, d, byDate, lastIndex }) => (
          <g key={entry.key}>
            <path d={d} fill="none" stroke={entry.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
            {lastIndex !== undefined && (
              <>
                <circle cx={x(lastIndex)} cy={y(byDate.get(dates[lastIndex]) ?? 0)} r={4} fill={entry.color} stroke="var(--surface-1)" strokeWidth={2} />
                {series.length <= 4 && (
                  <text x={x(lastIndex) + 8} y={y(byDate.get(dates[lastIndex]) ?? 0) + 3} fontSize={10} fill="var(--text-secondary)">
                    {formatNumber(byDate.get(dates[lastIndex]) ?? null, unit)}
                  </text>
                )}
              </>
            )}
            {hover !== null && byDate.get(dates[hover]) !== null && byDate.get(dates[hover]) !== undefined && (
              <circle cx={x(hover)} cy={y(byDate.get(dates[hover]) ?? 0)} r={4} fill={entry.color} stroke="var(--surface-1)" strokeWidth={2} />
            )}
          </g>
        ))}
      </svg>
      {hover !== null && (
        <div
          role="status"
          className="pointer-events-none absolute top-2 z-10 min-w-[9rem] rounded-lg border border-slate-200 bg-white p-2 text-xs shadow-sm"
          style={{ left: `min(max(${hoverLeft}%, 0%), calc(100% - 10rem))` }}
        >
          <p className="font-medium text-slate-900">{formatDay(dates[hover])}</p>
          {paths.map(({ entry, byDate }) => (
            <p key={entry.key} className="mt-1 flex items-center gap-2 text-slate-700">
              <span aria-hidden className="inline-block h-0.5 w-3" style={{ background: entry.color }} />
              <strong className="text-slate-900">{formatNumber(byDate.get(dates[hover]) ?? null, unit)}</strong>
              <span className="text-slate-500">{entry.label}</span>
            </p>
          ))}
        </div>
      )}
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs">
        {series.length >= 2 ? (
          <ul className="flex flex-wrap gap-4" aria-label="Legend">
            {series.map((entry) => (
              <li key={entry.key} className="flex items-center gap-2 text-slate-700">
                <span aria-hidden className="inline-block h-0.5 w-4 rounded" style={{ background: entry.color }} />
                {entry.label}
              </li>
            ))}
          </ul>
        ) : (
          <span />
        )}
        <button type="button" className="text-indigo-700" onClick={() => setShowTable((value) => !value)} aria-expanded={showTable} aria-controls={tableId}>
          {showTable ? "Hide table" : "Show table"}
        </button>
      </div>
      <table id={tableId} className={showTable ? "mt-2 w-full text-left text-xs" : "sr-only"}>
        <caption className="sr-only">{ariaLabel}</caption>
        <thead>
          <tr>
            <th className="py-1 pr-2 font-medium text-slate-600">Date</th>
            {series.map((entry) => (
              <th key={entry.key} className="py-1 pr-2 font-medium text-slate-600">
                {entry.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {dates.map((date) => (
            <tr key={date} className="border-t border-slate-100">
              <td className="py-1 pr-2">{formatDay(date)}</td>
              {paths.map(({ entry, byDate }) => (
                <td key={entry.key} className="py-1 pr-2" style={{ fontVariantNumeric: "tabular-nums" }}>
                  {formatNumber(byDate.get(date) ?? null, unit)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export type BarItem = { key: string; label: string; value: number | null; color: string; note?: string | null; href?: string };

export function BarChart({ items, unit = "count", ariaLabel }: { items: BarItem[]; unit?: string; ariaLabel: string }) {
  const id = useId();
  const [showTable, setShowTable] = useState(false);
  const max = Math.max(0, ...items.map((item) => item.value ?? 0)) || 1;
  const tableId = `${id}-table`;
  return (
    <div>
      <ul role="img" aria-label={ariaLabel} aria-describedby={tableId} className="space-y-2">
        {items.map((item) => (
          <li key={item.key} className="group text-xs" title={item.note ?? undefined}>
            <div className="flex items-center justify-between gap-2 text-slate-700">
              <span className="truncate">{item.label}</span>
              <strong className="shrink-0 text-slate-900" style={{ fontVariantNumeric: "tabular-nums" }}>
                {formatNumber(item.value, unit)}
              </strong>
            </div>
            <div className="mt-1 h-4 w-full rounded-r bg-slate-50">
              {item.value !== null && (
                <div
                  className="h-4 rounded-r transition-opacity group-hover:opacity-80"
                  style={{ width: `${Math.max(item.value > 0 ? 1 : 0, (item.value / max) * 100)}%`, background: item.color }}
                />
              )}
            </div>
          </li>
        ))}
      </ul>
      <button type="button" className="mt-2 text-xs text-indigo-700" onClick={() => setShowTable((value) => !value)} aria-expanded={showTable} aria-controls={tableId}>
        {showTable ? "Hide table" : "Show table"}
      </button>
      <table id={tableId} className={showTable ? "mt-2 w-full text-left text-xs" : "sr-only"}>
        <caption className="sr-only">{ariaLabel}</caption>
        <thead>
          <tr>
            <th className="py-1 pr-2 font-medium text-slate-600">Item</th>
            <th className="py-1 pr-2 font-medium text-slate-600">Value</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.key} className="border-t border-slate-100">
              <td className="py-1 pr-2">{item.label}</td>
              <td className="py-1 pr-2">{formatNumber(item.value, unit)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
