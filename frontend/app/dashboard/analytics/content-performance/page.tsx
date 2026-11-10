"use client";

import { useState } from "react";

import { useAnalytics, useAnalyticsData } from "@/components/analytics/analytics-provider";
import { BarChart, ChartCard, LineChart } from "@/components/analytics/charts";
import { StatTile } from "@/components/analytics/metric-card";
import { PostTable } from "@/components/analytics/post-table";
import { ApiError, apiRequest } from "@/lib/api";
import { formatDate, formatDay, formatNumber } from "@/lib/analytics-format";
import { PLATFORM_COLORS, type AISummary, type ContentPerformance } from "@/lib/analytics-types";

function AISummarySection() {
  const { workspaceId, query } = useAnalytics();
  const [summary, setSummary] = useState<AISummary | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const request = async () => {
    if (!workspaceId) return;
    setBusy(true);
    setError(null);
    try {
      setSummary(await apiRequest<AISummary>(`/workspaces/${workspaceId}/analytics/content-performance/summary?${query()}`, { method: "POST" }));
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "The summary could not be generated.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="rounded-2xl border border-dashed border-slate-300 bg-white p-5" aria-label="AI interpretation">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold">AI interpretation (optional)</h2>
        <button type="button" onClick={() => void request()} disabled={busy} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm disabled:opacity-50">
          {busy ? "Asking Groq…" : "Generate summary with Groq"}
        </button>
      </div>
      <p className="mt-1 text-xs text-slate-500">Describes the measured data above in plain language. It is an AI interpretation, not a verified explanation, and it does not predict future results.</p>
      {error && (
        <p role="alert" className="mt-2 text-sm text-red-800">
          {error}
        </p>
      )}
      {summary && (
        <div className="mt-3 rounded-lg bg-slate-50 p-3 text-sm">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{summary.label}</p>
          {summary.available ? <p className="mt-2 whitespace-pre-wrap text-slate-800">{summary.text}</p> : <p className="mt-2 text-slate-600">Not available: {summary.reason}</p>}
          {summary.model && <p className="mt-2 text-xs text-slate-500">Model: {summary.model}</p>}
        </div>
      )}
    </section>
  );
}

export default function ContentPerformancePage() {
  const { workspaceId, filters, query, dataVersion } = useAnalytics();
  const path = workspaceId ? `/workspaces/${workspaceId}/analytics/content-performance?${query()}` : null;
  const { data, loading, error } = useAnalyticsData<ContentPerformance>(path, [dataVersion]);
  const rangeLabel = `${formatDate(`${filters.start}T00:00:00Z`)} – ${formatDate(`${filters.end}T00:00:00Z`)}`;
  return (
    <>
      {error && (
        <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">
          {error}
        </p>
      )}
      {!data && loading && <p className="text-sm text-slate-500">Loading content performance…</p>}
      {data && (
        <div className={loading ? "space-y-6 opacity-60 transition-opacity" : "space-y-6"}>
          <section className="grid gap-4 md:grid-cols-4" aria-label="Period summary">
            <StatTile label="Posts measured" value={data.post_count} note={`${data.consistency.posts_per_week} posts per week · longest gap ${data.consistency.longest_gap_days ?? "n/a"} days`} />
            <StatTile label="Engagements this period" value={data.period_change.current_engagements} delta={data.period_change.change_percent} note={`Previous period: ${formatNumber(data.period_change.previous_engagements)} (${data.period_change.previous_posts} posts)`} />
            <StatTile label="Active posting days" value={data.consistency.active_days} note="Days with at least one measured post" />
            <StatTile
              label="Best-performing format"
              value={data.best_format?.average_engagement_rate ?? null}
              unit="percent"
              note={data.best_format ? `${data.best_format.platform_label} ${data.best_format.content_format_label} · ${data.best_format.posts} posts · ${data.best_format_note}` : data.best_format_note}
            />
          </section>
          {data.post_count === 0 ? (
            <p className="rounded-2xl border border-slate-200 bg-white p-5 text-sm text-slate-600">No measured posts in this range. Posts appear after the next synchronization.</p>
          ) : (
            <>
              <section className="rounded-2xl border border-slate-200 bg-white p-5" aria-label="Highest-performing posts">
                <h2 className="font-semibold">Highest-performing posts</h2>
                <p className="mt-1 text-xs text-slate-500">{data.ranking_method}</p>
                <div className="mt-3">
                  <PostTable posts={data.top_posts} compact />
                </div>
              </section>
              {data.bottom_posts.length > 0 && (
                <section className="rounded-2xl border border-slate-200 bg-white p-5" aria-label="Lowest-performing posts">
                  <h2 className="font-semibold">Lowest-performing posts</h2>
                  <p className="mt-1 text-xs text-slate-500">Same ranking, lowest values first.</p>
                  <div className="mt-3">
                    <PostTable posts={data.bottom_posts} compact />
                  </div>
                </section>
              )}
              <section className="grid gap-4 lg:grid-cols-2" aria-label="Formats and trends">
                <ChartCard
                  title="Content formats"
                  metricName="Average engagement rate per post (calculated), by platform and format"
                  rangeLabel={rangeLabel}
                  unit="percent"
                  loading={false}
                  error={null}
                  empty={data.formats.every((format) => format.average_engagement_rate === null)}
                  emptyMessage="Engagement rates need reach data; no format has it in this range."
                >
                  <BarChart
                    unit="percent"
                    ariaLabel="Average engagement rate by content format"
                    items={data.formats.map((format) => ({
                      key: `${format.platform}:${format.content_format}`,
                      label: `${format.platform_label} · ${format.content_format_label} (${format.posts} posts${format.enough_data ? "" : ", indicative"})`,
                      value: format.average_engagement_rate,
                      color: PLATFORM_COLORS[format.platform],
                      note: format.note,
                    }))}
                  />
                  <ul className="mt-2 text-xs text-slate-500">
                    {data.formats.map((format) => (
                      <li key={`${format.platform}:${format.content_format}`}>
                        {format.platform_label} {format.content_format_label}: avg engagements {formatNumber(format.average_engagements)}, avg reach {formatNumber(format.average_reach)}
                      </li>
                    ))}
                  </ul>
                </ChartCard>
                <ChartCard
                  title="Engagement trend"
                  metricName="Engagements and reach of posts published each week (platform definitions differ)"
                  rangeLabel={rangeLabel}
                  unit="count"
                  loading={false}
                  error={null}
                  empty={data.weekly_trend.every((week) => week.engagements === null && week.reach === null)}
                  emptyMessage="No weekly engagement data yet."
                >
                  <LineChart
                    ariaLabel="Weekly engagements and reach of published posts"
                    series={[
                      { key: "engagements", label: "Engagements", color: "var(--series-3)", points: data.weekly_trend.map((week) => ({ date: week.week_start, value: week.engagements })) },
                      { key: "reach", label: "Reach / unique viewers", color: "var(--series-4)", points: data.weekly_trend.map((week) => ({ date: week.week_start, value: week.reach })) },
                    ]}
                  />
                  <p className="mt-2 text-xs text-slate-500">Posts per week: {data.weekly_trend.map((week) => `${formatDay(week.week_start)}: ${week.posts}`).join(" · ")}</p>
                </ChartCard>
              </section>
              <AISummarySection />
            </>
          )}
          <footer className="text-xs text-slate-500">
            {data.notes.map((note) => (
              <p key={note}>{note}</p>
            ))}
          </footer>
        </div>
      )}
    </>
  );
}
