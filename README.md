# Autowok

Autowok is a SaaS platform for brand-aware social media research, content workflows, and publishing automation. Phases 1 and 2 provide authentication/workspaces, brand profiles, and encrypted AI provider configuration. Phase 3 adds Meta OAuth foundations for Facebook Pages and linked Instagram Professional accounts, plus Groq model discovery and explicit connection tests.

## Product vision

The long-term product aims to help teams establish a brand, research topics with trustworthy sources, draft and approve social content, and publish to supported networks such as LinkedIn and X. The initial MVP objective is to support the workflow: brand setup, topic research, content drafting, approval, and publishing to LinkedIn and X.

## Current phase

Phases 1–4 provide authentication and workspaces, brand profiles and encrypted AI provider configuration, Meta/Groq integration foundations, and research reports with source citations. Phase 5 adds content projects and drafts, immutable draft versions, platform validation, and workspace approval workflows. Automated tests use mocked or local dependencies; live vendor behavior and Meta App Review remain unverified without provider credentials.

## Technology stack

- Frontend: Next.js, React, TypeScript, Tailwind CSS, ESLint
- Backend: Python, FastAPI, Pydantic, SQLAlchemy, Alembic, Pytest
- Infrastructure: PostgreSQL, Redis, Docker Compose, GitHub Actions

## Architecture overview

The project is intentionally separated into independent layers:

- Frontend: customer-facing Next.js application shell and UI foundation
- Backend: FastAPI application, validation, routing, shared services, and health checks
- Database: PostgreSQL with SQLAlchemy session management and Alembic migrations
- Infrastructure: Docker Compose and persistent storage for local development

## Folder structure

```text
autowok/
├── .github/
│   └── workflows/
│       └── ci.yml
├── backend/
│   ├── alembic/
│   ├── app/
│   │   ├── api/
│   │   │   └── v1/
│   │   │       └── routes/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── core/
│   │   ├── db/
│   │   └── services/
│   ├── alembic/versions/
│   ├── tests/
│   ├── alembic.ini
│   ├── Dockerfile
│   ├── main.py
│   ├── pyproject.toml
│   └── requirements.txt
├── docs/
│   └── architecture.md
├── frontend/
│   ├── app/
│   ├── components/
│   ├── lib/
│   ├── public/
│   ├── Dockerfile
│   ├── next.config.ts
│   ├── package.json
│   ├── postcss.config.mjs
│   ├── tsconfig.json
│   └── eslint.config.mjs
├── infrastructure/
│   ├── docker/
│   └── storage/
├── scripts/
├── storage/
│   └── local/
├── .dockerignore
├── .env.example
├── .gitignore
├── docker-compose.yml
├── Makefile
├── README.md
└── .git
```

## Prerequisites

- Node.js 20+ and npm
- Python 3.12+
- Git
- Docker Desktop or Docker Engine (optional for local compose-based startup)

## Local environment setup

1. Create a copy of the root `.env.example` file named `.env`.
2. Sanitize values for the current local environment if needed.
3. Install the frontend dependencies with `npm install` inside `frontend/`.
4. Create a Python virtual environment in `backend/.venv` and install the backend requirements.

Example:

```powershell
Copy-Item .env.example .env
cd frontend
npm install
cd ../backend
C:\Users\Zeeshan Abbas\AppData\Local\Programs\Python\Python312\python.exe -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Docker-based startup

Use Docker Compose to run the PostgreSQL, Redis, backend, and frontend services together:

```powershell
docker compose up --build
```

For a detached environment:

```powershell
docker compose up --build -d
```

To stop services without deleting persistent volumes:

```powershell
docker compose down
```

## Direct frontend startup

```powershell
cd frontend
npm install
npm run dev
```

Frontend URL: http://localhost:3000

## Direct backend startup

```powershell
cd backend
C:\Users\Zeeshan Abbas\AppData\Local\Programs\Python\Python312\python.exe -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Backend URL: http://localhost:8000  
API docs: http://localhost:8000/docs  
Health endpoint: http://localhost:8000/health  
Ready endpoint: http://localhost:8000/ready

## Environment configuration

The project uses environment variables from a root `.env` file. The template is located at `.env.example`.

Important rules:

- Do not commit a real `.env` file.
- Never place production credentials in source control.
- Only values marked `NEXT_PUBLIC_` are exposed in the browser.
- The backend should validate required values on startup.

## Database migration instructions

The schema is managed by Alembic. The Compose backend applies additive migrations before starting; for direct development, apply them explicitly:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
alembic upgrade head
```

## Backend testing commands

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
pytest
```

The API tests use an isolated in-memory SQLite database and a mocked Redis rate limiter. They never connect to the configured development or production database.

## Frontend tests, validation, and build

```powershell
cd frontend
npm run lint
npm test
npx tsc --noEmit
npm run build
```

## Phase 1 authentication and workspace behavior

- Passwords are validated and hashed with Argon2id.
- Login and registration create a cryptographically random opaque session token. Only its SHA-256 hash is stored; the raw token is delivered in an HTTP-only cookie and is never returned in JSON or browser storage.
- Cookies are `SameSite=Lax` by default, `Secure` is configurable for HTTPS, and production mode always enables `Secure`. Set `SESSION_COOKIE_SAMESITE=none` only when cross-site deployment requires it and secure cookies are enabled.
- Unsafe API requests require an allowed `Origin` and the `X-CSRF-Protection: 1` header. The frontend client adds this header and uses credentialed requests. CORS requires explicit origins; wildcard origins are rejected.
- Redis enforces per-account/IP and per-IP login limits plus a per-IP registration limit. Authentication endpoints fail with HTTP 503 rather than silently bypassing rate limits when Redis is unavailable.
- Each new account receives a personal workspace and `OWNER` membership in the same database transaction. Workspace resources are returned only after backend membership checks.
- `OWNER` and `ADMIN` can manage normal workspace settings and membership, and may assign `ADMIN` or `MEMBER`. Neither can grant `OWNER`; ownership transfer is not supported in this phase. Owners cannot be removed. Members can view workspace details and members but cannot manage them.
- Session and workspace operations create audit records with credential-free metadata.

## Phase 2 brand and AI provider behavior

- Brands, voices, audiences, content pillars, goals, and policies are scoped to a workspace.
- `OWNER` and `ADMIN` can manage brand profiles and AI provider configurations; workspace members can read.
- Archived brands remain readable but are read-only and excluded from reusable brand context.
- AI provider credentials are Fernet-encrypted at rest. The API returns only a configured flag and a fixed mask; keys are not recorded in audit data or browser storage.
- Provider connection tests run only after an authorized user explicitly requests them. Phase 2 does not call generation APIs.
- Groq is available through its OpenAI-compatible API endpoint (`https://api.groq.com/openai/v1`). Groq's free tier is subject to model-specific rate limits and availability; do not upgrade or enable paid billing if you want to stay on the free tier.
- Custom OpenAI-compatible endpoints require an operator-controlled exact host allowlist, HTTPS, port 443, and public DNS resolution during tests. The test connection is pinned to the validated IP addresses while TLS verifies the configured hostname.

Set `AI_ENCRYPTION_KEY` in the ignored root `.env` before saving provider credentials. Generate it with:

```powershell
cd backend
.\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Keep the key backed up and stable; saved credentials cannot be decrypted without it. For rotation, deploy the new key as `AI_ENCRYPTION_KEY` and the old key as `AI_ENCRYPTION_KEY_PREVIOUS` while re-encrypting stored credentials. Never use a `NEXT_PUBLIC_` variable for encryption keys.

`AI_CUSTOM_ENDPOINT_HOSTS` is a comma-separated list of exact DNS names permitted for custom endpoints. Leave it empty to disable custom endpoint configuration.

### API endpoints

The API is versioned under `/api/v1`:

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/auth/register` | Register, create a personal workspace, and sign in |
| POST | `/auth/login` | Sign in |
| GET | `/auth/me` | Return the current user, sessions summary, memberships, and optional selected workspace (`?workspace_id=...`) |
| POST | `/auth/logout` | Revoke the current session |
| POST | `/auth/logout-all` | Revoke all active sessions |
| GET | `/auth/sessions` | List the caller's active sessions |
| DELETE | `/auth/sessions/{session_id}` | Revoke one of the caller's sessions |
| GET, POST | `/workspaces` | List accessible workspaces or create a workspace |
| GET, PATCH | `/workspaces/{workspace_id}` | Read or update an accessible workspace |
| GET, POST | `/workspaces/{workspace_id}/members` | List or add registered members |
| DELETE | `/workspaces/{workspace_id}/members/{user_id}` | Remove an authorized member |
| PATCH | `/workspaces/{workspace_id}/members/{user_id}/role` | Change a member's role |
| GET, POST | `/workspaces/{workspace_id}/brands` | List or create workspace brands |
| GET, PATCH, DELETE | `/brands/{brand_id}` | Read, update, or archive an authorized brand |
| GET | `/brands/{brand_id}/overview` | Read the brand and all profile sections |
| GET, PUT | `/brands/{brand_id}/voice` | Read or replace brand voice |
| GET, POST, PATCH, DELETE | `/brands/{brand_id}/{audiences,pillars,goals,policies}[/{id}]` | Manage profile entries |
| GET | `/brands/{brand_id}/context` | Return active, credential-free brand context |
| GET, POST | `/workspaces/{workspace_id}/ai-providers` | List or configure workspace AI providers |
| GET, PATCH, DELETE | `/workspaces/{workspace_id}/ai-providers/{id}` | Read, update, or remove a provider configuration |
| POST | `/workspaces/{workspace_id}/ai-providers/{id}/test` | Explicitly test the saved provider connection |
| GET | `/workspaces/{workspace_id}/ai-providers/groq/status` | Read Groq configuration status without exposing the key |
| GET | `/workspaces/{workspace_id}/ai-providers/groq/models` | Explicitly load available Groq models |
| POST | `/workspaces/{workspace_id}/ai-providers/groq/test` | Explicitly test the configured Groq model |
| GET | `/oauth/meta/authorize` and `/oauth/meta/callback` | Start and complete Meta OAuth |
| GET, POST | `/workspaces/{workspace_id}/social-accounts/meta/{facebook-pages,instagram-accounts,connect}` | Discover and connect eligible Meta accounts |
| GET, PATCH, POST | `/workspaces/{workspace_id}/social-accounts[/{account_id}]` | List, associate, verify, and disconnect workspace accounts |
| GET, POST | `/content/projects` | List or create workspace content projects |
| GET, PATCH, DELETE | `/content/projects/{project_id}` | Read, update, or delete a content project |
| GET, POST | `/content/projects/{project_id}/drafts` | List or create a platform draft |
| PATCH | `/content/projects/{project_id}/drafts/{draft_id}` | Save a draft revision and append a version |
| POST | `/content/projects/{project_id}/drafts/{draft_id}/validate` | Validate platform limits and report warnings |
| GET | `/content/projects/{project_id}/drafts/{draft_id}/versions` | Read immutable draft history |
| POST | `/content/projects/{project_id}/drafts/{draft_id}/versions/{version_id}/restore` | Restore a past version as a new version |
| POST | `/content/projects/{project_id}/submit-for-approval` | Submit all valid project drafts for review |
| GET | `/content/projects/{project_id}/approvals` | Read approval history |
| POST | `/content/projects/{project_id}/approvals/{approval_id}/decision` | Decide as an Owner/Admin |

Cookies are set by registration/login; browser mutations must include the CSRF header. In local development, the configured `CORS_ORIGINS` default is `http://localhost:3000`. Set it to the exact frontend origin(s) in deployment. `NEXT_PUBLIC_API_BASE_URL` must point to the FastAPI origin; it contains no secret.

### Phase 5 content workflow

1. Apply the migration with `alembic upgrade head` or start the backend through Docker Compose so it applies migrations.
2. Open `/dashboard/content`, create a project, and add at least one draft for each selected platform.
3. Save edits to create immutable numbered versions. The version history can restore an earlier snapshot without overwriting history.
4. Run platform validation before submitting. Instagram captions are limited to 2,200 characters and 30 hashtags; Facebook captions are limited to 63,206 characters, with a warning above 10 hashtags.
5. Submit all project drafts for review. Workspace members can submit; only Owners and Admins can approve, reject, or request changes. Approval requests are single-use, and projects cannot be edited while a request is pending.

### Phase 2 manual smoke test

1. Add a private `AI_ENCRYPTION_KEY` to `.env` before configuring a provider; do not commit or expose this value.
2. Apply the migration with `alembic upgrade head` or run `docker compose up --build` to let the backend apply migrations.
3. Open `/brands`, use **Create a brand** to complete the two-step setup, then manage identity from the brand’s **Settings** page and configure voice, audiences, pillars, goals, and policies. Pillars, goals, and policies can be activated or deactivated without deleting them.
4. To use Groq without a paid plan, create an account at [Groq Console](https://console.groq.com), create an API key at [Groq API Keys](https://console.groq.com/keys), and review your model limits. Do not upgrade or add paid billing if you want to remain on the free tier. In Autowok's `/settings/ai`, select **Groq (free tier)**, enter the exact model ID shown as available in your Groq Console, paste the key directly into the password field, and save. Use **Test connection** only when ready to make a real Groq API request; if the free-tier limit is exceeded, wait for the limit to reset.
5. Confirm an `OWNER`/`ADMIN` can manage entries while a `MEMBER` can only view them. Confirm the provider list only shows a masked key.

### Phase 3 manual smoke test

1. Follow [Meta developer setup](docs/meta-developer-setup.md) and [Groq free-tier setup](docs/groq-setup.md). Real Meta credentials/app permissions and a Groq API key are optional for automated tests, but required to exercise live OAuth/model requests.
2. Set `META_APP_ID`, `META_APP_SECRET`, the exact `META_REDIRECT_URI`, a random `META_OAUTH_STATE_SECRET`, and `TOKEN_ENCRYPTION_KEY` in the ignored `.env`. Add the frontend origin to `CORS_ORIGINS`.
3. Configure either a workspace Groq key in `/settings/ai` or server-side `GROQ_API_KEY` and `GROQ_DEFAULT_MODEL`. Use only the Groq Console's currently available models and do not enable paid billing for free-only use.
4. Run `docker compose up --build -d backend frontend`, then verify `docker compose ps` reports healthy services. The backend applies pending migrations at startup.
5. As a workspace Owner/Admin, open `/settings/social-accounts`, authorize Meta, and connect only Pages with the required tasks and linked Instagram Business/Creator accounts. Use verify/disconnect controls and associate the accounts with a workspace brand if desired.
6. In `/settings/ai`, explicitly refresh the Groq model list and test only when ready to make a real vendor request. No user-facing content generation or publishing flow is added in Phase 3.

### Environment variables

In addition to the Phase 0 settings, configure:

- `SESSION_COOKIE_NAME`: Cookie name (`autowok_session` by default).
- `SESSION_COOKIE_SECURE`: Explicit secure-cookie switch (production always enables it).
- `SESSION_COOKIE_SAMESITE`: `lax`, `strict`, or `none`; `none` requires secure cookies.
- `SESSION_TTL_DAYS`: Session lifetime from 1 to 365 days (default 30).
- `CORS_ORIGINS`: Comma-separated explicit frontend origins; `*` is not accepted.
- `REDIS_URL`: Required by the authentication rate-limit service.
- `NEXT_PUBLIC_API_BASE_URL`: Browser-visible FastAPI base URL.
- `DOCKER_DATABASE_URL` and `DOCKER_REDIS_URL`: Compose-network URLs using the `postgres` and `redis` service names. The regular `DATABASE_URL` and `REDIS_URL` remain for direct local startup using `localhost`.
- Groq: `GROQ_API_KEY` (optional server-managed key), `GROQ_API_BASE_URL`, `GROQ_DEFAULT_MODEL`, and bounded timeout/retry settings.
- Meta: `META_APP_ID`, `META_APP_SECRET`, `META_GRAPH_API_VERSION`, `META_REDIRECT_URI`, `META_OAUTH_STATE_SECRET`, `TOKEN_ENCRYPTION_KEY`, and optional `TOKEN_ENCRYPTION_KEY_PREVIOUS`.

Set production secrets and deployment-specific values outside source control. Do not put session tokens or passwords in environment variables or frontend storage.

### Security limitations

Email verification delivery, password recovery, invitations, MFA, ownership transfer, workspace deletion, and refresh-token/JWT infrastructure are deliberately not implemented. Session expiration and revocation are enforced by the API on every authenticated request. Rate limiting uses the direct peer IP; deployments behind reverse proxies should configure trusted proxy handling at the infrastructure boundary rather than trusting arbitrary forwarded headers.

Manual smoke test:

1. Start PostgreSQL and Redis and set the root `.env` to the local values.
2. Run `docker compose up --build`, or apply `alembic upgrade head` from `backend/` before starting FastAPI directly.
3. Open `http://localhost:3000/register`, create an account, and confirm the dashboard shows the new personal workspace and `OWNER` role.
4. Create another registered user, add that user to the workspace from its details page, and test the member/admin controls.
5. In Security settings, verify session listing, single-session revoke, and log out all.
6. Confirm unauthenticated workspace requests return 401 and an authenticated non-member receives 404 for another workspace.

## Troubleshooting

- If Python is not in PATH, use the full path to the interpreter.
- If the database is not ready, the backend ready endpoint will return a degraded status.
- If Docker is unavailable, use the backend and frontend directly with their standalone commands.
- If port 3000 or 8000 is already in use, stop the conflicting service or update the `.env` file values.

## Git initialization and future GitHub connection

This repository was initialized locally with Git. To connect a remote repository later:

```powershell
git remote add origin <your-github-repository-url>
git branch -M main
git push -u origin main
```

Do not connect or push a remote without explicit permission.

## Development roadmap

- Phase 0: Project setup and infrastructure.
- Phase 1: Authentication, sessions, workspaces, roles, permissions, and audit logging (implemented; verify against the deployment PostgreSQL instance).
- Phase 2: Brand profiles and AI-provider configuration (implemented; verify migration against deployment PostgreSQL).
- Phase 3: Meta OAuth for Facebook Pages and linked Instagram Professional accounts, plus Groq provider foundations (implemented; live vendor setup remains environment-dependent).
- Phase 4: Research, source extraction, and citations (implemented; live providers remain environment-dependent).
- Phase 5: Content projects and drafts, version history, platform validation, and approval workflows (implemented).
- Phase 6: AI ideation, writing, repurposing, critique, and fact-checking.
- Phase 7: Studio, media handling, previews, and first publishing workflow.
- Phase 8: Calendar, scheduling, retries, and queue recovery.
- Phase 9: Additional social platforms according to customer demand.
- Phase 10: Analytics, performance insights, and AI usage tracking.
- Phase 11: Controlled workflow automations with approval gates and run history.
- Phase 12: Multi-agent intelligence and advanced research capabilities.
- Phase 13: Optimization, accessibility, monitoring, backups, and advanced features.

## Later-phase exclusions

The following items remain out of scope for Phase 1 and will be built in later phases:

- Brand management
- AI generation and orchestration
- Additional social platforms beyond Meta account connections
- Publishing workflows
- Scheduling and analytics
- Email verification delivery, password recovery, invitations, MFA, workspace deletion, and ownership transfer

## Phase 3 setup and acceptance

- [Phase 3 integration overview](docs/phase-3-integrations.md)
- [Groq free-tier setup](docs/groq-setup.md)
- [Meta developer setup](docs/meta-developer-setup.md)
- [Credential storage and key rotation](docs/security/token-storage.md)

Groq free-tier access and limits are controlled by Groq; do not enable paid billing if you want to remain free-only. Meta access outside test roles requires the applicable Meta review and access approval. The repository's vendor tests are mocked and do not verify real API credentials.

## Preserved Phase 0 behavior

The existing landing page and `/api/v1/health` and `/api/v1/ready` endpoints remain available. The broader Phase 0 environment smoke test should still be run in the target Docker environment.
