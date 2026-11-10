export type ContentProject = {
  id: string;
  workspace_id: string;
  brand_id: string | null;
  created_by: string;
  title: string;
  topic: string | null;
  objective: string | null;
  content_type: string;
  selected_platforms: string[];
  content_pillar: string | null;
  target_audience: string | null;
  preferred_tone: string | null;
  language: string;
  keywords: string[];
  required_phrases: string[];
  prohibited_phrases: string[];
  cta_requirements: string | null;
  hashtag_preferences: string | null;
  emoji_preferences: string | null;
  desired_length: string | null;
  research_report_id: string | null;
  status: string;
  created_at: string;
  updated_at: string;
  submitted_at: string | null;
  approved_at: string | null;
};

export type ContentDraftVersion = {
  id: string;
  draft_id: string;
  version_number: number;
  platform: string;
  title: string | null;
  hook: string | null;
  body: string | null;
  cta: string | null;
  hashtags: string[];
  snapshot: Record<string, unknown> | null;
  change_reason: string | null;
  created_by: string | null;
  created_at: string;
};

export type ContentDraft = {
  id: string;
  project_id: string;
  platform: string;
  title: string | null;
  hook: string | null;
  body: string | null;
  cta: string | null;
  hashtags: string[];
  media_asset_ids: string[];
  status: string;
  ai_generated: boolean;
  version_count: number;
  created_at: string;
  updated_at: string;
  versions: ContentDraftVersion[];
};

export type ContentApproval = {
  id: string;
  project_id: string;
  draft_id: string | null;
  status: string;
  comments: string | null;
  reviewed_by: string | null;
  created_at: string;
  updated_at: string;
};
