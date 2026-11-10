import { addDays } from "@/lib/timezones";
import type { AnalyticsFilterState } from "@/lib/analytics-types";

export const UNAVAILABLE = "Not available";

/** Today's date in UTC (YYYY-MM-DD); analytics dates are compared in UTC. */
export function todayUtc(): string {
  return new Date().toISOString().slice(0, 10);
}

export function presetRange(days: 7 | 28 | 90, end: string = todayUtc()): { start: string; end: string } {
  return { start: addDays(end, -(days - 1)), end };
}

export function defaultFilters(): AnalyticsFilterState {
  return { ...presetRange(28), preset: "28", brandId: "", platform: "", accountId: "" };
}

/** Compact number formatting: 1,284 / 12.9K / 4.2M. Null is never shown as zero. */
export function formatNumber(value: number | null | undefined, unit: string = "count"): string {
  if (value === null || value === undefined || Number.isNaN(value)) return UNAVAILABLE;
  if (unit === "percent") return `${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}%`;
  if (unit === "milliseconds") {
    const seconds = value / 1000;
    return seconds >= 60 ? `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s` : `${seconds.toLocaleString(undefined, { maximumFractionDigits: 1 })}s`;
  }
  const abs = Math.abs(value);
  if (abs >= 1_000_000) return `${(value / 1_000_000).toLocaleString(undefined, { maximumFractionDigits: 1 })}M`;
  if (abs >= 10_000) return `${(value / 1_000).toLocaleString(undefined, { maximumFractionDigits: 1 })}K`;
  return value.toLocaleString(undefined, { maximumFractionDigits: Number.isInteger(value) ? 0 : 2 });
}

export function formatChange(change: number | null | undefined): { text: string; direction: "up" | "down" | "flat" | "none" } {
  if (change === null || change === undefined) return { text: "No comparison", direction: "none" };
  if (change === 0) return { text: "0%", direction: "flat" };
  const sign = change > 0 ? "+" : "";
  return { text: `${sign}${change.toLocaleString(undefined, { maximumFractionDigits: 1 })}%`, direction: change > 0 ? "up" : "down" };
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "never";
  return new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "UTC", timeZoneName: "short" }).format(new Date(iso));
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return UNAVAILABLE;
  return new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }).format(new Date(iso));
}

export function formatDay(day: string): string {
  return new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", timeZone: "UTC" }).format(new Date(`${day}T00:00:00Z`));
}

/** Human explanation for an availability note stored by the collector. */
export function availabilityText(reason: string | null | undefined): string {
  if (!reason) return UNAVAILABLE;
  if (reason.startsWith("missing_permission:")) {
    return `Needs the ${reason.split(":")[1]} permission (reconnect Meta)`;
  }
  const table: Record<string, string> = {
    not_supported_on_platform: "Not reported by this platform",
    not_supported: "Not reported by this platform",
    not_applicable: "Does not apply to this post type",
    not_returned: "Meta did not return this metric",
    unsupported_metric: "Not supported by Meta for this account",
    insufficient_data: "Below Meta's minimum audience for insights",
    hidden_or_not_returned: "Hidden by the account owner or not returned",
    object_unavailable: "The post could not be read from Meta",
    calculated: "Calculated by Autowok",
    calculated_without_clicks: "Calculated without clicks (clicks unavailable)",
    calculated_from_likes_comments_saves_shares: "Calculated from likes, comments, saves and shares",
    from_reactions_summary: "From the reactions summary (insights unavailable)",
    from_likes_summary: "From the likes summary (insights unavailable)",
    not_calculated: "Not calculated",
  };
  return table[reason] ?? reason.replaceAll("_", " ");
}

export function isCalculated(reason: string | null | undefined): boolean {
  return Boolean(reason && (reason.startsWith("calculated") || reason.startsWith("from_")));
}

export function filterQuery(filters: AnalyticsFilterState, extra: Record<string, string | number | undefined | null> = {}): string {
  const params = new URLSearchParams();
  params.set("start", filters.start);
  params.set("end", filters.end);
  if (filters.brandId) params.set("brand_id", filters.brandId);
  if (filters.platform) params.set("platform", filters.platform);
  if (filters.accountId) params.set("social_account_id", filters.accountId);
  for (const [key, value] of Object.entries(extra)) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  return params.toString();
}

/** Nice axis ticks: 0 to a rounded maximum in four steps. */
export function niceTicks(max: number, count: number = 4): number[] {
  if (!Number.isFinite(max) || max <= 0) return [0, 1];
  const rough = max / count;
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  const residual = rough / magnitude;
  const step = (residual > 5 ? 10 : residual > 2.5 ? 5 : residual > 1.5 ? 2 : 1) * magnitude;
  const ticks: number[] = [];
  for (let value = 0; value <= max + step * 0.999; value += step) ticks.push(Number(value.toFixed(10)));
  return ticks;
}
