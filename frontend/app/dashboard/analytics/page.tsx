"use client";

import { useAnalytics, useAnalyticsData } from "@/components/analytics/analytics-provider";
import { ChartCard, LineChart, type ChartSeries } from "@/components/analytics/charts";
import { MetricCard, StatTile } from "@/components/analytics/metric-card";
import { PostTable } from "@/components/analytics/post-table";
import { formatDate, formatDateTime, formatNumber } from "@/lib/analytics-format";
import { PLATFORM_COLORS, type Overview, type PlatformComparison, type Timeseries } from "@/lib/analytics-types";

const CHARTS: { metric: string; title: string }[] = [
  { metric: "reach", title: "Reach over time" },
  { metric: "views", title: "Views over time" },
  { metric: "engagements", title: "Engagement over time" },
  { metric: "followers", title: "Audience (followers) over time" },
];

export function TimeseriesChart({ metric, title }: { metric: string; title: string }) {
  const { workspaceId, filters, query, dataVersion } = useAnalytics();
  const path = workspaceId ? `/workspaces/${workspaceId}/analytics/timeseries?${query({ metric, group_by: filters.accountId ? "account" : "platform" })}` : null;
  const { data, loading, error } = useAnalyticsData<Timeseries>(path, [dataVersion]);
  const supported = (data?.series ?? []).filter((series) => series.supported);
  const chartSeries: ChartSeries[] = supported.map((series) => ({
    key: series.key,
    label: series.label,
    color: PLATFORM_COLORS[series.platform],
    points: series.points,
  }));
  const hasData = chartSeries.some((series) => series.points.some((point) => point.value !== null));
  const unsupported = (data?.series ?? []).filter((series) => !series.supported);
  const first = supported[0];
  const definitions = supported.map((series) => `${series.label}: ${series.definition ?? ""} (${series.source_metric ?? "n/a"})`).join(" ");
  return (
    <ChartCard
      title={title}
      metricName={first ? supported.map((s) => `${s.label}: ${s.metric_label}`).join(" · ") : metric}
      rangeLabel={`${formatDate(`${filters.start}T00:00:00Z`)} – ${formatDate(`${filters.end}T00:00:00Z`)}`}
      unit={first?.unit ?? "count"}
      definition={definitions || undefined}
      loading={loading}
      error={error}
      empty={!loading && !hasData}
      emptyMessage={
        unsupported.length > 0 && supported.length === 0
          ? unsupported.map((series) => `${series.label}: ${series.definition ?? "not reported by this platform"}`).join(" ")
          : "No daily values have been collected for this range yet. Data appears after the next synchronization."
      }
      hasPreviousData={hasData}
    >
      <LineChart series={chartSeries} unit={first?.unit ?? "count"} ariaLabel={`${title}, ${supported.map((s) => s.label).join(" and ")}, daily values`} />
      {unsupported.length > 0 && (
        <p className="mt-2 text-xs text-slate-500">
          {unsupported.map((series) => `${series.label}: ${series.definition ?? "not reported by this platform"}`).join(" ")}
        </p>
      )}
    </ChartCard>
  );
}

function PlatformComparisonSection() {
  const { workspaceId, filters, dataVersion } = useAnalytics();
  const params = new URLSearchParams({ start: filters.start, end: filters.end });
  if (filters.brandId) params.set("brand_id", filters.brandId);
  const path = workspaceId && !filters.platform && !filters.accountId ? `/workspaces/${workspaceId}/analytics/platforms/compare?${params}` : null;
  const { data, loading, error } = useAnalyticsData<PlatformComparison>(path, [dataVersion]);
  if (!path) return null;
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5" aria-label="Platform comparison">
      <h2 className="font-semibold">Platform comparison</h2>
      {error && (
        <p role="alert" className="mt-2 text-sm text-red-800">
          {error}
        </p>
      )}
      {!data && loading && <p className="mt-2 text-sm text-slate-500">Loading comparison…</p>}
      {data && (
        <>
          <p className="mt-1 text-sm text-slate-600">{data.note}</p>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[560px] text-left text-sm">
              <thead className="text-xs text-slate-500">
                <tr>
                  <th className="py-2 pr-3">Post metric (per post average)</th>
                  {data.platforms.map((platform) => (
                    <th key={platform.key} className="py-2 pr-3">
                      {platform.label}
                    </th>
                  ))}
                  <th className="py-2 pr-3">Comparable</th>
                </tr>
              </thead>
              <tbody>
                {data.post_metrics.map((metric) => (
                  <tr key={metric.key} className="border-t border-slate-100 align-top">
                    <td className="py-2 pr-3">
                      <p className="font-medium text-slate-800">{metric.label}</p>
                      {metric.note && <p className="text-xs text-amber-800">{metric.note}</p>}
                    </td>
                    {metric.platforms.map((entry) => (
                      <td key={entry.platform} className="py-2 pr-3">
                        {entry.average_per_post === null ? (
                          <span className="text-xs text-slate-500">Not available</span>
                        ) : (
                          <span style={{ fontVariantNumeric: "tabular-nums" }}>{formatNumber(entry.average_per_post)}</span>
                        )}
                        <p className="text-xs text-slate-500">
                          {entry.posts_with_data}/{entry.posts_total} posts · {entry.source_metric ?? "not reported"}
                        </p>
                        {entry.definition && (
                          <details className="text-xs text-slate-600">
                            <summary className="cursor-pointer text-indigo-700">Definition</summary>
                            <p className="mt-1 max-w-xs">{entry.definition}</p>
                          </details>
                        )}
                      </td>
                    ))}
                    <td className="py-2 pr-3 text-xs">{metric.comparable ? "Yes" : "No"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            {data.engagement_rates.map((rate) => (
              <div key={rate.platform} className="rounded-lg border border-slate-100 p-3 text-sm">
                <p className="flex items-center gap-2 font-medium">
                  <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: PLATFORM_COLORS[rate.platform] }} />
                  {rate.platform_label} average engagement rate (calculated)
                </p>
                <p className="mt-1 text-2xl font-semibold">{formatNumber(rate.average_engagement_rate, "percent")}</p>
                <p className="text-xs text-slate-500">
                  {rate.posts_with_rate}/{rate.posts_total} posts with reach · engagements = {rate.engagement_definition}; reach = {rate.reach_definition}
                </p>
              </div>
            ))}
          </div>
        </>
      )}
    </section>
  );
}

export default function AnalyticsOverviewPage() {
  const { workspaceId, query, dataVersion } = useAnalytics();
  const path = workspaceId ? `/workspaces/${workspaceId}/analytics/overview?${query()}` : null;
  const { data, loading, error } = useAnalyticsData<Overview>(path, [dataVersion]);

  return (
    <>
      {error && (
        <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">
          {error}
        </p>
      )}
      {!data && loading && <p className="text-sm text-slate-500">Loading overview…</p>}
      {data && (
        <div className={loading ? "space-y-6 opacity-60 transition-opacity" : "space-y-6"}>
          {data.accounts.length === 0 ? (
            <p className="rounded-2xl border border-slate-200 bg-white p-5 text-sm text-slate-600">No connected accounts match these filters.</p>
          ) : (
            <>
              <section aria-label="Key metrics" className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                {data.metrics.map((metric) => (
                  <MetricCard key={metric.key} metric={metric} />
                ))}
              </section>
              <section className="grid gap-4 md:grid-cols-3" aria-label="Posts and audience">
                <StatTile
                  label="Published posts in period"
                  value={data.published_posts.total}
                  delta={data.published_posts.change_percent}
                  note={`${data.published_posts.from_autowok} published through Autowok · ${Object.entries(data.published_posts.by_platform)
                    .map(([platform, count]) => `${platform === "instagram" ? "Instagram" : "Facebook"} ${count}`)
                    .join(", ")}`}
                />
                {data.follower_growth.map((growth) => (
                  <StatTile
                    key={growth.social_account_id}
                    label={`Audience growth · ${growth.account_name}`}
                    value={growth.change}
                    note={growth.note ?? `Calculated from ${growth.snapshots} follower snapshots. Latest: ${formatNumber(growth.latest)} followers.`}
                  />
                ))}
              </section>
              <section className="grid gap-4 lg:grid-cols-2" aria-label="Trends">
                {CHARTS.map((chart) => (
                  <TimeseriesChart key={chart.metric} metric={chart.metric} title={chart.title} />
                ))}
              </section>
              <PlatformComparisonSection />
              <section className="rounded-2xl border border-slate-200 bg-white p-5" aria-label="Top-performing posts">
                <h2 className="font-semibold">Top-performing posts</h2>
                <p className="mt-1 text-xs text-slate-500">Ranked by engagements using each platform&apos;s own definition.</p>
                <div className="mt-3">
                  <PostTable posts={data.top_posts} compact />
                </div>
              </section>
            </>
          )}
          <footer className="text-xs text-slate-500">
            {data.notes.map((note) => (
              <p key={note}>{note}</p>
            ))}
            <p>
              Newest data collected {formatDateTime(data.freshness.newest_collected_at)}. {data.filters.timezone_note}
            </p>
          </footer>
        </div>
      )}
    </>
  );
}
