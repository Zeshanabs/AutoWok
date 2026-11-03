export type Brand = {
  id: string;
  workspace_id: string;
  name: string;
  slug: string;
  description: string | null;
  website_url: string | null;
  industry: string | null;
  business_type: string | null;
  logo_url: string | null;
  primary_color: string | null;
  secondary_color: string | null;
  status: "ACTIVE" | "ARCHIVED";
  created_by: string;
  created_at: string;
  updated_at: string;
};

export type BrandVoice = {
  id: string;
  brand_id: string;
  tone: string | null;
  personality: string | null;
  writing_style: string | null;
  communication_style: string | null;
  vocabulary_preferences: string[];
  preferred_phrases: string[];
  prohibited_phrases: string[];
  language_preferences: string[];
  emoji_policy: string | null;
  hashtag_policy: string | null;
  call_to_action_style: string | null;
  created_at: string;
  updated_at: string;
};

export type TargetAudience = {
  id: string;
  brand_id: string;
  audience_name: string;
  description: string | null;
  age_range: string | null;
  locations: string[];
  interests: string[];
  pain_points: string[];
  goals: string[];
  preferred_platforms: string[];
  demographics: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

export type ContentPillar = {
  id: string;
  brand_id: string;
  name: string;
  description: string | null;
  objective: string | null;
  suggested_topics: string[];
  priority: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type BrandGoal = {
  id: string;
  brand_id: string;
  goal_type: string;
  title: string;
  description: string | null;
  priority: number;
  target_metric: string | null;
  target_value: string | null;
  target_period: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type BrandPolicy = {
  id: string;
  brand_id: string;
  policy_type: string;
  name: string;
  description: string | null;
  policy_value: string;
  severity: "LOW" | "MEDIUM" | "HIGH";
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type BrandOverview = {
  brand: Brand;
  voice: BrandVoice | null;
  audiences: TargetAudience[];
  pillars: ContentPillar[];
  goals: BrandGoal[];
  policies: BrandPolicy[];
};

export type AIProvider = {
  id: string;
  workspace_id: string;
  provider_name: "openai" | "anthropic" | "gemini" | "openai_compatible";
  display_name: string;
  model_name: string;
  base_url: string | null;
  api_key_configured: boolean;
  masked_api_key: string;
  is_active: boolean;
  is_default: boolean;
  configuration: Record<string, unknown>;
  created_by: string;
  created_at: string;
  updated_at: string;
  last_tested_at: string | null;
  last_test_status: string | null;
};
