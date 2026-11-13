# Phase 10: Controlled workflow automations and rule-based execution

Phase 10 adds an automation engine that lets workspace Owners and Admins define rules of the form
**when** *trigger* **and** *conditions* **then** *actions*, test them safely, enable or pause them, and
inspect every execution. The engine is deliberately narrow: it reacts only to events the application
already emits, evaluates only a validated JSON condition structure (never code), and runs only
allowlisted actions that call existing Autowok services. It cannot approve or publish content.

## User interface

| Route | Purpose |
| --- | --- |
| `/dashboard/automations` | List with name, description, trigger, status, last execution, success/failure counts, creator and last update; status filter |
| `/dashboard/automations/new` | Builder: name and trigger (with trigger configuration where needed), conditions, ordered actions with generated configuration forms, limits, review, **Validate**, **Test (dry run)**, **Save as draft** |
| `/dashboard/automations/[automationId]` | Configuration, status and controls (Enable / Pause / Resume / Edit / Duplicate / Archive / Delete, each destructive change confirmed), execution history with per-step results, recent failures, retry of eligible failed executions, dry-run panel with the last stored simulated result |
| `/dashboard/automations/[automationId]/edit` | Edit an existing draft, enabled or paused automation |
| `/dashboard/notifications` | Personal in-app notifications (read / unread, mark one or all read) and workspace tasks created by automations (open / done) |

Members can view automations, executions, notifications and tasks. Only Owners and Admins can create,
edit, enable, pause, resume, archive, delete, duplicate, dry-run or retry.

## Architecture

```
business change ──emit()──▶ automation_events (same transaction, dedupe_key)
                                     │  worker: dispatch_automation_events
                                     ▼
          enabled automations for (workspace, trigger_type) ── safety checks ── conditions
                                     │ match
                                     ▼
                      automation_executions (unique idempotency key, pending)
                                     │  worker: run_automation_executions
                                     ▼
            steps in order → notifications / tasks / labels / assignment / analytics refresh
```

Components (all under `backend/app/services/automation/`):

| Component | Module | Role |
| --- | --- | --- |
| Trigger registry | `registry.py` | Stable event identifiers, typed payload schemas, sample payloads, trigger configuration models |
| Condition evaluator | `conditions.py` | Strict validation and evaluation of the JSON condition tree |
| Action registry | `actions.py` | Allowlisted actions with pydantic configuration, role requirements, run and simulate functions |
| Templates | `templates.py` | `{field}` placeholder substitution restricted to schema fields |
| Event emission | `events.py` | Outbox `emit()`, publishing start/completion hooks, payload builders, loop tagging |
| Execution engine | `engine.py` | Event dispatch, execution claiming, step execution, retries, limits |
| Reminders | `reminders.py` | Periodic `APPROVAL_REMINDER_DUE` producer |
| Management | `service.py` | Validation, lifecycle, duplication, dry run |
| Worker tasks | `worker_tasks.py` | Registration with `python -m app.worker` |
| Notifications | `app/services/notifications.py` | Reusable in-app notification service |

The API lives in `app/api/v1/routes/automations.py` and `app/api/v1/routes/notifications.py`.

## Data model (migration `20261112_0010`)

| Table | Purpose | Notes |
| --- | --- | --- |
| `automations` | Rule definition and counters | `status` ∈ draft, enabled, paused, archived; `trigger_configuration`, `conditions` (JSON); `max_executions`, `cooldown_seconds`; `execution_count`/`success_count`/`failure_count`; `last_dry_run`; `created_by`, `updated_by` (the owner whose permissions it runs with) |
| `automation_actions` | Ordered actions | unique `(automation_id, execution_order)` |
| `automation_events` | Persisted trigger events (outbox) | unique `dedupe_key`; `status` ∈ pending, processing, processed, failed; lease columns; `origin_automation_id`, `origin_execution_id`, `chain_depth`; `dispatch_summary` records every automation's outcome |
| `automation_executions` | One run of one automation for one event | unique `idempotency_key` (`<automation>:event:<event>` or `<automation>:approval:<approval>`); `status` ∈ pending, running, succeeded, failed, cancelled; retry and lease columns; `execution_context` holds the payload snapshot and condition results |
| `automation_execution_steps` | Per-action result | `status` ∈ pending, running, succeeded, failed, skipped; `result_summary`, `error_message` |
| `notifications` | In-app notifications | per user and workspace, `read_at`, optional `dedupe_key` |
| `content_tasks` | Internal work items | `kind` ∈ task, followup, reminder, incident, analytics_followup; `severity`, `assigned_to`, `due_at`, `status` ∈ open, done |
| `content_projects` | Two new columns | `assigned_to` (nullable user) and `labels` (JSON list) — internal metadata, not content |

Event payloads contain only the fields of the trigger schema (ids, statuses, titles, counts). Tokens,
credentials and comments are never part of a schema and therefore never stored.

## Triggers

Every trigger has a stable identifier, a documented payload schema (field name, type, operators), a
`workspace_id`, an `occurred_at` timestamp and a source entity reference. `GET /automations/catalog`
returns the full schema. Payloads are normalized on emission: unknown fields are dropped and values that
do not fit their type become `null`.

| Trigger | Emitted when | Dedupe key |
| --- | --- | --- |
| `CONTENT_CREATED` | A content project is created | `content_created:<project>` |
| `CONTENT_SUBMITTED_FOR_APPROVAL` | A project is submitted for review | `content_submitted:<approval>` |
| `CONTENT_APPROVED` | A reviewer approves | `content_approved:<approval>` |
| `CONTENT_REJECTED` | A reviewer rejects **or requests changes** (`decision` field) | `content_rejected:<approval>` |
| `CONTENT_UPDATED` | Project fields change, a draft is saved, generated or a version is restored | unique per change |
| `POST_SCHEDULED` | A scheduled post is created | `post_scheduled:<schedule>:<revision>` |
| `POST_PUBLISHING` | A worker claims a publishing job (per attempt) | `post_publishing:<job>:<attempt>` |
| `POST_PUBLISHED` | A publishing job succeeds | `post_published:<job>` |
| `POST_PUBLISH_FAILED` | A publishing job reaches `failed` (no more automatic retries, or user action needed) | `post_publish_failed:<job>:<attempt>` |
| `POST_CANCELLED` | A pending publishing job is cancelled | `post_cancelled:<job>` |
| `ANALYTICS_SYNC_COMPLETED` | A sync job ends `succeeded` or `partial` | `analytics_sync_completed:<job>` |
| `ANALYTICS_SYNC_FAILED` | A sync job ends `failed` (payload includes `consecutive_failures`) | `analytics_sync_failed:<job>` |
| `TEAM_MEMBER_ASSIGNED` | A project is assigned via `POST /content/projects/{id}/assign` or the `assign_content` action | unique per assignment |
| `APPROVAL_REMINDER_DUE` | Produced by the worker once per pending approval per elapsed hour (only where an enabled automation uses it); the automation's `deadline_hours` decides when it fires, once per approval | `approval_reminder:<approval>:<hours>` |

Field groups:

* Content triggers: `project_id`, `brand_id`, `title`, `content_type`, `platforms` (list), `status`,
  `created_by`, `assigned_to`, `actor_user_id`, `labels` (list); approval triggers add `approval_id`,
  `decision`, `reviewer_id`.
* Publishing triggers: `publication_id`, `project_id`, `draft_id`, `brand_id`, `platform`,
  `social_account_id`, `source`, `status`, `attempt_count`, `max_attempts`, `error_category`,
  `error_code`, `requires_user_action`, `outcome_uncertain`, `requested_by`, `scheduled_post_id`, `title`.
* `POST_SCHEDULED`: `scheduled_post_id`, `project_id`, `draft_id`, `brand_id`, `platform`,
  `social_account_id`, `scheduled_at`, `timezone`, `created_by`, `title`.
* Analytics triggers: `sync_job_id`, `social_account_id`, `brand_id`, `platform`, `status`, `trigger`,
  `attempt_count`, `consecutive_failures`, `records_processed`, `error_category`, `error_code`, `requested_by`.
* `TEAM_MEMBER_ASSIGNED`: `project_id`, `brand_id`, `title`, `status`, `assigned_to`, `assigned_by`, `created_by`, `platforms`.
* `APPROVAL_REMINDER_DUE`: `approval_id`, `project_id`, `brand_id`, `title`, `created_by`, `assigned_to`,
  `pending_hours`, `submitted_at`, `platforms`.

Events are written **in the same database transaction** as the change they describe (outbox pattern), so
a crash leaves either both or neither. Emission failures are logged and never break the business
operation. A Redis wake-up is sent as a hint; the worker also polls the database every
`WORKER_POLL_INTERVAL_SECONDS`, so a Redis outage only delays processing.

## Conditions

```json
{"logic": "and", "rules": [
  {"field": "platform", "operator": "equals", "value": "facebook"},
  {"logic": "or", "rules": [
    {"field": "error_category", "operator": "in", "value": ["token_expired", "permission"]},
    {"field": "attempt_count", "operator": "greater_than", "value": 2}
  ]}
]}
```

* `logic` is `and` or `or`; an empty rule list always matches. Groups may be nested up to
  `AUTOMATION_MAX_CONDITION_DEPTH` (default 2) with at most `AUTOMATION_MAX_CONDITIONS` rules (default 20).
* Operators by field type:
  * string: `equals`, `not_equals`, `in`, `not_in`, `contains`, `not_contains`, `is_empty`, `is_not_empty`
  * uuid: `equals`, `not_equals`, `in`, `not_in`, `is_empty`, `is_not_empty`
  * number: `equals`, `not_equals`, `greater_than`, `greater_than_or_equal`, `less_than`, `less_than_or_equal`, `is_empty`, `is_not_empty`
  * boolean: `equals`
  * list: `contains`, `not_contains`, `is_empty`, `is_not_empty`
* Unknown fields, unsupported operators, wrong value types, values outside a field's documented choices,
  unknown keys and malformed groups are rejected with explicit messages (HTTP 422).
* String comparisons are case-insensitive. No expression language, JavaScript, Python or SQL is ever evaluated.
* The builder edits a flat rule list with one `and`/`or` selector; nested groups are accepted by the API.

## Actions

| Action | What it does | Owner role | Allowed triggers |
| --- | --- | --- | --- |
| `notify_member` | In-app notification to one workspace member (`user_id`, `message`, optional `title`) | Member | any |
| `notify_admins` | In-app notification to every Owner and Admin | Member | any |
| `notify_content_owner` | Notify the `creator`, `assignee`, `actor` or `requester` referenced by the event | Member | any trigger that has the matching field |
| `assign_content` | Set the content post's assignee (and notify them); emits `TEAM_MEMBER_ASSIGNED` | Admin | content, team and publishing triggers |
| `create_task` | Create a `task`, `followup` or `analytics_followup` with optional assignee and due date | Member | any |
| `add_label` | Add an internal label to the content post (metadata only; no new version, approval untouched) | Member | content, team and publishing triggers |
| `create_approval_reminder` | Create a reminder task and notify reviewers while the post is awaiting approval | Member | `CONTENT_SUBMITTED_FOR_APPROVAL`, `APPROVAL_REMINDER_DUE` |
| `record_publishing_incident` | Record an incident task with severity and notify administrators | Member | `POST_PUBLISH_FAILED` |
| `request_analytics_refresh` | Request an eligible analytics sync through the Phase 9 service (cooldown and eligibility apply) | Admin | `POST_PUBLISHED`, `ANALYTICS_SYNC_FAILED` |

Text fields (`title`, `message`, `description`, `note`) accept `{field}` placeholders that must name a
field of the trigger schema; anything else is rejected at save time. Recipients and assignees must be
members of the workspace, checked when saving and again when running.

**Email** is not implemented: Autowok has no email delivery service yet, so no email action exists.

Every action validates its configuration, checks the automation owner's current role, records a step
result, and is idempotent per execution step (notifications and tasks carry a `dedupe_key`), so a retried
execution never duplicates side effects. There is no action for HTTP requests, shell commands, database
queries or code execution.

## Execution engine

### Dispatch

The worker claims pending events with a conditional `UPDATE` and a lease. For every enabled automation of
the event's workspace and trigger it evaluates, in order, and records the outcome in
`automation_events.dispatch_summary`:

| Outcome | Meaning |
| --- | --- |
| `chain_depth_exceeded` | The event was caused by automations more than `AUTOMATION_MAX_CHAIN_DEPTH` levels deep |
| `self_trigger_blocked` | The event was caused by this automation's own execution |
| `brand_mismatch` | The automation is scoped to a different brand |
| `deadline_not_reached` | Reminder: the approval has not waited `deadline_hours` yet |
| `execution_limit_reached` | The automation's lifetime `max_executions` cap |
| `cooldown` | `cooldown_seconds` since the last execution has not elapsed |
| `rate_limited` | `AUTOMATION_MAX_EXECUTIONS_PER_HOUR` for this automation |
| `workspace_limit_reached` | `AUTOMATION_WORKSPACE_MAX_EXECUTIONS_PER_DAY` |
| `conditions_not_met` | Conditions evaluated false (results included) |
| `duplicate` | An execution with the same idempotency key already exists |
| `queued` | An execution was created |

### Run

Executions are claimed with a conditional `UPDATE` that also enforces
`AUTOMATION_MAX_CONCURRENT_EXECUTIONS` running executions per automation. If the automation is no longer
enabled the execution is `cancelled`. Steps run in order; each step is committed and the lease renewed.
Steps that already succeeded are skipped on a retry. An execution that exceeds
`AUTOMATION_EXECUTION_TIMEOUT_SECONDS` fails with the remaining steps skipped.

* Temporary failures (`ActionRetryable`, unexpected exceptions) → the execution returns to `pending`
  with exponential backoff and jitter, up to `AUTOMATION_MAX_RETRIES`.
* Permanent failures (`ActionError`, permission errors) → `failed`; remaining steps are `skipped`; the
  automation owner receives one `automation_failure` notification; an audit record is written.
* Owners/Admins can retry a failed execution of an enabled automation; failed and skipped steps are rerun.

### Reliability

* Events and executions live in the database; Redis is only a wake-up hint. Worker restarts, lost
  messages and Redis outages delay work by at most one poll interval.
* Abandoned events/executions are recovered when their lease expires (`AUTOMATION_LEASE_SECONDS`).
* Dispatch errors retry with backoff up to `AUTOMATION_EVENT_MAX_ATTEMPTS`, then the event is `failed`
  with `last_error`.
* Several workers can run at once: all claims are atomic conditional updates and all side effects are idempotent.

## Safety and permission controls

* Workspace isolation on every query; cross-workspace ids return 404.
* Owners/Admins manage; Members read. Enabling re-validates the whole definition and makes the enabling
  admin the owner whose role is checked at execution time. If that person loses the role or leaves, admin
  actions fail with an explicit message and the detail page lists the issue.
* Allowlisted triggers, operators and actions; strict pydantic schemas with `extra="forbid"`.
* No code execution, no outbound HTTP, no shell, no raw SQL from configuration.
* Idempotency: unique event `dedupe_key`, unique execution `idempotency_key`, per-step dedupe keys for
  notifications and tasks.
* Loop prevention: events emitted while a step runs are tagged with the origin automation and
  `chain_depth + 1`; the dispatcher refuses self-triggered events and anything deeper than the limit.
* Limits (defaults): 50 automations per workspace, 10 actions, 20 conditions, depth 2, 60 executions per
  hour per automation, 1,000 per day per workspace, 2 concurrent executions per automation, 60 s per
  execution, 3 retries, optional per-automation lifetime cap and cooldown.
* Pause stops new executions immediately and cancels queued ones; archive also cancels pending executions.
* Audit log actions: `automation.created/updated/enabled/paused/resumed/archived/deleted/duplicated/dry_run`,
  `automation.execution_succeeded/failed/cancelled/retried`, `content.assigned/unassigned`,
  `publishing.incident_recorded`.

### Approval and publishing safeguards

Automations cannot approve content, decide approvals, publish, schedule or edit content. The only content
mutations are the internal `assigned_to` and `labels` columns, which are not part of drafts, create no
version and leave approval status untouched. Immediate publishing (Phase 7) and scheduling (Phase 8) are
not reachable from any action. `request_analytics_refresh` is the only action that leads to an external
request and it goes through the Phase 9 service with its eligibility checks and cooldown.

## Dry run

`POST /workspaces/{id}/automations/dry-run` (unsaved definition) and
`POST /workspaces/{id}/automations/{automation_id}/dry-run` (saved) evaluate the configuration against the
trigger's built-in sample payload or the latest recorded event of that type in the workspace
(`payload_source: "latest_event"`), optionally with `payload_overrides` (validated against the schema).
The response is always labelled `simulated: true` with a notice, and contains: the payload used, each
condition's pass/fail with expected and actual values, whether the automation would run, and for every
action in execution order whether it `would_run` or is `blocked`, with a human description such as
"Would notify 2 administrator(s) (…)". Nothing is created: the session is rolled back before the result
is stored on the saved automation (`GET …/dry-run` returns the last result).

## Notifications and tasks

* `GET /workspaces/{id}/notifications?unread_only=` → `{items, unread_count}` for the caller only.
* `POST /workspaces/{id}/notifications/{notification_id}/read`, `POST /workspaces/{id}/notifications/read-all`
  (optional `notification_ids`).
* `GET /workspaces/{id}/tasks?status=open|done&kind=&mine=`; `POST /workspaces/{id}/tasks/{task_id}/complete`
  and `/reopen`.
* Categories: `automation`, `approval_reminder`, `publishing_incident`, `automation_failure`, `assignment`, `task`.
* Duplicate suppression through dedupe keys; there are no user notification preferences yet.

## API (`/api/v1`)

| Method | Path | Role | Notes |
| --- | --- | --- | --- |
| `GET` | `/workspaces/{id}/automations/catalog` | Member | Triggers (fields, operators, samples), actions (JSON schema), limits |
| `POST` | `/workspaces/{id}/automations/validate` | Admin | `{valid, errors, warnings}` without saving |
| `POST` | `/workspaces/{id}/automations/dry-run` | Admin | Simulate an unsaved definition |
| `GET`, `POST` | `/workspaces/{id}/automations` | Member / Admin | List (`status`, `trigger_type`, `include_archived`) or create a draft |
| `GET`, `PATCH`, `DELETE` | `/workspaces/{id}/automations/{automation_id}` | Member / Admin / Admin | Detail with recent executions; edit; delete (draft or archived only) |
| `POST` | `/workspaces/{id}/automations/{automation_id}/enable\|pause\|resume\|archive\|duplicate` | Admin | Lifecycle |
| `POST`, `GET` | `/workspaces/{id}/automations/{automation_id}/dry-run` | Admin / Member | Run or read the last simulation |
| `GET` | `/workspaces/{id}/automations/{automation_id}/executions?status=` | Member | History with steps |
| `GET` | `/workspaces/{id}/automation-executions?automation_id=&status=` | Member | Workspace-wide history |
| `GET` | `/workspaces/{id}/automation-executions/{execution_id}` | Member | Execution with context and steps |
| `POST` | `/workspaces/{id}/automation-executions/{execution_id}/retry` | Admin | Retry an eligible failed execution |
| `POST` | `/content/projects/{project_id}/assign` | Member | `{user_id}` or `{user_id: null}`; emits `TEAM_MEMBER_ASSIGNED` |

Create/update body:

```json
{
  "name": "Notify reviewers",
  "description": "Tell admins when content is submitted.",
  "brand_id": null,
  "trigger_type": "CONTENT_SUBMITTED_FOR_APPROVAL",
  "trigger_configuration": {},
  "conditions": {"logic": "and", "rules": [{"field": "platforms", "operator": "contains", "value": "facebook"}]},
  "actions": [
    {"action_type": "notify_admins", "configuration": {"message": "“{title}” is waiting for review."}},
    {"action_type": "add_label", "configuration": {"label": "needs-review"}}
  ],
  "max_executions": null,
  "cooldown_seconds": 0
}
```

## Environment

| Variable | Default | Purpose |
| --- | --- | --- |
| `AUTOMATION_ENABLED` | `true` | Disables emission, dispatch and execution when `false` |
| `AUTOMATION_MAX_PER_WORKSPACE` | 50 | Non-archived automations per workspace |
| `AUTOMATION_MAX_ACTIONS` | 10 | Actions per automation |
| `AUTOMATION_MAX_CONDITIONS` / `AUTOMATION_MAX_CONDITION_DEPTH` | 20 / 2 | Condition limits |
| `AUTOMATION_MAX_EXECUTIONS_PER_HOUR` | 60 | Per automation |
| `AUTOMATION_WORKSPACE_MAX_EXECUTIONS_PER_DAY` | 1000 | Per workspace |
| `AUTOMATION_MAX_CHAIN_DEPTH` | 3 | Loop protection |
| `AUTOMATION_MAX_RETRIES` | 3 | Per execution |
| `AUTOMATION_EXECUTION_TIMEOUT_SECONDS` | 60 | Per execution |
| `AUTOMATION_LEASE_SECONDS` | 300 | Claim lease for events and executions |
| `AUTOMATION_MAX_CONCURRENT_EXECUTIONS` | 2 | Running executions per automation |
| `AUTOMATION_EVENT_MAX_ATTEMPTS` | 5 | Dispatch attempts per event |
| `AUTOMATION_BACKOFF_BASE_SECONDS` / `AUTOMATION_BACKOFF_MAX_SECONDS` | 15 / 600 | Retry backoff |

## Running locally

```
cd backend
alembic upgrade head          # adds the Phase 10 tables
uvicorn app.main:app --reload # API
python -m app.worker          # dispatches events and runs executions
cd ../frontend && npm run dev
```

With Docker Compose nothing changes: the `backend` service applies the migration and the `worker`
service runs the automation tasks alongside scheduling and analytics.

## Testing

```
cd backend && pytest tests/test_phase10_automations.py   # 16 tests
cd frontend && npx vitest run app/dashboard/automations  # builder, list and dry-run panel
```

The backend tests cover: the trigger registry and payload normalization; emission dedupe and the
`AUTOMATION_ENABLED` switch; condition validation (unknown fields, operators, types, choices, limits,
nesting) and evaluation (AND/OR, every operator); API permissions and lifecycle; cross-workspace
isolation; end-to-end execution through the worker loop; duplicate delivery; publishing failure →
incident (through the real publishing hooks with a mocked Graph API); scheduling and analytics events;
self-trigger and chain-depth blocking; hourly, cooldown, workspace and lifetime limits; paused and
unauthorized automations; retry with no duplicate side effects; crash recovery through leases;
concurrency; the time limit; approval reminders firing once per approval; dry runs with no side effects;
the assignment endpoint.

## Limitations

* No email delivery (no email service exists in Autowok yet), so no email action.
* No per-user notification preferences; duplicate suppression relies on dedupe keys.
* The builder edits a single level of conditions; nested groups are API-only.
* Rate and concurrency limits are enforced in the database and are exact for a single database; the
  hourly/daily counters are best-effort under heavy parallel dispatch (two workers may both admit the
  60th execution).
* Execution time limits are cooperative: checked between steps, not enforced inside a step.
* `POST_PUBLISHING`, `POST_PUBLISHED`, `POST_PUBLISH_FAILED`, `POST_CANCELLED`, `ANALYTICS_SYNC_*` were
  exercised against mocked Meta responses only, like the rest of Phases 7–9.
* PostgreSQL/Docker runs of the migration were not verified in this environment (the Docker daemon is
  unavailable); the migration was compiled with `alembic upgrade --sql` and the models were exercised on SQLite.
