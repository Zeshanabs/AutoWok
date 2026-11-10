import type { Publication } from "@/lib/media-types";

export type ScheduleStatus = "scheduled" | "queued" | "processing" | "published" | "failed" | "cancelled";
export type CalendarView = "month" | "week" | "day" | "list";

export type SchedulingHistoryEntry = {
  id: string;
  action: string;
  previous_scheduled_at: string | null;
  new_scheduled_at: string | null;
  performed_by: string | null;
  performed_by_name: string | null;
  details: Record<string, unknown>;
  created_at: string;
};

export type ScheduledPost = {
  id: string;
  workspace_id: string;
  project_id: string;
  draft_id: string;
  social_account_id: string;
  brand_id: string | null;
  platform: string;
  scheduled_at: string;
  scheduled_local: string;
  timezone: string;
  utc_offset: string;
  status: ScheduleStatus;
  stored_status: ScheduleStatus;
  revision: number;
  content_version_number: number;
  current_content_version: number | null;
  content_changed: boolean;
  approval_status: string | null;
  publication_id: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
  queued_at: string | null;
  cancelled_at: string | null;
  published_at: string | null;
  title: string | null;
  caption_preview: string | null;
  brand_name: string | null;
  account_name: string | null;
  account_platform: string | null;
  account_status: string | null;
  permalink: string | null;
  can_edit: boolean;
  can_cancel: boolean;
  can_retry: boolean;
  publication: Publication | null;
  history: SchedulingHistoryEntry[];
};

export type CalendarItem = {
  kind: "scheduled" | "published";
  id: string;
  scheduled_post_id: string | null;
  publication_id: string | null;
  project_id: string;
  draft_id: string | null;
  title: string | null;
  caption_preview: string | null;
  brand_id: string | null;
  brand_name: string | null;
  platform: string;
  social_account_id: string | null;
  account_name: string | null;
  at: string;
  local_time: string;
  local_date: string;
  timezone: string;
  status: ScheduleStatus;
  approval_status: string | null;
  content_changed: boolean;
  last_error: string | null;
  permalink: string | null;
  can_edit: boolean;
  can_cancel: boolean;
};

export type UnscheduledItem = {
  project_id: string;
  draft_id: string;
  title: string | null;
  caption_preview: string | null;
  platform: string;
  brand_id: string | null;
  brand_name: string | null;
};

export type CalendarResponse = {
  view: CalendarView;
  timezone: string;
  anchor_date: string;
  range_start: string;
  range_end: string;
  days: string[];
  items: CalendarItem[];
  unscheduled: UnscheduledItem[];
};

export type QueueStatus = {
  counts: Record<string, number>;
  schedule_counts: Record<string, number>;
  next_scheduled_at: string | null;
  active_jobs: Publication[];
  retrying_jobs: Publication[];
  attention_jobs: Publication[];
  upcoming: ScheduledPost[];
};

export type Preferences = {
  timezone: string;
  timezone_is_default: boolean;
  default_timezone: string;
};

export const HISTORY_LABELS: Record<string, string> = {
  created: "Scheduled",
  rescheduled: "Rescheduled",
  updated: "Updated",
  cancelled: "Cancelled",
  queued: "Sent to publishing queue",
  published: "Published",
  failed: "Publishing failed",
  retry_scheduled: "Automatic retry scheduled",
  retried: "Retry requested",
  validation_failed: "Blocked at publishing time",
  missed: "Missed publishing window",
};
