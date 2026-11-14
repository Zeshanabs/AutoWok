# Phase 11: Multi-agent AI intelligence and orchestration

Phase 11 adds a controlled multi-agent system. Eight specialized agents (research, strategy, planning,
writing, brand review, fact-checking, quality review, analytics) work together in four predefined
workflows. A central orchestrator plans each run, executes the agents in dependency order, validates
every answer and compiles a deliverable **for a person to review**.

The system is deliberately bounded:

- Agents are Python objects in a registry. Users cannot add agents, prompts, tools or steps.
- Agents read through a small allowlist of workspace-scoped tools. There is no tool for publishing,
  scheduling, approving, deleting, roles, credentials, HTTP, shell or SQL.
- Every model answer is treated as untrusted data: parsed as JSON, validated against a schema, then
  checked against the records the agent was given. Nothing an agent returns is executed.
- Content reaches the content studio only when a person accepts it, always as a `draft`. Approval,
  scheduling and publishing work exactly as in Phases 5–8.

Agents use **Groq for inference** (through the existing `GroqService`) and the **existing Phase 4
research engine and its search provider** for external research. Groq does not search the web.

## Architecture

```
 User (browser)                                   /dashboard/ai-agents
     │  start workflow · cancel · accept · revise · reject
     ▼
 FastAPI  /workspaces/{id}/agent-workflows        auth · workspace role · validation · rate limits
     │  create_workflow(): validate inputs, plan steps, persist            (agent_workflows, agent_workflow_steps)
     ▼
 Worker   python -m app.worker ── run_agent_workflows ── claim with lease
     │
     ▼
 Orchestrator (app/services/agents/orchestrator.py)
     │   for each ready step, in dependency order:
     │
     ├── context step ──▶ read-only tools ──────────────┐
     │                                                   │
     ├── agent step ───▶ Specialized agent               │
     │                     prepare():  ToolBox ──────────┼──▶ Existing services
     │                     infer:      AgentLLM ─▶ GroqService ─▶ Groq API        brand_context_service (Phase 2)
     │                     finalize(): schema + evidence checks                  ResearchEngineService + sources (Phase 4)
     │                                                   │                       ContentStudioService (Phase 5)
     └── compile step ─▶ deliverable + review gate       │                       analytics queries (Phase 9)
                              │                          ▼
                              ▼                 Validated results (agent_executions.output_data)
                     bounded revision? ──yes──▶ writer + reviewers run once more
                              │ no
                              ▼
                     final_output  ──▶  Human review  ──accept──▶ draft content project (Phase 5 approval still required)
                                                       ──revise──▶ one more bounded round
                                                       ──reject──▶ nothing saved
```

Code map (`backend/app/services/agents/`):

| Module | Responsibility |
| --- | --- |
| `registry.py` | `AgentSpec`, registration and validation, workspace enable/disable |
| `tools.py` | Tool allowlist, `ToolBox`, workspace-scoped tool implementations |
| `schemas.py` | Input/output schemas for every agent and the response envelope |
| `llm.py` | `AgentLLM`: Groq calls through `GroqService`, error mapping, prompt helpers |
| `agents.py` | The eight agents (`prepare` / `finalize`) and their registration |
| `workflows.py` | The four workflow definitions, input builders, compile steps, review gate |
| `orchestrator.py` | Planning, claiming, execution, retries, timeouts, cancellation, recovery |
| `service.py` | Human review (accept / reject / revise) and statistics |
| `worker_tasks.py` | Periodic task for the background worker |

## Agent registry

Each agent is an `AgentSpec` registered at import time:

| Field | Meaning |
| --- | --- |
| `key` | Identifier (`^[a-z][a-z0-9_]{2,40}$`) |
| `name`, `description`, `responsibility` | Shown in the UI and API |
| `version` | Semantic version, stored on every execution |
| `input_model`, `output_model` | Pydantic schemas |
| `tools` | Names of the registered tools the agent may call |
| `required_role` | Minimum workspace role of the person the workflow runs for (`MEMBER` for all agents today) |
| `model` | Groq request settings: `temperature`, `max_tokens`. The model id comes from configuration |
| `limits` | Optional per-agent `timeout_seconds` and `max_attempts` (default: server settings) |
| `prepare`, `finalize` | The agent's two code halves |

`register_agent` rejects invalid keys, versions, unknown or duplicate tools, unknown roles, out-of-range
model settings or limits, non-Pydantic schemas and duplicate keys. A workspace Owner or Admin can switch
an agent off (`agent_settings`). A workflow cannot start while one of its agents is off, and a queued
workflow fails at that agent's step.

### Agents

| Key | Agent | Tools | Responsibility |
| --- | --- | --- | --- |
| `research` | Research Agent | `get_brand_profile`, `get_research`, `run_research` | Industry, competitor, audience and trend findings with source references |
| `marketing_strategist` | Marketing Strategist Agent | `get_brand_profile`, `get_research`, `get_analytics` | Strategy summary, audience insights, themes, pillars, objectives, content mix, evidence and assumptions |
| `content_planner` | Content Planner Agent | `get_brand_profile`, `get_research` | Content ideas per platform, formats, adaptations, suggested frequency (never schedules) |
| `content_writer` | Content Writer Agent | `get_brand_profile`, `get_research` | Facebook and Instagram versions with hook, body, CTA, hashtags, alternative hooks |
| `brand_guardian` | Brand Guardian Agent | `get_brand_profile` | Advisory brand review: tone, terminology, prohibited phrases, unsupported claims |
| `fact_checker` | Fact-Checker Agent | `get_research` | Claim classification against stored research sources |
| `content_quality` | Content Quality Agent | none | Editorial scores (1–10) with explanations |
| `analytics_strategist` | Analytics Strategist Agent | `get_analytics` | Interpretation of measured analytics, patterns, experiments |

What each agent's `finalize` enforces after schema validation:

- **Research**: sources are shown to the model as `S1`, `S2`… Each cited ref must map to a
  `research_sources` row of the workspace (checked with the Phase 4 `CitationValidationService`).
  Unknown refs are removed with a warning. A finding with no valid source is `verified: false`. With no
  sources at all (for example no search provider configured), every finding is an assumption and the
  output says so.
- **Marketing Strategist**: evidence with basis `research` but no valid source, `analytics` without
  analytics, or `brand_profile` without a brand is relabelled `assumption`.
- **Content Planner**: ideas for platforms that were not requested are dropped; formats are limited to
  the content studio's content types.
- **Content Writer**: exactly one version per requested platform; each must pass
  `ContentStudioService.platform_validation` (Instagram 2,200 characters / 30 hashtags, and so on).
  Prohibited phrases are reported as warnings.
- **Brand Guardian**: prohibited phrases are detected by rule (case-insensitive match against the brand
  voice and policies), not by trusting the model; any high-severity issue makes the assessment
  `major_issues`. The result always carries `human_approval_required: true`.
- **Fact-Checker**: classifications are `SUPPORTED`, `PARTIALLY_SUPPORTED`, `UNSUPPORTED`,
  `CONTRADICTED`, `OPINION`, `UNVERIFIABLE`. `SUPPORTED`, `PARTIALLY_SUPPORTED` and `CONTRADICTED`
  without a valid source reference are downgraded to `UNVERIFIABLE`.
- **Content Quality**: the overall score is the mean of the six criteria, computed in code; a
  disclaimer states that scores are editorial assessments, not performance predictions.
- **Analytics Strategist**: when there are no measured posts the model is not called at all. Otherwise
  every `metric_refs` value must exist in the measured data supplied to the model; others are removed.
  Numbers in the narrative that are not in the data are listed as `unverified_numbers`.

## Tools and permissions

| Tool | Access | What it does |
| --- | --- | --- |
| `get_brand_profile` | read | Phase 2 `BrandContextService` (profile, voice, audiences, pillars, goals, policies) |
| `get_research` | read | Research reports and up to 12 source records of selected research projects |
| `get_content_project` | read | A content project and its drafts; optionally approved content only |
| `get_analytics` | read | Phase 9 content performance in the compact, id-free form used by analytics summaries |
| `run_research` | write | Creates and runs a research project with the Phase 4 engine and search provider |
| `create_content_draft` | write | Creates a `draft` content project through `ContentStudioService` |

Rules:

- A `ToolBox` is built per execution from the agent's allowlist. An unknown tool raises
  `UnknownToolError`; a registered tool outside the allowlist raises `ToolNotAllowedError`. Refused
  calls are never executed.
- The workspace always comes from the workflow row. Every query filters by it, so ids from another
  workspace are "not found" even if they were tampered with after validation.
- Only the Research Agent has `run_research`. **No agent has `create_content_draft`**; it is used only
  by the human "accept" action, with the accepting member as the actor.
- The orchestrator's own context steps use the read tools only.
- A workflow runs with the permissions of the member who started it. If that member leaves the
  workspace or is deactivated, the workflow fails before the next step.

Not available to agents, by design: changing roles, billing or credentials, connecting social accounts,
publishing, scheduling, approving, deleting data, HTTP requests, shell commands, SQL.

## Structured communication

Every step stores one response envelope in `agent_executions.output_data`:

```json
{
  "agent_id": "fact_checker",
  "agent_version": "1.0.0",
  "task_id": "<workflow id>",
  "execution_id": "<execution id>",
  "status": "succeeded",
  "result": { "claims": [], "summary": "", "counts": {}, "citation_coverage": {} },
  "evidence": [{ "type": "research_source", "source_id": "", "research_id": "", "title": "", "url": "", "domain": "" }],
  "warnings": [],
  "errors": [],
  "token_usage": { "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0 },
  "duration_ms": 0,
  "model": "<model id returned by Groq>"
}
```

Agents never read each other's free text. The orchestrator builds the next agent's input from the
validated `result` of earlier steps (`workflows.py`, the `*_input` functions). `agent_messages` records a
`task` and a `result` message per attempt and a `revision_request` per revision round, as an audit trail.

The full JSON Schema of each agent's input and output is returned by
`GET /workspaces/{id}/agents` (`input_schema`, `output_schema`) and defined in `schemas.py`. Unknown keys
in model output are dropped; wrong types, missing required fields and out-of-range values fail validation
and the step is retried.

## Workflows

| Key | Sequence | Deliverable | Human action |
| --- | --- | --- | --- |
| `content_research` | Research → Marketing Strategist → Content Planner → compile | Research findings, audience insights, strategic recommendations, content opportunities, content ideas | Turn an idea into a draft project |
| `social_content` | brand context → research context → Content Planner → Content Writer → Brand Guardian ∥ Fact-Checker ∥ Content Quality → compile | Draft, platform versions, brand review, fact-check report, quality assessment, improvement suggestions | Accept draft, request revision, reject |
| `content_repurposing` | approved source content → Content Planner → Content Writer → Brand Guardian ∥ Content Quality → compile | Facebook and Instagram adaptations, alternative hooks, CTA recommendations, brand consistency | Accept draft, request revision, reject |
| `performance_analysis` | analytics → Analytics Strategist → Marketing Strategist → compile | Performance summary, patterns, opportunities, experiments, metric references | Read; nothing to accept |

`∥` marks steps of one parallel group: they depend only on the writer, not on each other.

Inputs: `task` (required), `brand_id` (required for `social_content`), `research_ids` (up to 5),
`content_project_id` (required for `content_repurposing`; must be approved), `platforms`
(Facebook and/or Instagram), `days` (7–90, performance analysis), `run_new_research`.

### Bounded revisions

After the reviewers, the compile step applies a review gate. A revision is requested when the Brand
Guardian reports a high-severity issue, the Fact-Checker reports an `UNSUPPORTED` or `CONTRADICTED`
claim, or the quality score is below `AGENT_QUALITY_REVISION_THRESHOLD`. The orchestrator then appends
one more round (`writer:r1`, reviewers, `compile:r1`) and gives the writer the previous draft and the
reviewers' findings.

- Automatic rounds are limited by `AGENT_MAX_AUTO_REVISIONS` (default 1).
- All rounds, including those a person requests with feedback, are limited by `AGENT_MAX_REVISIONS`
  (default 3).
- When the limit is reached with issues still open, the workflow finishes and lists them under
  `open_issues` with `revision_limit_reached: true`. It never loops.

## Execution engine

State machine (all state in PostgreSQL):

```
workflow: pending ──claim──▶ running ──▶ succeeded | failed | cancelled
             ▲                  │
             └── retry later ───┘        Groq rate limit or outage, with backoff

step:     pending ─▶ running ─▶ succeeded | failed          others become skipped (failure) or cancelled
```

| Concern | Behaviour |
| --- | --- |
| Dependencies | A step runs when all steps in its `depends_on` succeeded |
| Sequential by default | `AGENT_MAX_PARALLEL_CALLS=1`: even independent reviewers run one at a time, to respect Groq rate limits |
| Parallel execution | With `AGENT_MAX_PARALLEL_CALLS` > 1, steps of one parallel group send their Groq requests concurrently. Database work stays on one thread |
| Timeouts | Each model call is abandoned after `AGENT_STEP_TIMEOUT_SECONDS` (or the agent's own limit); `GROQ_TIMEOUT_SECONDS` bounds the HTTP request |
| Retries | Invalid JSON, missing fields, timeouts and transient Groq errors are retried up to `AGENT_MAX_STEP_ATTEMPTS` per step. Authentication, configuration and request errors are not retried |
| Rate limits | On HTTP 429 the step is not retried immediately. The workflow returns to `pending` with `next_attempt_at` set from Groq's `retry-after` header (or exponential backoff) and the worker picks it up later |
| Call budget | At most `AGENT_MAX_CALLS_PER_WORKFLOW` agent attempts per workflow, retries and revisions included |
| Duration | The workflow fails after `AGENT_MAX_WORKFLOW_SECONDS` (waiting time counts) |
| Cancellation | A queued workflow is cancelled at once. A running one stops before its next step; finished steps keep their results |
| Recovery | The workflow is claimed with a conditional UPDATE and a lease (`AGENT_LEASE_SECONDS`), renewed after each step. If a worker dies, another worker claims it after the lease expires, resets the interrupted step and continues; finished steps are not repeated |
| Workspace limits | `AGENT_MAX_ACTIVE_WORKFLOWS` at once and `AGENT_MAX_WORKFLOWS_PER_HOUR`, plus a per-user request rate limit on start and revise |
| Wake-up | Starting a workflow pushes a Redis wake-up; the worker also polls the database, so a Redis outage only delays work |

Usage is recorded per execution (`token_usage`, `model_name`, `execution_duration_ms`) and summed on
the workflow (`agent_call_count`, `prompt_tokens`, `completion_tokens`, `total_tokens`). Groq reports
tokens, not cost, so no cost is calculated.

## Groq configuration

Agents reuse the existing provider settings: the workspace Groq configuration from **Settings → AI**
if one exists, otherwise `GROQ_API_KEY`, `GROQ_API_BASE_URL` and `GROQ_DEFAULT_MODEL`, with
`GROQ_TIMEOUT_SECONDS`. No other provider is called and there is no fallback: without a working Groq
configuration the first agent step fails with a clear message.

- **Model**: no model id is hardcoded. Agents use the workspace model or `GROQ_DEFAULT_MODEL`;
  `AGENT_GROQ_MODEL` optionally sets a different model for agents only. Choose from the live list
  (Settings → AI → load models, which calls `GET https://api.groq.com/openai/v1/models`) and run
  **Test connection**.
- Groq's model documentation (<https://console.groq.com/docs/models>) was checked on 2026-11-13. It
  listed `llama-3.1-8b-instant`, `llama-3.3-70b-versatile`, `openai/gpt-oss-120b` and
  `openai/gpt-oss-20b` as production text models. This is a dated note, not configuration: models are
  added and retired, so always use the live list. Agents need a model that follows JSON instructions
  reliably; larger models do this better.
- **Rate limits** (<https://console.groq.com/docs/rate-limits>): limits apply per organization in
  requests and tokens per minute and per day; a 429 response carries `retry-after`. Autowok keeps
  requests sequential by default, honours `retry-after`, bounds retries and caps calls per workflow. A
  `social_content` run makes 5 Groq requests, or 9 with one automatic revision.

## Database

Migration `20261113_0011_phase11_agents.py` adds five tables and changes no existing table.

| Table | Purpose |
| --- | --- |
| `agent_settings` | Per-workspace on/off switch for a registered agent (no row = enabled) |
| `agent_workflows` | One workflow run: type, task, validated inputs, status, lease, limits counters, token totals, final output, human review state |
| `agent_workflow_steps` | Planned steps with order, dependencies, parallel group, revision round, status, attempts |
| `agent_executions` | One attempt of one step: input, response envelope, model, tokens, duration, error |
| `agent_messages` | Structured orchestrator ↔ agent messages (audit trail) |

Agent definitions are code, not rows, so there is no `agent_definitions` table. No API key or secret is
stored in these tables. Brand profiles, research text and analytics are not copied into them: agents
read those through tools at run time, and executions store only the agent's validated input and output.
Research usage is still logged in the existing `research_usage_logs`.

## API

All routes are under `/api/v1/workspaces/{workspace_id}` and require a session. Ids outside the
workspace return 404.

| Method | Path | Role | Purpose |
| --- | --- | --- | --- |
| GET | `/agents` | Member | List registered agents with schemas, tools and enabled state |
| GET | `/agents/{agent_key}` | Member | One agent |
| PATCH | `/agents/{agent_key}` | Owner, Admin | Enable or disable an agent in this workspace |
| GET | `/agent-workflows/catalog` | Member | Workflow definitions, agents, limits, Groq and search-provider status |
| POST | `/agent-workflows/plan` | Member | Validate inputs and return the planned execution. Starts nothing |
| POST | `/agent-workflows` | Member | Start a workflow (201) |
| GET | `/agent-workflows` | Member | History with `status`, `workflow_type`, `offset`, `limit` |
| GET | `/agent-workflows/stats` | Member | Counts, agent calls, tokens, recent runs |
| GET | `/agent-workflows/{id}` | Member | Steps, agent outputs, warnings, evidence, final output |
| GET | `/agent-workflows/{id}/progress` | Member | Status and progress only |
| GET | `/agent-workflows/{id}/output` | Member | Final output |
| GET | `/agent-workflows/{id}/executions/{execution_id}` | Member | One agent output |
| POST | `/agent-workflows/{id}/cancel` | Starter, Owner, Admin | Cancel a queued or running workflow |
| POST | `/agent-workflows/{id}/accept` | Member | Save the draft (or one idea, `idea_index`) as a draft content project |
| POST | `/agent-workflows/{id}/revise` | Member | Request one more bounded revision round with feedback |
| POST | `/agent-workflows/{id}/reject` | Member | Reject the output |

Errors: 404 unknown or foreign ids, 409 wrong state or disabled agent, 422 invalid input, 429 workspace
or request limits. State-changing requests need the same `Origin` and `X-CSRF-Protection` header as the
rest of the API. Start, cancel, accept, reject, revise, agent enable/disable and every workflow outcome
are written to the audit log; the starter is notified in-app when a workflow succeeds or fails.

## User interface

| Route | Purpose |
| --- | --- |
| `/dashboard/ai-agents` | Available workflows and agents, usage for the last 30 days, recent executions with status |
| `/dashboard/ai-agents/workflows` | Builder: choose a workflow, enter the task, select brand, research, approved content, platforms; **Review planned execution**, then **Start workflow** |
| `/dashboard/ai-agents/workflows/[workflowId]` | Execution timeline with agent, status, attempts, model, duration, tokens, warnings, errors, evidence and structured output per step; final deliverable; **Accept**, **Request revision**, **Reject**, **Cancel** |
| `/dashboard/ai-agents/history` | All runs with status and workflow filters |
| `/dashboard/ai-agents/settings` | Groq and search-provider status, limits, registered agents with tools; Owners and Admins can switch agents on or off |

The execution view refreshes every few seconds while a workflow is queued or running. Accept, reject and
cancel ask for confirmation. Source links are clickable only when they are `http(s)` URLs.

## Security summary

| Risk | Control |
| --- | --- |
| Cross-workspace access | Workspace taken from the workflow row; all tool queries and API lookups are workspace-scoped; tested with tampered ids |
| Prompt injection from web pages, stored content or earlier agents | Reference material is wrapped in `<untrusted_data>` blocks with a standing rule to treat it as data; outputs are data only and cannot trigger tools or actions |
| Invented sources or metrics | Citations must resolve to stored source rows; metric values must exist in the measured data; unsupported items are removed or relabelled, with warnings |
| Agents bypassing approval | No approve/schedule/publish tool exists; accepted drafts are `draft`; Brand Guardian output is advisory |
| Runaway execution | Limits on attempts, calls, duration, revisions, active workflows and hourly starts; cancellation; lease-based recovery |
| Arbitrary code or agents | Agents, tools and workflows are code registered at import; requests select by key only |
| Secrets | Groq key handling is unchanged (encrypted workspace key or environment); not stored in agent tables, not returned by the API, not placed in prompts |

## Configuration

```dotenv
AGENTS_ENABLED=true
AGENT_GROQ_MODEL=
AGENT_MAX_CALLS_PER_WORKFLOW=24
AGENT_MAX_WORKFLOW_SECONDS=900
AGENT_STEP_TIMEOUT_SECONDS=90
AGENT_MAX_STEP_ATTEMPTS=3
AGENT_MAX_AUTO_REVISIONS=1
AGENT_MAX_REVISIONS=3
AGENT_MAX_PARALLEL_CALLS=1
AGENT_LEASE_SECONDS=300
AGENT_MAX_ACTIVE_WORKFLOWS=3
AGENT_MAX_WORKFLOWS_PER_HOUR=20
AGENT_BACKOFF_BASE_SECONDS=20
AGENT_BACKOFF_MAX_SECONDS=300
AGENT_QUALITY_REVISION_THRESHOLD=6.0
```

Workflows run in the background worker (`python -m app.worker`, Docker service `worker`). Without a
running worker a started workflow stays queued.

## Testing

```powershell
cd backend; .venv\Scripts\python.exe -m pytest tests/test_phase11_agents.py
cd frontend; npx vitest run app/dashboard/ai-agents
```

- `backend/tests/test_phase11_agents.py` (41 tests) covers the registry, orchestration (sequential,
  parallel, dependencies, invalid workflows, failure, retries, rate limits, timeout, cancellation,
  crash recovery, limits), agent output validation (envelope, invalid JSON, missing fields, fabricated
  citations and metrics), the four workflows, human review, tool allowlists, workspace isolation, the
  Groq integration and regressions.
- `backend/tests/agent_helpers.py` provides `FakeGroq`, a scripted model selected by the `AGENT:` header
  of each prompt. The Groq HTTP path is tested with `httpx.MockTransport`. **No test calls the live Groq
  API**, so the suite needs no credentials.
- `frontend/app/dashboard/ai-agents/phase11-agents.test.tsx` (15 tests) covers the five pages and the
  result views.

## Known limitations

- **Live Groq is not verified.** No `GROQ_API_KEY` was configured in the development environment, so
  every run used mocked responses. Prompt quality, JSON reliability and token use with a real model are
  untested.
- **The Phase 4 search provider returns no results.** `ConfiguredSearchProvider.search` validates
  configuration but has no live provider behind it yet. The Research Agent calls it correctly (tested
  with a stubbed provider), but until a real provider exists, new research has no sources and findings
  are labelled as assumptions. Selecting existing research with stored sources works.
- **PostgreSQL and Docker are not verified.** The migration was applied, compared with the models and
  downgraded on SQLite; it was not run on PostgreSQL, and Docker Compose was not started.
- Fact-checking compares claims with stored source snippets (up to 500 characters each, 12 sources). It
  does not fetch or re-read full pages.
- The unverified-number scan flags numbers in analytics narratives; it does not rewrite the text.
- A timed-out Groq request cannot be interrupted mid-flight; its result is discarded and the HTTP
  timeout ends it.
- Parallel calls are limited to model inference. With the default setting everything is sequential.
- Workflow progress is polled; there is no streaming.
- Media metadata, image generation, email delivery and cost estimation are not part of this phase.
- Phase 6's simpler fact-check, critique and scoring endpoints are unchanged and separate from these
  agents.
