// Phase 11: multi-agent AI workflows.

export type AgentTool = { name: string; description: string; access: string };

export type Agent = {
  key: string;
  name: string;
  description: string;
  responsibility: string;
  version: string;
  enabled: boolean;
  required_role: string;
  tools: AgentTool[];
  model: { provider: string; temperature: number; max_tokens: number };
  limits: { timeout_seconds: number | null; max_attempts: number | null };
};

export type PlannedStep = {
  step_order: number;
  step_key: string;
  base_key: string;
  kind: "context" | "agent" | "compile";
  agent_key: string;
  agent_name: string;
  label: string;
  depends_on: string[];
  parallel_group: string | null;
};

export type WorkflowDefinition = {
  key: string;
  name: string;
  description: string;
  deliverables: string[];
  requires: string[];
  optional: string[];
  agents: string[];
  supports_revision: boolean;
  accept_mode: "draft" | "idea" | null;
  steps: PlannedStep[];
  disabled_agents: string[];
};

export type AgentLimits = {
  enabled: boolean;
  max_calls_per_workflow: number;
  max_workflow_seconds: number;
  step_timeout_seconds: number;
  max_step_attempts: number;
  max_auto_revisions: number;
  max_revisions: number;
  max_parallel_calls: number;
  max_active_workflows: number;
  max_workflows_per_hour: number;
};

export type GroqStatus = {
  provider: string;
  enabled: boolean;
  configured: boolean;
  source: string;
  model_name: string | null;
  agent_model_override: boolean;
  search_provider_configured: boolean;
};

export type Catalog = {
  workflows: WorkflowDefinition[];
  agents: Agent[];
  limits: AgentLimits;
  groq: GroqStatus;
};

export type WorkflowPlan = {
  workflow: WorkflowDefinition;
  input_data: Record<string, unknown>;
  estimated_agent_calls: number;
  notes: string[];
};

export type Evidence = {
  type: string;
  source_id?: string;
  research_id?: string;
  title?: string;
  url?: string;
  domain?: string | null;
  metric?: string;
  value?: number;
  scope?: string;
};

export type AgentExecution = {
  id: string;
  step_key: string;
  agent_key: string;
  agent_version: string | null;
  attempt_number: number;
  status: string;
  model_name: string | null;
  token_usage: { prompt_tokens: number | null; completion_tokens: number | null; total_tokens: number | null } | null;
  execution_duration_ms: number | null;
  error_message: string | null;
  started_at: string;
  completed_at: string | null;
  warnings: string[];
  evidence: Evidence[];
  result: Record<string, unknown> | null;
};

export type WorkflowStep = {
  id: string;
  step_order: number;
  step_key: string;
  base_key: string;
  revision_round: number;
  kind: "context" | "agent" | "compile";
  agent_key: string;
  agent_name: string;
  label: string;
  depends_on: string[];
  parallel_group: string | null;
  status: string;
  attempt_count: number;
  error_message: string | null;
  execution: AgentExecution | null;
};

export type AgentWorkflow = {
  id: string;
  workspace_id: string;
  brand_id: string | null;
  brand_name: string | null;
  workflow_type: string;
  workflow_name: string;
  name: string;
  task: string;
  status: string;
  error_message: string | null;
  cancel_requested: boolean;
  agent_call_count: number;
  revision_count: number;
  total_tokens: number;
  prompt_tokens: number;
  completion_tokens: number;
  review_status: "pending" | "accepted" | "rejected" | null;
  review_note: string | null;
  accepted_project_id: string | null;
  created_by: string | null;
  created_by_name: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  next_attempt_at: string | null;
  steps_total: number;
  steps_done: number;
  can_cancel: boolean;
  can_accept: boolean;
  can_revise: boolean;
  can_reject: boolean;
  supports_revision: boolean;
  accept_mode: "draft" | "idea" | null;
};

export type DraftVersion = { platform: string; hook: string; body: string; cta: string; hashtags: string[] };

export type BrandIssue = {
  category: string;
  severity: "low" | "medium" | "high";
  platform: string | null;
  excerpt: string;
  explanation: string;
  suggestion: string;
  detected_by: string;
};

export type BrandReview = {
  assessment?: string;
  summary?: string;
  issues?: BrandIssue[];
  suggested_improvements?: string[];
  approval_note?: string;
};

export type ClaimAssessment = {
  claim: string;
  classification: string;
  reasoning: string;
  source_refs: string[];
  source_ids: string[];
};

export type FactCheck = {
  claims?: ClaimAssessment[];
  summary?: string;
  counts?: Record<string, number>;
  citation_coverage?: { factual_claims: number; claims_with_evidence: number; sources_available: number };
};

export type QualityAssessment = {
  scores?: Record<string, { score: number; explanation: string }>;
  overall_score?: number;
  improvements?: string[];
  repetition_issues?: string[];
  summary?: string;
  disclaimer?: string;
};

export type ContentIdea = {
  title: string;
  description: string;
  content_angle: string;
  platform: string;
  format: string;
  content_pillar: string | null;
  objective: string;
  suggested_hook: string;
  source_ids: string[];
};

export type ResearchFinding = {
  claim: string;
  explanation: string;
  category: string;
  verified: boolean;
  source_refs: string[];
  source_ids: string[];
};

export type MetricRef = { metric: string; value: number; scope: string };

export type FinalOutput = {
  type: string;
  decision?: string;
  human_review?: string;
  warnings?: string[];
  evidence?: Evidence[];
  open_issues?: string[];
  revision_limit_reached?: boolean;
  revision_rounds?: number;
  usage?: { agent_calls: number; prompt_tokens: number; completion_tokens: number; total_tokens: number };
  // Content workflows
  content_draft?: { title?: string; versions?: DraftVersion[]; factual_claims?: string[] };
  alternative_hooks?: string[];
  cta_recommendations?: string[];
  brand_review?: BrandReview;
  fact_check?: FactCheck;
  quality_assessment?: QualityAssessment;
  improvement_suggestions?: string[];
  // Research workflow
  research_findings?: { summary?: string; findings?: ResearchFinding[]; assumptions?: string[]; limitations?: string[]; sources_available?: number };
  audience_insights?: string[];
  strategic_recommendations?: {
    strategy_summary?: string;
    recommended_themes?: string[];
    content_pillars?: string[];
    campaign_objectives?: string[];
    content_mix?: { format: string; share_percent: number; rationale: string }[];
    supporting_evidence?: { statement: string; basis: string; source_ids: string[] }[];
    assumptions?: string[];
    limitations?: string[];
  };
  content_opportunities?: string[];
  content_ideas?: ContentIdea[];
  suggested_publishing_frequency?: { posts_per_week: number; rationale: string } | null;
  accepted_idea_projects?: Record<string, string>;
  // Performance workflow
  performance_summary?: string | null;
  measured_data?: { period?: { start: string; end: string }; post_count?: number; connected_accounts?: number } | null;
  content_patterns?: { observation: string; metric_refs: MetricRef[] }[];
  improvement_opportunities?: string[];
  recommendations?: { recommendation: string; rationale: string }[];
  suggested_experiments?: { hypothesis: string; change: string; measure: string }[];
  data_limitations?: string[];
  unverified_numbers?: string[];
  metric_references?: Evidence[];
  label?: string | null;
};

export type AgentWorkflowDetail = AgentWorkflow & {
  input_data: Record<string, unknown>;
  agents: string[];
  steps: WorkflowStep[];
  final_output: FinalOutput | null;
};

export type WorkflowList = { items: AgentWorkflow[]; total: number; offset: number; limit: number };

export type AgentStats = {
  days: number;
  counts: Record<string, number>;
  total: number;
  active: number;
  agent_calls: number;
  total_tokens: number;
  limits: AgentLimits;
  recent: AgentWorkflow[];
};

export type AcceptResult = { project_id: string; draft_ids: Record<string, string>; status: string; workflow: AgentWorkflow };

export const ACTIVE_STATUSES = ["pending", "running"];

export function isActive(status: string): boolean {
  return ACTIVE_STATUSES.includes(status);
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

export function reviewLabel(status: AgentWorkflow["review_status"]): string {
  if (status === "pending") return "Awaiting your review";
  if (status === "accepted") return "Accepted";
  if (status === "rejected") return "Rejected";
  return "—";
}

export const CLASSIFICATION_LABELS: Record<string, string> = {
  SUPPORTED: "Supported",
  PARTIALLY_SUPPORTED: "Partially supported",
  UNSUPPORTED: "Unsupported",
  CONTRADICTED: "Contradicted",
  OPINION: "Opinion",
  UNVERIFIABLE: "Unverifiable",
};
