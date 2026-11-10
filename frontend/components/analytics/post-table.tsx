"use client";

/* eslint-disable @next/next/no-img-element -- thumbnails are external Meta CDN URLs */
import Link from "next/link";

import { AvailabilityBadge } from "@/components/analytics/metric-card";
import { formatDate, formatDateTime, formatNumber, isCalculated } from "@/lib/analytics-format";
import { PLATFORM_COLORS, POST_METRIC_COLUMNS, type AnalyticsPost } from "@/lib/analytics-types";

type Props = {
  posts: AnalyticsPost[];
  selectable?: boolean;
  selected?: string[];
  onToggle?: (postId: string) => void;
  onOpen?: (post: AnalyticsPost) => void;
  compact?: boolean;
};

export function MetricCell({ post, metric }: { post: AnalyticsPost; metric: string }) {
  const value = post.metrics[metric];
  const note = post.metric_availability[metric];
  if (value === null || value === undefined) return <AvailabilityBadge reason={note} />;
  return (
    <span className="inline-flex items-center gap-1" style={{ fontVariantNumeric: "tabular-nums" }}>
      {formatNumber(value)}
      {isCalculated(note) && (
        <abbr title={`Calculated by Autowok: ${note}`} className="text-[10px] text-indigo-700 no-underline">
          calc
        </abbr>
      )}
    </span>
  );
}

export function PostThumbnail({ post, className = "h-12 w-12" }: { post: AnalyticsPost; className?: string }) {
  if (!post.thumbnail_url) {
    return (
      <div className={`${className} flex items-center justify-center rounded-lg bg-slate-100 text-[10px] text-slate-500`} aria-hidden>
        {post.content_format_label ?? "Post"}
      </div>
    );
  }
  return <img src={post.thumbnail_url} alt={post.caption_preview ? `Thumbnail: ${post.caption_preview}` : "Post thumbnail"} className={`${className} rounded-lg bg-slate-100 object-cover`} loading="lazy" referrerPolicy="no-referrer" />;
}

export function PostTable({ posts, selectable = false, selected = [], onToggle, onOpen, compact = false }: Props) {
  const columns = compact ? POST_METRIC_COLUMNS.filter((column) => ["reach", "views", "engagements"].includes(column.key)) : POST_METRIC_COLUMNS;
  if (posts.length === 0) {
    return <p className="rounded-lg bg-slate-50 p-3 text-sm text-slate-600">No posts with analytics in this range.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-left text-sm">
        <thead className="text-xs text-slate-500">
          <tr>
            {selectable && <th className="py-2 pr-2">Compare</th>}
            <th className="py-2 pr-3">Post</th>
            <th className="py-2 pr-3">Published</th>
            {columns.map((column) => (
              <th key={column.key} className="py-2 pr-3">
                {column.label}
              </th>
            ))}
            <th className="py-2 pr-3">Engagement rate</th>
            <th className="py-2 pr-3">Last sync</th>
          </tr>
        </thead>
        <tbody>
          {posts.map((post) => (
            <tr key={post.id} className="border-t border-slate-100 align-top">
              {selectable && (
                <td className="py-2 pr-2">
                  <input
                    type="checkbox"
                    aria-label={`Select ${post.caption_preview ?? post.external_post_id} for comparison`}
                    checked={selected.includes(post.id)}
                    onChange={() => onToggle?.(post.id)}
                  />
                </td>
              )}
              <td className="py-2 pr-3">
                <div className="flex gap-3">
                  <PostThumbnail post={post} />
                  <div className="min-w-0">
                    <p className="flex items-center gap-2 text-xs text-slate-500">
                      <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: PLATFORM_COLORS[post.platform] }} />
                      {post.platform_label} · {post.account_name ?? "Account"} · {post.content_format_label ?? "Post"}
                    </p>
                    <button type="button" onClick={() => onOpen?.(post)} className="mt-0.5 block max-w-xs truncate text-left font-medium text-slate-900 hover:text-indigo-700">
                      {post.caption_preview ?? `Post ${post.external_post_id}`}
                    </button>
                    <p className="text-xs text-slate-500">
                      {post.project_id ? (
                        <Link href={`/dashboard/content/${post.project_id}`} className="text-indigo-700">
                          {post.project_title ?? "Autowok content"}
                        </Link>
                      ) : (
                        <span>Published outside Autowok</span>
                      )}
                      {post.permalink && (
                        <>
                          {" · "}
                          <a href={post.permalink} target="_blank" rel="noreferrer" className="text-indigo-700">
                            View on {post.platform === "instagram" ? "Instagram" : "Facebook"}
                          </a>
                        </>
                      )}
                    </p>
                  </div>
                </div>
              </td>
              <td className="py-2 pr-3 whitespace-nowrap text-slate-700">{formatDate(post.published_at)}</td>
              {columns.map((column) => (
                <td key={column.key} className="py-2 pr-3">
                  <MetricCell post={post} metric={column.key} />
                </td>
              ))}
              <td className="py-2 pr-3" title={post.engagement_rate_note ?? `Calculated: engagements / reach x 100 (${post.engagement_definition})`}>
                {post.engagement_rate === null ? <AvailabilityBadge reason="not_calculated" /> : `${formatNumber(post.engagement_rate, "percent")}`}
              </td>
              <td className="py-2 pr-3 whitespace-nowrap text-xs text-slate-500">{formatDateTime(post.collected_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
