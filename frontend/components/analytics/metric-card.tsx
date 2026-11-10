"use client";

import { availabilityText, formatChange, formatDateTime, formatNumber } from "@/lib/analytics-format";
import { PLATFORM_COLORS, type MetricSummary, type PlatformMetric } from "@/lib/analytics-types";

function Change({ change }: { change: number | null }) {
  const { text, direction } = formatChange(change);
  const tone = direction === "up" ? "text-emerald-800" : direction === "down" ? "text-red-800" : "text-slate-500";
  const arrow = direction === "up" ? "▲" : direction === "down" ? "▼" : "";
  return (
    <span className={`text-xs ${tone}`}>
      {arrow && <span aria-hidden>{arrow} </span>}
      {text} <span className="text-slate-500">vs previous period</span>
    </span>
  );
}

export function PlatformValue({ entry, label }: { entry: PlatformMetric; label?: string }) {
  const unavailable = entry.value === null;
  return (
    <div className="flex items-start gap-3 py-2">
      <span aria-hidden className="mt-1.5 inline-block h-3 w-3 shrink-0 rounded-sm" style={{ background: PLATFORM_COLORS[entry.platform] }} />
      <div className="min-w-0 flex-1">
        <p className="text-xs text-slate-500">{label ?? entry.platform_label}</p>
        {unavailable ? (
          <p className="text-sm font-medium text-slate-500">
            Not available
            {entry.reason && <span className="block text-xs font-normal text-slate-500">{entry.reason}</span>}
          </p>
        ) : (
          <>
            <p className="text-2xl font-semibold text-slate-900">{formatNumber(entry.value, entry.unit)}</p>
            <Change change={entry.change_percent} />
            {entry.availability === "partial" && (
              <p className="text-xs text-amber-800">
                Partial: {entry.accounts_with_data} of {entry.accounts_total} accounts reported data.
              </p>
            )}
          </>
        )}
        {entry.definition && (
          <details className="mt-1 text-xs text-slate-600">
            <summary className="cursor-pointer select-none text-indigo-700">
              {entry.source_metric ? `Definition (${entry.source_metric})` : "Definition"}
            </summary>
            <p className="mt-1">{entry.definition}</p>
            {entry.collected_at && <p className="mt-1 text-slate-500">Collected {formatDateTime(entry.collected_at)}.</p>}
          </details>
        )}
      </div>
    </div>
  );
}

export function MetricCard({ metric }: { metric: MetricSummary }) {
  return (
    <article className="rounded-2xl border border-slate-200 bg-white p-5" aria-label={metric.label}>
      <h3 className="text-sm font-semibold text-slate-900">{metric.label}</h3>
      {metric.combined_value !== null && (
        <p className="mt-1 text-xs text-slate-500" title={metric.combined_note ?? undefined}>
          Combined: <strong className="text-slate-700">{formatNumber(metric.combined_value)}</strong> · {metric.combined_note}
        </p>
      )}
      {!metric.comparable && metric.platforms.length > 1 && (
        <p className="mt-1 text-xs text-amber-800">Shown per platform only: the platforms define this metric differently.</p>
      )}
      <div className="mt-1 divide-y divide-slate-100">
        {metric.platforms.map((entry) => (
          <PlatformValue key={entry.platform} entry={entry} />
        ))}
      </div>
    </article>
  );
}

export function StatTile({ label, value, delta, note, unit }: { label: string; value: number | null; delta?: number | null; note?: string | null; unit?: string }) {
  return (
    <article className="rounded-2xl border border-slate-200 bg-white p-5">
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 text-3xl font-semibold text-slate-900">{formatNumber(value, unit)}</p>
      {delta !== undefined && <Change change={delta ?? null} />}
      {note && <p className="mt-1 text-xs text-slate-500">{note}</p>}
    </article>
  );
}

export function AvailabilityBadge({ reason }: { reason: string | null | undefined }) {
  return (
    <span className="inline-flex rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600" title={availabilityText(reason)}>
      {availabilityText(reason)}
    </span>
  );
}
