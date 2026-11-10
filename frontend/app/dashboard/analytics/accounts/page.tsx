"use client";

/* eslint-disable @next/next/no-img-element -- profile images are external Meta CDN URLs */
import { useAnalytics, useAnalyticsData } from "@/components/analytics/analytics-provider";
import { ChartCard, LineChart } from "@/components/analytics/charts";
import { availabilityText, formatChange, formatDate, formatDateTime, formatNumber } from "@/lib/analytics-format";
import { PLATFORM_COLORS, type AccountInsights } from "@/lib/analytics-types";

function AccountCard({ insights, rangeLabel }: { insights: AccountInsights; rangeLabel: string }) {
  const account = insights.account;
  const hasFollowerData = insights.follower_series.some((point) => point.value !== null);
  return (
    <article className="rounded-2xl border border-slate-200 bg-white p-5" aria-label={`${account.display_name} insights`}>
      <header className="flex flex-wrap items-center gap-3">
        {account.profile_image_url ? (
          <img src={account.profile_image_url} alt="" className="h-10 w-10 rounded-full bg-slate-100 object-cover" referrerPolicy="no-referrer" />
        ) : (
          <span aria-hidden className="inline-block h-10 w-10 rounded-full" style={{ background: PLATFORM_COLORS[account.platform] }} />
        )}
        <div>
          <h2 className="font-semibold">{account.display_name}</h2>
          <p className="text-xs text-slate-500">
            {account.platform_label}
            {account.username ? ` · @${account.username}` : ""} · {account.connection_status}
          </p>
        </div>
        <p className="ml-auto text-xs text-slate-500">
          {insights.sync.last_synced_at ? `Synced ${formatDateTime(insights.sync.last_synced_at)}` : "Never synchronized"}
          {!insights.sync.insights_available && <span className="block text-amber-800">Insights permission missing: only followers and post counts are collected.</span>}
        </p>
      </header>
      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[640px] text-left text-sm">
          <caption className="sr-only">Account metrics for {account.display_name}</caption>
          <thead className="text-xs text-slate-500">
            <tr>
              <th className="py-2 pr-3">Metric</th>
              <th className="py-2 pr-3">Current period</th>
              <th className="py-2 pr-3">Previous period</th>
              <th className="py-2 pr-3">Change</th>
              <th className="py-2 pr-3">Collected</th>
            </tr>
          </thead>
          <tbody>
            {insights.metrics.map((metric) => {
              const change = formatChange(metric.change_percent);
              return (
                <tr key={metric.key} className="border-t border-slate-100 align-top">
                  <td className="py-2 pr-3">
                    <p className="font-medium text-slate-800">{metric.label}</p>
                    <details className="text-xs text-slate-600">
                      <summary className="cursor-pointer text-indigo-700">{metric.source_metric ? `Definition (${metric.source_metric})` : "Definition"}</summary>
                      <p className="mt-1 max-w-md">{metric.definition}</p>
                      {metric.aggregation === "last" && <p className="mt-1 text-slate-500">Shows the latest snapshot in the period.</p>}
                    </details>
                  </td>
                  <td className="py-2 pr-3" style={{ fontVariantNumeric: "tabular-nums" }}>
                    {metric.value === null ? <span className="text-xs text-slate-500">{availabilityText(metric.reason ?? "unavailable")}</span> : formatNumber(metric.value, metric.unit)}
                  </td>
                  <td className="py-2 pr-3" style={{ fontVariantNumeric: "tabular-nums" }}>
                    {metric.previous_value === null ? <span className="text-xs text-slate-500">Not available</span> : formatNumber(metric.previous_value, metric.unit)}
                  </td>
                  <td className={`py-2 pr-3 text-xs ${change.direction === "up" ? "text-emerald-800" : change.direction === "down" ? "text-red-800" : "text-slate-500"}`}>{change.text}</td>
                  <td className="py-2 pr-3 text-xs text-slate-500">{metric.collected_at ? formatDateTime(metric.collected_at) : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="mt-4">
        <ChartCard
          title="Followers"
          metricName="followers_count snapshot per day"
          rangeLabel={rangeLabel}
          unit="count"
          loading={false}
          error={null}
          empty={!hasFollowerData}
          emptyMessage="No follower snapshots in this range yet."
        >
          <LineChart
            series={[{ key: account.id, label: account.display_name, color: PLATFORM_COLORS[account.platform], points: insights.follower_series }]}
            ariaLabel={`Followers per day for ${account.display_name}`}
          />
          <p className="mt-2 text-xs text-slate-500">
            Audience growth in period (calculated): {insights.follower_change === null ? "needs at least two snapshots" : formatNumber(insights.follower_change)}
          </p>
        </ChartCard>
      </div>
    </article>
  );
}

export default function AnalyticsAccountsPage() {
  const { workspaceId, filters, query, dataVersion } = useAnalytics();
  const path = workspaceId ? `/workspaces/${workspaceId}/analytics/accounts?${query()}` : null;
  const { data, loading, error } = useAnalyticsData<AccountInsights[]>(path, [dataVersion]);
  const rangeLabel = `${formatDate(`${filters.start}T00:00:00Z`)} – ${formatDate(`${filters.end}T00:00:00Z`)}`;
  return (
    <>
      {error && (
        <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">
          {error}
        </p>
      )}
      {!data && loading && <p className="text-sm text-slate-500">Loading accounts…</p>}
      {data && data.length === 0 && <p className="rounded-2xl border border-slate-200 bg-white p-5 text-sm text-slate-600">No connected accounts match these filters.</p>}
      <div className={loading ? "space-y-6 opacity-60 transition-opacity" : "space-y-6"}>
        {data?.map((insights) => (
          <AccountCard key={insights.account.id} insights={insights} rangeLabel={rangeLabel} />
        ))}
      </div>
    </>
  );
}
