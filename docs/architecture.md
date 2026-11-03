# Autowok architecture

## Purpose and phase boundary

This document describes the Phase 0 foundation, Phase 1 authentication/workspaces, and Phase 2 brand profiles and AI-provider configuration. Phase 2 does not include social accounts, research, content generation, or publishing.

## Components and request flow

### Frontend

The Next.js App Router application provides authentication and workspace management, `/brands`, `/brands/[brandId]` and its voice/audience/pillar/goal/policy sections, `/settings/ai`, and `/settings/security`. A client-side session provider restores the current user from FastAPI when the application loads and protects the authenticated pages. The API client sends credentialed requests and the CSRF marker on state-changing calls. It does not read or persist the HTTP-only session cookie. Provider API keys are held only in the configuration form until submission and are not persisted in browser storage.

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

The Phase 2 migration adds `brands`, one-to-one `brand_voices`, `target_audiences`, `content_pillars`, `brand_goals`, `brand_policies`, and `ai_provider_configs`. Brand slugs are unique within each workspace. Provider secrets are stored only as Fernet ciphertext; the database enforces at most one default provider per workspace. Brand and provider records are workspace-scoped, and child records cascade with their brand.

### Authentication and sessions

Passwords have a minimum length of 12 and must contain uppercase/lowercase letters, a number, and a symbol. They are hashed using Argon2id (`argon2-cffi`); plaintext credentials are never stored or included in responses or audit metadata.

The API generates an opaque 256-bit session token using Python's cryptographically secure `secrets` module. Only the SHA-256 hash is stored in PostgreSQL. The bearer token is set only as an HTTP-only cookie and is never logged, returned in JSON, or stored in browser JavaScript storage. Sessions expire after `SESSION_TTL_DAYS` (30 by default), are checked on each authenticated request, and can be individually or globally revoked.

Cookie configuration uses `SESSION_COOKIE_NAME`, `SESSION_COOKIE_SECURE`, and `SESSION_COOKIE_SAMESITE`. `Secure` is forced in production; local development can use HTTP. `SameSite=Lax` is the default and `SameSite=None` is accepted only with secure cookies. The frontend calls FastAPI with `credentials: "include"`; configure exact frontend CORS origins and the public `NEXT_PUBLIC_API_BASE_URL` for each environment.

Cookie authentication is protected against CSRF by exact origin checking plus a required non-simple custom header on every unsafe method. Browsers cannot send that header cross-origin without passing the explicit credentialed CORS policy. This is intentionally a small double-check rather than a separate CSRF-token endpoint; non-browser clients must send the configured origin and header too.

Login is limited to 10 attempts per account/IP and 60 per peer IP per 15 minutes; registration is limited to 5 attempts per peer IP per hour using atomic Redis counters. The API fails closed with 503 if Redis is unavailable. Behind a reverse proxy, forwarded client addresses must be configured by trusted infrastructure; arbitrary forwarded headers are not used.

### Workspaces and authorization

Every new user owns a personal workspace. Memberships are the basis for access checks. Shared dependencies (`get_current_user`, `get_current_session`, `get_current_workspace`, `require_workspace_member`, and role-specific requirements) centralize authentication and authorization.

- `OWNER`: controls workspace settings and membership; cannot be removed or leave in this phase.
- `ADMIN`: manages regular workspace settings and members, including `ADMIN`/`MEMBER` role changes; cannot change/remove the owner or grant `OWNER`.
- `MEMBER`: can view workspace details and members, but cannot administer them.

Brand reads, context, and provider metadata are available to workspace members. Brand/profile writes, archive operations, provider credentials, and provider tests require `OWNER` or `ADMIN`. Provider records are always queried with workspace scoping. Archived brands remain readable but cannot be changed and are not included in reusable context.

Only registered users can be added; invitations are not implemented. Ownership transfer and workspace deletion are intentionally unavailable. The application rejects owner-removal/role-change operations instead of allowing an ownerless workspace. The workspace owner ID is set at creation and is cross-checked against the owner membership during authorization.

### Audit events

Audit records are created for registration, login, failed login, logout, logout-all, workspace creation/update, member addition/removal, and role changes. Failed-login metadata records only a generic reason and does not include the attempted email/password. Session tokens, password hashes, and authentication payloads are never recorded. There is no user-facing audit mutation API.

Phase 2 adds audit events for brand identity/profile mutations and provider configuration/default/test operations. Metadata records changed field names only; provider credentials, raw provider responses, and provider error bodies are excluded.

## Brand context and provider credentials

`BrandContextService` authorizes the workspace before loading a brand and returns a versioned, credential-free object containing brand identity, voice, audiences, active content pillars/goals/policies, languages, and restrictions. It does not call an AI provider or perform generation.

`AIProviderConfig` supports OpenAI, Anthropic, Gemini, and allowlisted OpenAI-compatible endpoints. The API key is encrypted with Fernet using `AI_ENCRYPTION_KEY`; an optional `AI_ENCRYPTION_KEY_PREVIOUS` supports MultiFernet decryption during key rotation. Missing or invalid keys fail closed before a credential can be stored. Responses expose only a configured flag and a fixed mask. No provider request occurs during configuration; an authorized user must explicitly invoke the connection-test endpoint.

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

Authentication failures use generic login responses. Inaccessible workspace details and membership lists return 404 to limit resource enumeration.

## Environment and operations

The root `.env.example` documents:

- `CORS_ORIGINS`: explicit comma-separated browser origins.
- `SESSION_COOKIE_NAME`, `SESSION_COOKIE_SECURE`, `SESSION_COOKIE_SAMESITE`, `SESSION_TTL_DAYS`.
- `DATABASE_URL` and `REDIS_URL`.
- `DOCKER_DATABASE_URL` and `DOCKER_REDIS_URL` for backend containers, which must use Compose service names rather than host `localhost`.
- `NEXT_PUBLIC_API_BASE_URL`.
- `AI_ENCRYPTION_KEY` and optional `AI_ENCRYPTION_KEY_PREVIOUS`; never expose these as `NEXT_PUBLIC_*`.
- `AI_CUSTOM_ENDPOINT_HOSTS`: exact allowlisted DNS names for custom provider testing.

Do not commit `.env` or use secrets in public frontend variables. Direct backend startup requires `alembic upgrade head`; the Docker backend applies migrations before starting. Migrations are additive and do not drop Phase 0 data. Run `alembic upgrade head` with the deployment PostgreSQL connection before rollout and verify a backup/restore procedure separately.

## Tests and verification

- Backend: `cd backend; .venv\Scripts\python.exe -m pytest`. Tests override the database with an isolated in-memory SQLite database and mock Redis; they do not touch configured application data.
- Frontend: `cd frontend; npm test`, `npm run lint`, `npx tsc --noEmit`, and `npm run build`.
- Migration: run `alembic upgrade head` against PostgreSQL. Offline SQL compilation and SQLite migration/schema comparison are useful local checks but do not replace PostgreSQL deployment verification.

## Remaining work and trade-offs

Email verification delivery, password recovery, account invitations, MFA, workspace deletion, ownership transfer, social integrations, research, content generation, and publishing are not implemented. Phase 2 has not been verified against a deployment PostgreSQL database; migration application and schema verification remain required before deployment. Session activity metadata stores a bounded user-agent string but exposes only a coarse device label. Rate-limit counters are ephemeral and Redis-backed; a Redis outage blocks authentication rather than disabling protection. Production HTTPS termination, proxy trust, monitoring, and operational key/secret rotation must be configured by the deployment environment.
