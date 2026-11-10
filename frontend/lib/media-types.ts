import { API_BASE_URL } from "@/lib/api";

export type MediaAsset = {
  id: string;
  workspace_id: string;
  brand_id: string | null;
  original_filename: string;
  title: string | null;
  media_type: "image" | "video";
  mime_type: string;
  file_extension: string;
  file_size: number;
  width: number | null;
  height: number | null;
  duration_seconds: number | null;
  checksum: string;
  has_thumbnail: boolean;
  metadata_stripped: boolean;
  storage_provider: string;
  processing_status: string;
  uploaded_by: string;
  archived: boolean;
  created_at: string;
  updated_at: string;
  content_url: string;
  download_url: string;
  thumbnail_url: string | null;
  duplicate: boolean;
};

export type PreviewMediaItem = {
  id: string;
  media_type: "image" | "video";
  mime_type: string;
  title: string;
  width: number | null;
  height: number | null;
  duration_seconds: number | null;
  content_url: string;
  thumbnail_url: string | null;
};

export type DraftPreview = {
  platform: string;
  preview_type: string | null;
  approximate: boolean;
  disclaimer: string;
  media_count: number;
  caption: string | null;
  caption_length: number;
  account_name: string | null;
  account_username: string | null;
  account_image_url: string | null;
  media: PreviewMediaItem[];
  errors: string[];
  warnings: string[];
};

export type Eligibility = {
  eligible: boolean;
  platform: string;
  publish_format: string | null;
  approval_status: string | null;
  content_version_number: number | null;
  caption: string;
  media_count: number;
  errors: string[];
  warnings: string[];
  social_account_id: string;
  account_name: string | null;
  account_platform: string | null;
};

export type PublishingAttempt = {
  id: string;
  attempt_number: number;
  status: string;
  stage: string | null;
  error_category: string | null;
  error_code: string | null;
  error_message: string | null;
  retryable: boolean;
  started_at: string;
  finished_at: string | null;
};

export type Publication = {
  id: string;
  workspace_id: string;
  project_id: string;
  draft_id: string | null;
  social_account_id: string | null;
  platform: string;
  source: "manual" | "schedule";
  status: "pending" | "processing" | "publishing" | "published" | "failed" | "cancelled";
  stage: string | null;
  publish_format: string | null;
  caption: string | null;
  media_asset_ids: string[];
  content_version_number: number | null;
  external_post_id: string | null;
  permalink: string | null;
  attempt_count: number;
  max_attempts: number;
  next_attempt_at: string | null;
  error_category: string | null;
  error_code: string | null;
  error_message: string | null;
  requires_user_action: boolean;
  outcome_uncertain: boolean;
  can_retry: boolean;
  can_cancel: boolean;
  requested_by: string | null;
  confirmed_at: string | null;
  started_at: string | null;
  published_at: string | null;
  completed_at: string | null;
  cancelled_at: string | null;
  created_at: string;
  updated_at: string;
  project_title: string | null;
  account_name: string | null;
  attempts: PublishingAttempt[];
};

export const ACTIVE_PUBLICATION_STATUSES = ["pending", "processing", "publishing"];

/** Absolute URL for an API-relative media path (cookies are sent: same site). */
export function mediaUrl(path: string | null | undefined): string | undefined {
  return path ? `${API_BASE_URL}${path}` : undefined;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDuration(seconds: number | null): string | null {
  if (seconds == null) return null;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  return `${minutes}:${rest.toString().padStart(2, "0")}`;
}

export const ACCEPTED_MEDIA = ".jpg,.jpeg,.png,.gif,.mp4,.m4v,.mov";
