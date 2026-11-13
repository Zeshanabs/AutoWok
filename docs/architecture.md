# Autowok architecture

## Purpose and phase boundary

This document describes the Phase 0 foundation, Phase 1 authentication/workspaces, Phase 2 brand profiles, and Phase 3 Meta/Groq integration foundations. Phase 3 does not include research, content generation workflows, or publishing.

## Components and request flow

### Frontend

The Next.js App Router application provides authentication and workspace management, `/brands`, the two-step `/brands/new` wizard, `/brands/[brandId]` and its `/settings` and voice/audience/pillar/goal/policy sections, `/settings/ai`, `/settings/social-accounts`, and `/settings/security`. A client-side session provider restores the current user from FastAPI when the application loads and protects the authenticated pages. The API client sends credentialed requests and the CSRF marker on state-changing calls. It does not read or persist the HTTP-only session cookie. Provider API keys are held only in the configuration form until submission and are not persisted in browser storage.

Workspace selection is a non-secret preference kept in `sessionStorage`; the API validates membership whenever a selected workspace is requested. This value is not an authorization credential.

### Backend API

FastAPI exposes `/api/v1/auth/*`, `/api/v1/workspaces/*`, brand profile routes, and AI provider configuration routes. Pydantic validates all public request and response data. The backend is authoritative for account authentication, session validity, workspace membership, and role authorization. Inaccessible workspace resources return 404 where appropriate.

Unsafe browser requests must present an exact allowed `Origin` and `X-CSRF-Protection: 1`. Credentialed CORS accepts only the explicit `CORS_ORIGINS` list. Responses include standard framing, content-type, referrer, and permissions headers; HTTPS production responses also include HSTS.

### Database

PostgreSQL is the application database, managed by SQLAlchemy and Alembic. The Phase 1 migration adds:

- `users`: UUID, normalized unique email, Argon2id password hash, account/verification state, and timestamps.
- `workspaces`: UUID, display name, globally unique slug, owner user, and timestamps.
- `workspace_memberships`: UUID, workspace/user foreign keys, `OWNER`/`ADMIN`/`MEMBER` role, membership timestamps, and a unique workspace/user pair.
- `sessions`: UUID, user foreign key, unique SHA-256 token hash, expiry/revocation/use timestamps, and optional user-agent metadata.
- `audit_logs`: nullable workspace/actor references, action/resource identifiers, safe JSON metadata, and creation time.

Database foreign keys, role checks, unique constraints, indexes, and delete behavior are defined in the migration. Account registration creates the account, default personal workspace, owner membership, session, and audit records in one transaction. Workspace creation similarly writes the workspace, owner membership, and audit record together.

The Phase 2 migrations add `brands`, one-to-one `brand_voices`, `target_audiences`, `content_pillars`, `brand_goals`, `brand_policies`, and `ai_provider_configs`. Brand slugs are unique within each workspace. Provider secrets are stored only as Fernet ciphertext; the database enforces at most one default provider per workspace. The Phase 3 migration adds workspace-scoped Meta authorizations, one-time OAuth state, social account metadata, and encrypted social credentials. Brand and provider records are workspace-scoped, and child records cascade with their brand.

### Authentication and sessions

Passwords have a minimum length of 12 and must contain uppercase/lowercase letters, a number, and a symbol. They are hashed using Argon2id (`argon2-cffi`); plaintext credentials are never stored or included in responses or audit metadata.

The API generates an opaque 256-bit session token using Python's cryptographically secure `secrets` module. Only the SHA-256 hash is stored in PostgreSQL. The bearer token is set only as an HTTP-only cookie and is never logged, returned in JSON, or stored in browser JavaScript storage. Sessions expire after `SESSION_TTL_DAYS` (30 by default), are checked on each authenticated request, and can be individually or globally revoked.

Cookie configuration uses `SESSION_COOKIE_NAME`, `SESSION_COOKIE_SECURE`, and `SESSION_COOKIE_SAMESITE`. `Secure` is forced in production; local development can use HTTP. `SameSite=Lax` is the default and `SameSite=None` is accepted only with secure cookies. The frontend calls FastAPI with `credentials: "include"`; configure exact frontend CORS origins and the public `NEXT_PUBLIC_API_BASE_URL` for each environment.

Cookie authentication is protected against CSRF by exact origin checking plus a required non-simple custom header on every unsafe method. Browsers cannot send that header cross-origin without passing the explicit credentialed CORS policy. This is intentionally a small double-check rather than a separate CSRF-token endpoint; non-browser clients must send the configured origin and header too.

Login is limited to 10 attempts per account/IP and 60 per peer IP per 15 minutes; registration is limited to 5 attempts per peer IP per hour using atomic Redis counters. The API fails closed with 503 if Redis is unavailable. Behind a reverse proxy, forwarded client addresses must be configured by trusted infrastructure; arbitrary forwarded headers are not used.

Meta authorization, callback, token refresh, account discovery, connection, and verification operations also use Redis-backed per-user/IP limits and fail closed if Redis is unavailable. Limits are intentionally separate per operation so vendor calls cannot be triggered without bound by a workspace administrator.

### Workspaces and authorization

Every new user owns a personal workspace. Memberships are the basis for access checks. Shared dependencies (`get_current_user`, `get_current_session`, `get_current_workspace`, `require_workspace_member`, and role-specific requirements) centralize authentication and authorization.

- `OWNER`: controls workspace settings and membership; cannot be removed or leave in this phase.
- `ADMIN`: manages regular workspace settings and members, including `ADMIN`/`MEMBER` role changes; cannot change/remove the owner or grant `OWNER`.
- `MEMBER`: can view workspace details and members, but cannot administer them.

Brand reads, context, and provider metadata are available to workspace members. Brand/profile writes, archive operations, provider credentials, and provider tests require `OWNER` or `ADMIN`. Provider records are always queried with workspace scoping. Archived brands remain readable but cannot be changed and are not included in reusable context.

Only registered users can be added; invitations are not implemented. Ownership transfer and workspace deletion are intentionally unavailable. The application rejects owner-removal/role-change operations instead of allowing an ownerless workspace. The workspace owner ID is set at creation and is cross-checked against the owner membership during authorization.

### Audit events

Audit records are created for registration, login, failed login, logout, logout-all, workspace creation/update, member addition/removal, and role changes. Failed-login metadata records only a generic reason and does not include the attempted email/password. Session tokens, password hashes, and authentication payloads are never recorded. There is no user-facing audit mutation API.

Phase 2 adds audit events for brand identity/profile mutations and provider configuration/default/test operations. Phase 3 also audits Meta authorization, social account connect/update/verify/disconnect, and Groq tests. Metadata records changed field names or non-secret status values only; credentials, raw provider responses, and provider error bodies are excluded.

## Brand context and provider credentials

`BrandContextService` authorizes the workspace before loading a brand and returns a versioned, credential-free object containing brand identity, voice, audiences, active content pillars/goals/policies, languages, and restrictions. It does not call an AI provider or perform generation.

`AIProviderConfig` supports OpenAI, Anthropic, Gemini, Groq, and allowlisted OpenAI-compatible endpoints. Groq uses its official OpenAI-compatible endpoint at `https://api.groq.com/openai/v1`; free-tier use is subject to Groq's model-specific limits. `GROQ_API_KEY` can be server-managed or an encrypted workspace key can be configured. Model listing and connection tests make external requests only when explicitly invoked. API keys are encrypted with Fernet using `AI_ENCRYPTION_KEY`; optional previous keys support decryption during rotation.

Meta OAuth stores user and Page credentials encrypted with Fernet using `TOKEN_ENCRYPTION_KEY`. OAuth state is random, stored only as an HMAC digest, bound to the initiating user/workspace, expires after ten minutes, and is consumed once. Owner/Admin authorization is checked at start and callback. Page discovery filters to `MANAGE` or `CREATE_CONTENT` tasks; Instagram discovery accepts only linked `BUSINESS` or `MEDIA_CREATOR` accounts. Meta API calls use the configured Graph version and never expose access tokens in API responses. See [credential storage](./security/token-storage.md) for rotation operations.

Custom endpoints require an exact `AI_CUSTOM_ENDPOINT_HOSTS` entry, HTTPS on port 443, no URL credentials/query/fragment, and public DNS addresses during connection tests. The test transport pins the connection to those validated addresses while retaining TLS hostname verification, preventing DNS rebinding from redirecting the request. Redirects are disabled, requests have a timeout, and response bodies are not returned or logged.

## API surface

All endpoints are under `/api/v1`.

| Method | Path | Authorization |
|---|---|---|
| POST | `/auth/register` | Public; sets session cookie |
| POST | `/auth/login` | Public; sets session cookie |
| GET | `/auth/me` | Current session; optional validated `workspace_id` query |
| POST | `/auth/logout` | Current session |
| POST | `/auth/logout-all` | Current user |
| GET | `/auth/sessions` | Current user |
| DELETE | `/auth/sessions/{session_id}` | Own session only |
| GET, POST | `/workspaces` | Authenticated user; list accessible workspaces or create one |
| GET | `/workspaces/{workspace_id}` | Workspace member |
| PATCH | `/workspaces/{workspace_id}` | Owner or admin |
| GET | `/workspaces/{workspace_id}/members` | Workspace member |
| POST | `/workspaces/{workspace_id}/members` | Owner or admin; existing registered user |
| DELETE | `/workspaces/{workspace_id}/members/{user_id}` | Owner or admin; owner is protected |
| PATCH | `/workspaces/{workspace_id}/members/{user_id}/role` | Owner or admin; ownership transfer rejected |
| GET, POST | `/workspaces/{workspace_id}/brands` | Workspace member / owner or admin |
| GET, PATCH, DELETE | `/brands/{brand_id}` | Workspace member / owner or admin |
| GET | `/brands/{brand_id}/overview` | Workspace member |
| GET, PUT | `/brands/{brand_id}/voice` | Workspace member / owner or admin |
| GET, POST, PATCH, DELETE | `/brands/{brand_id}/{audiences,pillars,goals,policies}[/{id}]` | Read: member; write: owner or admin |
| GET | `/brands/{brand_id}/context` | Workspace member; active brand only |
| GET, POST | `/workspaces/{workspace_id}/ai-providers` | Workspace member / owner or admin |
| GET, PATCH, DELETE | `/workspaces/{workspace_id}/ai-providers/{id}` | Workspace member / owner or admin |
| POST | `/workspaces/{workspace_id}/ai-providers/{id}/test` | Owner or admin; explicitly calls the configured provider |
| GET | `/workspaces/{workspace_id}/ai-providers/groq/status` | Workspace member; reports configuration source only |
| GET | `/workspaces/{workspace_id}/ai-providers/groq/models` | Owner or admin; explicitly fetches Groq models |
| POST | `/workspaces/{workspace_id}/ai-providers/groq/test` | Owner or admin; explicitly tests Groq |
| GET | `/oauth/meta/authorize` and `/oauth/meta/callback` | Owner or admin; starts/finishes one-time Meta OAuth |
| GET, POST | `/workspaces/{workspace_id}/social-accounts/meta/{facebook-pages,instagram-accounts,connect}` | Owner or admin; discovery and connection |
| GET, PATCH, POST | `/workspaces/{workspace_id}/social-accounts[/{id}]` | Read: member; updates, verification, and disconnect: owner or admin |

Phase 9 analytics endpoints are listed in [phase-9-analytics.md](phase-9-analytics.md). Phase 7 and 8 endpoints for media, publishing, scheduling, calendar, queue, and preferences are listed in [phase-7-media-publishing.md](phase-7-media-publishing.md) and [phase-8-scheduling.md](phase-8-scheduling.md). Members can read them; only Owners and Admins can publish or schedule.

## Media, publishing, and scheduling (Phases 7–8)

```
Browser ──▶ API (FastAPI) ──▶ PostgreSQL  ◀── Worker (python -m app.worker)
              │  enqueue id      ▲   │               │ scheduler task: due scheduled_posts → content_publications
              └──────▶ Redis ────┘   │               │ publisher: claim job → Meta Graph API → attempts
                       (wake-up only)└── source of truth (statuses, leases, idempotency keys, guards)
Meta ──GET signed URL──▶ /public-media/{id} (HMAC, expiring) ──▶ StorageBackend (local)
```

- `media_assets` are files in a `StorageBackend`, validated by content. The browser reads them through authenticated endpoints, and Meta reads them through signed, expiring URLs.
- `content_publications` (jobs) and `publishing_attempts` are the only publishing records. Immediate publishing (`source=manual`) and scheduled publishing (`source=schedule`) share them.
- `scheduled_posts` and `scheduling_history` describe *when* to publish. At the due time the scheduler creates a job in the same transaction as the claim.
- Concurrency control comes from conditional `UPDATE`s on status, revision, and lease, unique idempotency keys, and unique `active_guard` columns. Any number of API and worker processes can run.

## Analytics (Phase 9)

```
Worker --schedule_analytics_syncs--> analytics_sync_jobs <-- POST /workspaces/{id}/analytics/sync (Owner/Admin)
Worker --run_analytics_syncs--> claim job --> MetaInsightsCollector --> Meta Graph API (insights, fields, posts)
                                   | normalize through the metric catalogue
                                   v
            analytics_snapshots (account metric per day) . post_analytics (+ post_analytics_history)
                                   ^
            GET /workspaces/{id}/analytics/* -- queries, calculations, CSV/PDF reports --> /dashboard/analytics
```

* Analytics never calls Meta on page load; dashboards read stored snapshots that carry the source metric name, unit, API version and collection time.
* Only metrics documented in Meta's current references are collected (`app/services/analytics/metrics.py`); deprecated impression metrics are excluded and missing values are stored as `NULL`, never 0.
* Facebook and Instagram values are kept separate; cross-platform totals exist only for keys marked comparable, and engagement definitions are shown per platform.
* Sync jobs are claimed with conditional updates, retried with bounded backoff (rate limits honour Meta's `estimated_time_to_regain_access`), and one active job per account is enforced by a unique guard. Manual refreshes are rate limited per user and per account.
* Tokens are decrypted only in the worker and never leave the server. Details: [phase-9-analytics.md](phase-9-analytics.md).

Authentication failures use generic login responses. Inaccessible workspace details and membership lists return 404 to limit resource enumeration.

## Automations (Phase 10)

Phase 10 adds a controlled automation engine (`backend/app/services/automation/`) on top of the existing
worker. Business code records `AutomationEvent` rows in the same transaction as the change they describe
(outbox pattern); the worker dispatches them to enabled `Automation` rules of the same workspace and
trigger type, evaluates a strictly validated JSON condition tree, and creates `AutomationExecution` rows
(unique idempotency key per automation and event). A second worker task claims executions with leases and
runs their allowlisted `AutomationAction`s in order, recording `AutomationExecutionStep` results. Actions
only call existing services: in-app notifications (`notifications`), internal tasks (`content_tasks`),
content assignment and labels (two new metadata columns on `content_projects`), and the Phase 9 analytics
refresh. No action publishes, schedules, approves or edits content; there is no code execution, outbound
HTTP or shell access. Loop protection tags events caused by executions with their origin automation and a
chain depth; per-automation hourly, lifetime, cooldown and concurrency limits plus a workspace daily limit
bound the load. Dry runs evaluate a configuration against sample or recorded events and roll back before
returning a result labelled as simulated. Details: `docs/phase-10-automations.md`.

## Environment and operations

The root `.env.example` documents:

- `CORS_ORIGINS`: explicit comma-separated browser origins.
- `SESSION_COOKIE_NAME`, `SESSION_COOKIE_SECURE`, `SESSION_COOKIE_SAMESITE`, `SESSION_TTL_DAYS`.
- `DATABASE_URL` and `REDIS_URL`.
- `DOCKER_DATABASE_URL` and `DOCKER_REDIS_URL` for backend containers, which must use Compose service names rather than host `localhost`.
- `NEXT_PUBLIC_API_BASE_URL`.
- `AI_ENCRYPTION_KEY` and optional `AI_ENCRYPTION_KEY_PREVIOUS`; never expose these as `NEXT_PUBLIC_*`.
- `AI_CUSTOM_ENDPOINT_HOSTS`: exact allowlisted DNS names for custom provider testing.
- `GROQ_API_KEY`, `GROQ_API_BASE_URL`, `GROQ_DEFAULT_MODEL`, and bounded timeout/retry settings.
- `META_APP_ID`, `META_APP_SECRET`, `META_GRAPH_API_VERSION`, `META_REDIRECT_URI`, and `META_OAUTH_STATE_SECRET`.
- `TOKEN_ENCRYPTION_KEY` and optional `TOKEN_ENCRYPTION_KEY_PREVIOUS` for Meta credentials.
- Phase 7: `STORAGE_PROVIDER`, `MEDIA_MAX_IMAGE_BYTES`, `MEDIA_MAX_VIDEO_BYTES`, `MEDIA_URL_SIGNING_SECRET`, `MEDIA_SIGNED_URL_TTL_SECONDS`, `PUBLIC_MEDIA_BASE_URL`, `PUBLISHING_MAX_ATTEMPTS`, `PUBLISHING_BACKOFF_BASE_SECONDS`, `PUBLISHING_BACKOFF_MAX_SECONDS`, `PUBLISHING_LEASE_SECONDS`, `WORKER_POLL_INTERVAL_SECONDS`.
- Phase 8: `DEFAULT_TIMEZONE`, `SCHEDULE_MIN_LEAD_SECONDS`, `SCHEDULE_MAX_HORIZON_DAYS`, `SCHEDULE_MAX_LATENESS_SECONDS`.
- Phase 10: `AUTOMATION_ENABLED`, `AUTOMATION_MAX_PER_WORKSPACE`, `AUTOMATION_MAX_ACTIONS`, `AUTOMATION_MAX_CONDITIONS`, `AUTOMATION_MAX_CONDITION_DEPTH`, `AUTOMATION_MAX_EXECUTIONS_PER_HOUR`, `AUTOMATION_WORKSPACE_MAX_EXECUTIONS_PER_DAY`, `AUTOMATION_MAX_CHAIN_DEPTH`, `AUTOMATION_MAX_RETRIES`, `AUTOMATION_EXECUTION_TIMEOUT_SECONDS`, `AUTOMATION_LEASE_SECONDS`, `AUTOMATION_MAX_CONCURRENT_EXECUTIONS`, `AUTOMATION_EVENT_MAX_ATTEMPTS`, `AUTOMATION_BACKOFF_BASE_SECONDS`, `AUTOMATION_BACKOFF_MAX_SECONDS`.
- Phase 9: `ANALYTICS_ENABLED`, `ANALYTICS_SYNC_INTERVAL_HOURS`, `ANALYTICS_INITIAL_LOOKBACK_DAYS`, `ANALYTICS_INCREMENTAL_LOOKBACK_DAYS`, `ANALYTICS_POST_LOOKBACK_DAYS`, `ANALYTICS_MAX_POSTS_PER_SYNC`, `ANALYTICS_SYNC_MAX_ATTEMPTS`, `ANALYTICS_SYNC_LEASE_SECONDS`, `ANALYTICS_MANUAL_REFRESH_COOLDOWN_MINUTES`, `ANALYTICS_MANUAL_REFRESH_LIMIT_PER_HOUR`.

Do not commit `.env` or use secrets in public frontend variables. Direct backend startup requires `alembic upgrade head`; the Docker backend applies migrations before starting. Migrations are additive and do not drop Phase 0 data. Run `alembic upgrade head` with the deployment PostgreSQL connection before rollout and verify a backup/restore procedure separately.

## Tests and verification

- Backend: `cd backend; .venv\Scripts\python.exe -m pytest`. Tests override the database with an isolated in-memory SQLite database and mock Redis; they do not touch configured application data.
- Frontend: `cd frontend; npm test`, `npm run lint`, `npx tsc --noEmit`, and `npm run build`.
- Migration: run `alembic upgrade head` against PostgreSQL. Offline SQL compilation and SQLite migration/schema comparison are useful local checks but do not replace PostgreSQL deployment verification.

## Remaining work and trade-offs

Email verification delivery, password recovery, account invitations, MFA, workspace deletion, and ownership transfer are not implemented. Publishing (Phase 7), scheduling (Phase 8) and analytics collection (Phase 9) are implemented but only verified against a mocked Meta API. Automations (Phase 10) have no email action because no email service exists, and their PostgreSQL migration was compiled offline but not applied to a live PostgreSQL instance in the development environment. Phase 3 tests use mocks; real vendor credentials, Meta App Review, and live API calls remain unverified. Apply and verify PostgreSQL migrations in the deployment environment. Session activity metadata stores a bounded user-agent string but exposes only a coarse device label. Authentication rate-limit counters are ephemeral and Redis-backed; a Redis outage blocks authentication rather than disabling protection. Production HTTPS termination, proxy trust, monitoring, backups, and operational key/secret rotation must be configured by the deployment environment.
