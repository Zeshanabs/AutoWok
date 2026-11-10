"use client";

import { useAnalytics, useAnalyticsData } from "@/components/analytics/analytics-provider";
import { PlatformValue } from "@/components/analytics/metric-card";
import { API_BASE_URL } from "@/lib/api";
import { formatDate, formatDateTime, formatNumber } from "@/lib/analytics-format";
import type { Report } from "@/lib/analytics-types";

export default function AnalyticsReportsPage() {
  const { workspaceId, query, dataVersion } = useAnalytics();
  const path = workspaceId ? `/workspaces/${workspaceId}/analytics/reports?${query()}` : null;
  const { data, loading, error } = useAnalyticsData<Report>(path, [dataVersion]);
  const exportUrl = (format: "csv" | "pdf") => `${API_BASE_URL}/api/v1/workspaces/${workspaceId}/analytics/reports/export?${query({ format })}`;

  return (
    <>
      <section className="rounded-2xl border border-slate-200 bg-white p-5" aria-label="Export report">
        <h2 className="font-semibold">Export report</h2>
        <p className="mt-1 text-sm text-slate-600">
          The report uses the filters above (brand, platform, account and date range) and includes the reporting period, selected accounts, key metrics with their
          definitions, post performance, data collection timestamps and explanations for missing data.
        </p>
        <div className="mt-3 flex flex-wrap gap-3 text-sm">
          <a href={workspaceId ? exportUrl("csv") : "#"} download className="rounded-xl bg-slate-900 px-4 py-2 font-medium text-white" aria-disabled={!workspaceId}>
            Download CSV
          </a>
          <a href={workspaceId ? exportUrl("pdf") : "#"} download className="rounded-xl border border-slate-300 bg-white px-4 py-2 font-medium" aria-disabled={!workspaceId}>
            Download PDF
          </a>
        </div>
      </section>
      {error && (
        <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">
          {error}
        </p>
      )}
      {!data && loading && <p className="text-sm text-slate-500">Preparing report preview…</p>}
      {data && (
        <section className={`rounded-2xl border border-slate-200 bg-white p-5 ${loading ? "opacity-60" : ""}`} aria-label="Report preview">
          <h2 className="font-semibold">{data.title} · preview</h2>
          <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <dt className="text-xs text-slate-500">Reporting period</dt>
              <dd>
                {formatDate(`${data.period.start}T00:00:00Z`)} – {formatDate(`${data.period.end}T00:00:00Z`)} ({data.period.days} days)
              </dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">Brand</dt>
              <dd>{data.brand.name ?? "All brands"}</dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">Accounts</dt>
              <dd>{data.accounts.length ? data.accounts.map((account) => `${account.display_name} (${account.platform_label})`).join(", ") : "None match the filters"}</dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">Published posts</dt>
              <dd>
                {data.published_posts.total} ({data.published_posts.from_autowok} through Autowok)
              </dd>
            </div>
          </dl>
          <h3 className="mt-5 text-sm font-semibold">Key metrics</h3>
          <div className="mt-2 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {data.key_metrics.map((metric) => (
              <div key={metric.key} className="rounded-lg border border-slate-100 p-3">
                <p className="text-sm font-medium">{metric.label}</p>
                {metric.platforms.map((entry) => (
                  <PlatformValue key={entry.platform} entry={entry} />
                ))}
              </div>
            ))}
          </div>
          <h3 className="mt-5 text-sm font-semibold">Missing data</h3>
          {data.missing_data.length === 0 ? (
            <p className="mt-1 text-sm text-slate-600">All requested metrics were available.</p>
          ) : (
            <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-slate-700">
              {data.missing_data.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          )}
          <h3 className="mt-5 text-sm font-semibold">Posts included</h3>
          <p className="mt-1 text-sm text-slate-600">
            {data.posts.length} posts, sorted by engagements. Top post: {data.posts[0] ? `${data.posts[0].caption_preview ?? data.posts[0].external_post_id} (${formatNumber(data.posts[0].metrics.engagements)} engagements)` : "none"}.
          </p>
          <p className="mt-4 text-xs text-slate-500">
            {data.collection.note} Newest collection: {formatDateTime(data.collection.newest_collected_at)}. Generated {formatDateTime(data.generated_at)}. {data.definitions.length} metric definitions are included in the export.
          </p>
        </section>
      )}
    </>
  );
}
