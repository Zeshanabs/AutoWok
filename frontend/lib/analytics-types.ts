export type AnalyticsPlatform = "facebook_page" | "instagram";

export type AnalyticsFilterState = {
  start: string;
  end: string;
  preset: "7" | "28" | "90" | "custom";
  brandId: string;
  platform: "" | AnalyticsPlatform;
  accountId: string;
};

export type FiltersRead = {
  start: string;
  end: string;
  days: number;
  previous_start: string;
  previous_end: string;
  brand_id: string | null;
  platform: string | null;
  social_account_id: string | null;
  account_ids: string[];
  timezone_note: string;
};

export type Availability = "available" | "partial" | "unavailable" | "not_supported";

export type PlatformMetric = {
  platform: AnalyticsPlatform;
  platform_label: string;
  value: number | null;
  previous_value: number | null;
  change_percent: number | null;
  availability: Availability;
  reason: string | null;
  definition: string | null;
  source_metric: string | null;
  unit: string;
  aggregation: string | null;
  collected_at: string | null;
  accounts_with_data: number;
  accounts_total: number;
  days_with_data: number;
};

export type MetricSummary = {
  key: string;
  label: string;
  comparable: boolean;
  combined_value: number | null;
  combined_note: string | null;
  platforms: PlatformMetric[];
};

export type SyncStatus = {
  social_account_id: string;
  account_name: string;
  platform: AnalyticsPlatform;
  connection_status: string;
  last_synced_at: string | null;
  last_sync_status: string | null;
  last_error: string | null;
  last_error_category: string | null;
  next_attempt_at: string | null;
  active_job_id: string | null;
  insights_available: boolean;
  can_sync: boolean;
  missing_permissions: string[];
  notes: string[];
};

export type FollowerGrowth = {
  social_account_id: string;
  account_name: string;
  platform: AnalyticsPlatform;
  change: number | null;
  snapshots: number;
  latest: number | null;
  note: string | null;
};

export type PublishedCounts = {
  total: number;
  by_platform: Record<string, number>;
  from_autowok: number;
  previous_total: number;
  change_percent: number | null;
};

export type PostMetrics = Record<string, number | null>;

export type AnalyticsPost = {
  id: string;
  workspace_id: string;
  brand_id: string | null;
  social_account_id: string;
  account_name: string | null;
  platform: AnalyticsPlatform;
  platform_label: string;
  publication_id: string | null;
  project_id: string | null;
  project_title: string | null;
  draft_id: string | null;
  external_post_id: string;
  permalink: string | null;
  published_at: string | null;
  content_format: string | null;
  content_format_label: string | null;
  caption_preview: string | null;
  thumbnail_url: string | null;
  metrics: PostMetrics;
  extra_metrics: Record<string, number | null>;
  metric_availability: Record<string, string>;
  engagement_rate: number | null;
  engagement_rate_note: string | null;
  engagement_definition: string | null;
  reach_definition: string | null;
  source: "autowok" | "external";
  collected_at: string | null;
  api_version: string | null;
};

export type PostHistoryEntry = { snapshot_date: string; collected_at: string | null; metrics: PostMetrics };

export type MetricDefinition = {
  key: string;
  platform: string;
  platform_label?: string;
  level: string;
  label: string;
  source_kind?: string;
  source_name?: string;
  formula?: string;
  definition: string;
  unit: string;
  period?: string | null;
  applies_to?: string[];
  requirements?: string[];
  limitations?: string[];
  comparable?: boolean;
  aggregation?: string;
};

export type AnalyticsPostDetail = AnalyticsPost & { history: PostHistoryEntry[]; definitions: MetricDefinition[] };

export type PostList = { total: number; offset: number; limit: number; items: AnalyticsPost[] };

export type Overview = {
  filters: FiltersRead;
  accounts: SyncStatus[];
  metrics: MetricSummary[];
  follower_growth: FollowerGrowth[];
  published_posts: PublishedCounts;
  top_posts: AnalyticsPost[];
  freshness: { newest_collected_at: string | null; oldest_collected_at: string | null };
  notes: string[];
};

export type SeriesPoint = { date: string; value: number | null };

export type Series = {
  key: string;
  label: string;
  platform: AnalyticsPlatform;
  metric_label: string;
  definition: string | null;
  source_metric: string | null;
  unit: string;
  supported: boolean;
  has_data: boolean;
  points: SeriesPoint[];
};

export type Timeseries = { metric: string; group_by: string; start: string; end: string; series: Series[] };

export type AccountMetric = {
  key: string;
  label: string;
  value: number | null;
  previous_value: number | null;
  change_percent: number | null;
  availability: Availability;
  reason: string | null;
  definition: string | null;
  source_metric: string | null;
  unit: string;
  aggregation: string | null;
  collected_at: string | null;
  accounts_with_data: number;
  accounts_total: number;
  days_with_data: number;
};

export type AccountInsights = {
  account: {
    id: string;
    display_name: string;
    username: string | null;
    platform: AnalyticsPlatform;
    platform_label: string;
    brand_id: string | null;
    profile_image_url: string | null;
    connection_status: string;
  };
  metrics: AccountMetric[];
  follower_series: SeriesPoint[];
  follower_change: number | null;
  sync: SyncStatus;
};

export type ComparisonValue = { post_id: string; value: number | null; availability: string | null };

export type Comparison = {
  posts: AnalyticsPost[];
  metrics: { key: string; label: string; comparable: boolean; note: string | null; values: ComparisonValue[]; definitions: Record<string, string | null> }[];
  mixed_platforms: boolean;
};

export type PlatformComparison = {
  filters: FiltersRead;
  platforms: { key: AnalyticsPlatform; label: string; accounts: number }[];
  account_metrics: MetricSummary[];
  post_metrics: {
    key: string;
    label: string;
    comparable: boolean;
    note: string | null;
    platforms: {
      platform: AnalyticsPlatform;
      platform_label: string;
      total: number | null;
      average_per_post: number | null;
      posts_with_data: number;
      posts_total: number;
      definition: string | null;
      source_metric: string | null;
      availability: Availability;
    }[];
  }[];
  engagement_rates: {
    platform: AnalyticsPlatform;
    platform_label: string;
    average_engagement_rate: number | null;
    posts_with_rate: number;
    posts_total: number;
    engagement_definition: string;
    reach_definition: string;
  }[];
  meaningful: boolean;
  note: string;
};

export type FormatPerformance = {
  platform: AnalyticsPlatform;
  platform_label: string;
  content_format: string;
  content_format_label: string;
  posts: number;
  average_engagements: number | null;
  average_reach: number | null;
  average_engagement_rate: number | null;
  enough_data: boolean;
  note: string | null;
};

export type ContentPerformance = {
  filters: FiltersRead;
  post_count: number;
  ranking_metric: "engagement_rate" | "engagements";
  ranking_method: string;
  top_posts: AnalyticsPost[];
  bottom_posts: AnalyticsPost[];
  formats: FormatPerformance[];
  best_format: FormatPerformance | null;
  best_format_note: string;
  weekly_trend: { week_start: string; posts: number; engagements: number | null; reach: number | null }[];
  period_change: {
    current_engagements: number | null;
    previous_engagements: number | null;
    change_percent: number | null;
    current_posts: number;
    previous_posts: number;
  };
  consistency: { posts: number; active_days: number; posts_per_week: number; longest_gap_days: number | null };
  notes: string[];
};

export type AISummary = { available: boolean; label: string; reason: string | null; text: string | null; model: string | null };

export type SyncJob = {
  id: string;
  workspace_id: string;
  social_account_id: string;
  account_name: string | null;
  platform: AnalyticsPlatform;
  status: "pending" | "running" | "succeeded" | "partial" | "failed" | "cancelled";
  trigger: "manual" | "scheduled";
  requested_by: string | null;
  range_start: string | null;
  range_end: string | null;
  attempt_count: number;
  max_attempts: number;
  next_attempt_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  error_category: string | null;
  error_code: string | null;
  last_error: string | null;
  records_processed: number;
  details: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type SyncRequestResult = { jobs: SyncJob[]; skipped: { social_account_id: string; account_name: string; reason: string }[] };
export type SyncStatusList = { accounts: SyncStatus[]; active_jobs: number; sync_interval_hours: number };

export type Report = {
  title: string;
  generated_at: string;
  period: { start: string; end: string; days: number };
  previous_period: { start: string; end: string };
  brand: { id: string | null; name: string | null };
  platform_filter: string | null;
  accounts: { id: string; display_name: string; username: string | null; platform: AnalyticsPlatform; platform_label: string; connection_status: string }[];
  key_metrics: MetricSummary[];
  follower_growth: FollowerGrowth[];
  published_posts: PublishedCounts;
  account_insights: AccountInsights[];
  posts: AnalyticsPost[];
  definitions: MetricDefinition[];
  missing_data: string[];
  collection: { newest_collected_at: string | null; note: string };
};

export const PLATFORM_LABELS: Record<AnalyticsPlatform, string> = { facebook_page: "Facebook Page", instagram: "Instagram" };

/** Colour follows the entity (platform), never its position in a list. */
export const PLATFORM_COLORS: Record<AnalyticsPlatform, string> = { facebook_page: "var(--series-1)", instagram: "var(--series-2)" };

export const POST_METRIC_COLUMNS: { key: string; label: string }[] = [
  { key: "reach", label: "Reach / unique viewers" },
  { key: "views", label: "Views" },
  { key: "engagements", label: "Engagements" },
  { key: "likes", label: "Likes" },
  { key: "comments", label: "Comments" },
  { key: "shares", label: "Shares" },
  { key: "saves", label: "Saves" },
  { key: "clicks", label: "Clicks" },
  { key: "video_views", label: "Video views" },
];
