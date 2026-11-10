"use client";

import { useState } from "react";

import { useAnalytics, useAnalyticsData } from "@/components/analytics/analytics-provider";
import { ChartCard, LineChart } from "@/components/analytics/charts";
import { AvailabilityBadge } from "@/components/analytics/metric-card";
import { MetricCell, PostTable, PostThumbnail } from "@/components/analytics/post-table";
import { ApiError, apiRequest } from "@/lib/api";
import { availabilityText, formatDate, formatDateTime, formatNumber } from "@/lib/analytics-format";
import { PLATFORM_COLORS, POST_METRIC_COLUMNS, type AnalyticsPost, type AnalyticsPostDetail, type Comparison, type PostList } from "@/lib/analytics-types";

const fieldClass = "rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm";
const FORMATS = [
  { value: "", label: "All content types" },
  { value: "text", label: "Facebook text" },
  { value: "photo", label: "Facebook photo" },
  { value: "multi_photo", label: "Facebook multi-photo" },
  { value: "video", label: "Video" },
  { value: "link", label: "Facebook link" },
  { value: "image", label: "Instagram image" },
  { value: "carousel", label: "Instagram carousel" },
  { value: "reel", label: "Instagram reel" },
];
const PAGE_SIZE = 25;

function PostDetail({ post, onClose }: { post: AnalyticsPost; onClose: () => void }) {
  const { workspaceId } = useAnalytics();
  const { data, loading, error } = useAnalyticsData<AnalyticsPostDetail>(workspaceId ? `/workspaces/${workspaceId}/analytics/posts/${post.id}` : null, []);
  const history = data?.history ?? [];
  const series = ["reach", "views", "engagements"].map((key, index) => ({
    key,
    label: POST_METRIC_COLUMNS.find((column) => column.key === key)?.label ?? key,
    color: `var(--series-${index + 1})`,
    points: history.map((entry) => ({ date: entry.snapshot_date, value: entry.metrics[key] ?? null })),
  }));
  return (
    <section className="rounded-2xl border border-indigo-200 bg-white p-5" aria-label="Post details">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex gap-3">
          <PostThumbnail post={post} className="h-20 w-20" />
          <div>
            <p className="text-xs text-slate-500">
              {post.platform_label} · {post.account_name} · {post.content_format_label} · {formatDate(post.published_at)}
            </p>
            <h2 className="mt-1 font-semibold">{post.caption_preview ?? `Post ${post.external_post_id}`}</h2>
            <p className="text-xs text-slate-500">
              Last synchronized {formatDateTime(post.collected_at)}
              {post.api_version ? ` · Graph API ${post.api_version}` : ""}
            </p>
          </div>
        </div>
        <button type="button" onClick={onClose} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm">
          Close
        </button>
      </div>
      {error && (
        <p role="alert" className="mt-3 text-sm text-red-800">
          {error}
        </p>
      )}
      <dl className="mt-4 grid gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {POST_METRIC_COLUMNS.map((column) => (
          <div key={column.key} className="rounded-lg border border-slate-100 p-3">
            <dt className="text-xs text-slate-500">{column.label}</dt>
            <dd className="mt-1 text-lg font-semibold">
              <MetricCell post={post} metric={column.key} />
            </dd>
            {data?.definitions.find((definition) => definition.key === column.key) && (
              <dd className="mt-1 text-[11px] text-slate-500">{data.definitions.find((definition) => definition.key === column.key)?.definition}</dd>
            )}
          </div>
        ))}
        <div className="rounded-lg border border-slate-100 p-3">
          <dt className="text-xs text-slate-500">Engagement rate (calculated)</dt>
          <dd className="mt-1 text-lg font-semibold">{post.engagement_rate === null ? <AvailabilityBadge reason="not_calculated" /> : formatNumber(post.engagement_rate, "percent")}</dd>
          <dd className="mt-1 text-[11px] text-slate-500">{post.engagement_rate_note ?? `engagements (${post.engagement_definition}) / ${post.reach_definition} x 100`}</dd>
        </div>
      </dl>
      {Object.keys(post.extra_metrics).length > 0 && (
        <p className="mt-3 text-xs text-slate-600">
          Additional Meta metrics:{" "}
          {Object.entries(post.extra_metrics)
            .map(([key, value]) => `${key.replaceAll("_", " ")} ${formatNumber(value, key.includes("watch_time") ? "milliseconds" : "count")}`)
            .join(" · ")}
        </p>
      )}
      <div className="mt-4">
        <ChartCard
          title="Performance history"
          metricName="Reach, views and engagements per collection day"
          rangeLabel={history.length ? `${formatDate(`${history[0].snapshot_date}T00:00:00Z`)} – ${formatDate(`${history[history.length - 1].snapshot_date}T00:00:00Z`)}` : "no history yet"}
          unit="count"
          loading={loading}
          error={null}
          empty={history.length < 2}
          emptyMessage="History builds up with each daily synchronization; at least two collection days are needed for a trend."
        >
          <LineChart series={series} ariaLabel="Post performance history" />
        </ChartCard>
      </div>
    </section>
  );
}

function ComparePanel({ ids, onClear }: { ids: string[]; onClear: () => void }) {
  const { workspaceId } = useAnalytics();
  const [data, setData] = useState<Comparison | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [requestedFor, setRequestedFor] = useState<string>("");
  const key = ids.join(",");
  if (workspaceId && ids.length >= 2 && requestedFor !== key) {
    setRequestedFor(key);
    apiRequest<Comparison>(`/workspaces/${workspaceId}/analytics/posts/compare`, { method: "POST", body: JSON.stringify({ post_ids: ids }) })
      .then((result) => {
        setData(result);
        setError(null);
      })
      .catch((compareError: unknown) => setError(compareError instanceof ApiError ? compareError.message : "The comparison could not be loaded."));
  }
  if (ids.length < 2) return null;
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5" aria-label="Post comparison">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold">Compare {ids.length} posts</h2>
        <button type="button" onClick={onClear} className="text-sm text-indigo-700">
          Clear selection
        </button>
      </div>
      {error && (
        <p role="alert" className="mt-2 text-sm text-red-800">
          {error}
        </p>
      )}
      {data && (
        <>
          {data.mixed_platforms && <p className="mt-1 text-xs text-amber-800">Posts from both platforms are selected: only metrics marked comparable measure the same thing.</p>}
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[560px] text-left text-sm">
              <thead className="text-xs text-slate-500">
                <tr>
                  <th className="py-2 pr-3">Metric</th>
                  {data.posts.map((post) => (
                    <th key={post.id} className="py-2 pr-3">
                      <span className="flex items-center gap-1 font-medium text-slate-700">
                        <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: PLATFORM_COLORS[post.platform] }} />
                        {(post.caption_preview ?? post.external_post_id).slice(0, 32)}
                      </span>
                      <span className="block font-normal">
                        {post.platform_label} · {formatDate(post.published_at)}
                      </span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.metrics.map((metric) => (
                  <tr key={metric.key} className="border-t border-slate-100 align-top">
                    <td className="py-2 pr-3">
                      <p className="font-medium text-slate-800">{metric.label}</p>
                      {!metric.comparable && <p className="text-xs text-amber-800">{metric.note ?? "Not comparable across platforms."}</p>}
                    </td>
                    {metric.values.map((value) => (
                      <td key={value.post_id} className="py-2 pr-3" style={{ fontVariantNumeric: "tabular-nums" }}>
                        {value.value === null ? <span className="text-xs text-slate-500">{availabilityText(value.availability ?? "unavailable")}</span> : formatNumber(value.value, metric.key === "engagement_rate" ? "percent" : "count")}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

export default function AnalyticsPostsPage() {
  const { workspaceId, query, dataVersion } = useAnalytics();
  const [contentFormat, setContentFormat] = useState("");
  const [source, setSource] = useState("");
  const [minEngagements, setMinEngagements] = useState("");
  const [maxEngagements, setMaxEngagements] = useState("");
  const [sort, setSort] = useState("published_at");
  const [order, setOrder] = useState("desc");
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<string[]>([]);
  const [open, setOpen] = useState<AnalyticsPost | null>(null);

  const path = workspaceId
    ? `/workspaces/${workspaceId}/analytics/posts?${query({
        content_format: contentFormat,
        source,
        min_engagements: minEngagements,
        max_engagements: maxEngagements,
        sort,
        order,
        offset: page * PAGE_SIZE,
        limit: PAGE_SIZE,
      })}`
    : null;
  const { data, loading, error } = useAnalyticsData<PostList>(path, [dataVersion]);
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  const toggle = (id: string) =>
    setSelected((current) => (current.includes(id) ? current.filter((item) => item !== id) : current.length >= 6 ? current : [...current, id]));

  return (
    <>
      <section className="rounded-2xl border border-slate-200 bg-white p-4">
        <form className="flex flex-wrap items-end gap-3" onSubmit={(event) => event.preventDefault()} aria-label="Post filters">
          <label className="text-xs text-slate-600">
            Content type
            <select aria-label="Filter by content type" className={`${fieldClass} mt-1 block`} value={contentFormat} onChange={(event) => (setContentFormat(event.target.value), setPage(0))}>
              {FORMATS.map((format) => (
                <option key={format.value} value={format.value}>
                  {format.label}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-slate-600">
            Source
            <select aria-label="Filter by source" className={`${fieldClass} mt-1 block`} value={source} onChange={(event) => (setSource(event.target.value), setPage(0))}>
              <option value="">All posts</option>
              <option value="autowok">Published through Autowok</option>
              <option value="external">Published outside Autowok</option>
            </select>
          </label>
          <label className="text-xs text-slate-600">
            Min engagements
            <input type="number" min={0} aria-label="Minimum engagements" className={`${fieldClass} mt-1 block w-28`} value={minEngagements} onChange={(event) => (setMinEngagements(event.target.value), setPage(0))} />
          </label>
          <label className="text-xs text-slate-600">
            Max engagements
            <input type="number" min={0} aria-label="Maximum engagements" className={`${fieldClass} mt-1 block w-28`} value={maxEngagements} onChange={(event) => (setMaxEngagements(event.target.value), setPage(0))} />
          </label>
          <label className="text-xs text-slate-600">
            Sort by
            <select aria-label="Sort posts" className={`${fieldClass} mt-1 block`} value={sort} onChange={(event) => setSort(event.target.value)}>
              <option value="published_at">Published date</option>
              {POST_METRIC_COLUMNS.map((column) => (
                <option key={column.key} value={column.key}>
                  {column.label}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-slate-600">
            Order
            <select aria-label="Sort order" className={`${fieldClass} mt-1 block`} value={order} onChange={(event) => setOrder(event.target.value)}>
              <option value="desc">Highest first</option>
              <option value="asc">Lowest first</option>
            </select>
          </label>
        </form>
      </section>
      {open && <PostDetail post={open} onClose={() => setOpen(null)} />}
      <ComparePanel ids={selected} onClear={() => setSelected([])} />
      <section className="rounded-2xl border border-slate-200 bg-white p-5" aria-label="Post performance">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-semibold">Post performance</h2>
          <p className="text-xs text-slate-500">
            {data ? `${data.total} posts` : ""} · select 2–6 posts to compare · &quot;calc&quot; marks values calculated by Autowok
          </p>
        </div>
        {error && (
          <p role="alert" className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-800">
            {error}
          </p>
        )}
        {!data && loading && <p className="mt-3 text-sm text-slate-500">Loading posts…</p>}
        {data && (
          <div className={loading ? "mt-3 opacity-60 transition-opacity" : "mt-3"}>
            <PostTable posts={data.items} selectable selected={selected} onToggle={toggle} onOpen={setOpen} />
            {pages > 1 && (
              <nav className="mt-3 flex items-center gap-3 text-sm" aria-label="Pagination">
                <button type="button" disabled={page === 0} onClick={() => setPage((value) => value - 1)} className="rounded-lg border border-slate-300 px-3 py-1 disabled:opacity-40">
                  Previous
                </button>
                <span>
                  Page {page + 1} of {pages}
                </span>
                <button type="button" disabled={page + 1 >= pages} onClick={() => setPage((value) => value + 1)} className="rounded-lg border border-slate-300 px-3 py-1 disabled:opacity-40">
                  Next
                </button>
              </nav>
            )}
          </div>
        )}
      </section>
    </>
  );
}
