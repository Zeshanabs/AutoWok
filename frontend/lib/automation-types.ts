export type AutomationStatus = "draft" | "enabled" | "paused" | "archived";
export type ExecutionStatus = "pending" | "running" | "succeeded" | "failed" | "cancelled";

export type TriggerField = {
  name: string;
  type: "string" | "number" | "boolean" | "uuid" | "list";
  label: string;
  ref: "brand" | "user" | "social_account" | "project" | null;
  choices: string[] | null;
  description: string;
  operators: string[];
};

export type TriggerConfigurationField = {
  name: string;
  type: string;
  label: string;
  required: boolean;
  min?: number;
  max?: number;
  description?: string;
};

export type TriggerSpec = {
  type: string;
  label: string;
  description: string;
  category: string;
  entity_type: string;
  fields: TriggerField[];
  sample_payload: Record<string, unknown>;
  configuration_fields: TriggerConfigurationField[];
};

export type JsonSchemaProperty = {
  type?: string | string[];
  anyOf?: JsonSchemaProperty[];
  enum?: string[];
  const?: string;
  format?: string;
  default?: unknown;
  description?: string;
  maxLength?: number;
  minimum?: number;
  maximum?: number;
  title?: string;
};

export type ActionSpec = {
  type: string;
  label: string;
  description: string;
  category: string;
  required_role: "ADMIN" | "MEMBER";
  allowed_triggers: string[] | null;
  required_fields: string[];
  configuration_schema: {
    properties?: Record<string, JsonSchemaProperty>;
    required?: string[];
  };
};

export type Catalog = {
  triggers: TriggerSpec[];
  actions: ActionSpec[];
  limits: Record<string, number | boolean>;
};

export type ConditionRule = { field: string; operator: string; value?: unknown };
export type ConditionGroup = { logic: "and" | "or"; rules: Array<ConditionRule | ConditionGroup> };

export type ActionInput = { action_type: string; configuration: Record<string, unknown> };

export type AutomationDefinition = {
  name: string;
  description: string | null;
  brand_id: string | null;
  trigger_type: string;
  trigger_configuration: Record<string, unknown>;
  conditions: ConditionGroup;
  actions: ActionInput[];
  max_executions: number | null;
  cooldown_seconds: number;
};

export type ExecutionStep = {
  id: string;
  action_type: string;
  execution_order: number;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  result_summary: Record<string, unknown> | null;
  error_message: string | null;
};

export type Execution = {
  id: string;
  automation_id: string;
  automation_name: string | null;
  workspace_id: string;
  trigger_event_id: string | null;
  trigger_type: string;
  status: ExecutionStatus;
  retry_count: number;
  max_retries: number;
  next_attempt_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  chain_depth: number;
  created_at: string;
  can_retry: boolean;
  execution_context: Record<string, unknown>;
  steps: ExecutionStep[];
};

export type AutomationAction = {
  id: string;
  action_type: string;
  label: string;
  action_configuration: Record<string, unknown>;
  execution_order: number;
};

export type Automation = {
  id: string;
  workspace_id: string;
  brand_id: string | null;
  brand_name: string | null;
  name: string;
  description: string | null;
  status: AutomationStatus;
  trigger_type: string;
  trigger_label: string;
  trigger_configuration: Record<string, unknown>;
  conditions: ConditionGroup;
  max_executions: number | null;
  cooldown_seconds: number;
  execution_count: number;
  success_count: number;
  failure_count: number;
  last_executed_at: string | null;
  last_execution: Execution | null;
  created_by: string | null;
  created_by_name: string | null;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
  enabled_at: string | null;
  paused_at: string | null;
  archived_at: string | null;
  actions: AutomationAction[];
  issues: string[];
  can_enable: boolean;
};

export type AutomationDetail = Automation & {
  recent_executions: Execution[];
  last_dry_run: DryRunResult | null;
  last_dry_run_at: string | null;
};

export type DryRunAction = {
  order: number;
  action_type: string;
  label: string;
  status: "would_run" | "blocked";
  detail: string;
  errors: string[];
};

export type ConditionResult = {
  path: string;
  passed: boolean;
  logic?: string;
  children?: ConditionResult[];
  field?: string | null;
  operator?: string | null;
  expected?: unknown;
  actual?: unknown;
};

export type DryRunResult = {
  simulated: true;
  generated_at: string;
  trigger_type: string;
  payload_source: string;
  event_id: string | null;
  payload: Record<string, unknown>;
  conditions_passed: boolean;
  condition_results: ConditionResult;
  would_execute: boolean;
  actions: DryRunAction[];
  errors: string[];
  notice: string;
};

export type ValidationResult = { valid: boolean; errors: string[]; warnings: string[] };

export type Notification = {
  id: string;
  workspace_id: string;
  category: string;
  title: string;
  message: string;
  resource_type: string | null;
  resource_id: string | null;
  automation_id: string | null;
  execution_id: string | null;
  read_at: string | null;
  created_at: string;
};

export type NotificationList = { items: Notification[]; unread_count: number };

export type WorkTask = {
  id: string;
  workspace_id: string;
  project_id: string | null;
  project_title: string | null;
  publication_id: string | null;
  kind: string;
  title: string;
  description: string | null;
  severity: string | null;
  status: "open" | "done";
  assigned_to: string | null;
  assigned_to_name: string | null;
  due_at: string | null;
  completed_at: string | null;
  automation_id: string | null;
  execution_id: string | null;
  created_at: string;
};

export const OPERATOR_LABELS: Record<string, string> = {
  equals: "is",
  not_equals: "is not",
  in: "is one of",
  not_in: "is none of",
  contains: "contains",
  not_contains: "does not contain",
  is_empty: "is empty",
  is_not_empty: "is not empty",
  greater_than: "is greater than",
  greater_than_or_equal: "is at least",
  less_than: "is less than",
  less_than_or_equal: "is at most",
};

export const VALUELESS_OPERATORS = new Set(["is_empty", "is_not_empty"]);
export const LIST_OPERATORS = new Set(["in", "not_in"]);

export const DISPATCH_OUTCOME_LABELS: Record<string, string> = {
  queued: "Execution queued",
  duplicate: "Already executed for this event",
  conditions_not_met: "Conditions not met",
  rate_limited: "Hourly execution limit reached",
  workspace_limit_reached: "Workspace daily limit reached",
  cooldown: "In cooldown",
  execution_limit_reached: "Lifetime execution limit reached",
  self_trigger_blocked: "Blocked: caused by this automation",
  chain_depth_exceeded: "Blocked: automation chain too deep",
  brand_mismatch: "Different brand",
  deadline_not_reached: "Deadline not reached yet",
  not_enabled: "Automation not enabled",
};

export function isConditionGroup(rule: ConditionRule | ConditionGroup): rule is ConditionGroup {
  return "rules" in rule;
}

export function emptyConditions(): ConditionGroup {
  return { logic: "and", rules: [] };
}

export function formatDuration(seconds: number): string {
  if (!seconds) return "none";
  if (seconds % 3600 === 0) return `${seconds / 3600} h`;
  if (seconds % 60 === 0) return `${seconds / 60} min`;
  return `${seconds} s`;
}
