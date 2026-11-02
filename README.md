# Autowok

Autowok is a SaaS platform for brand-aware social media research, content workflows, and publishing automation. Phase 1 adds a tested authentication and workspace foundation to the Phase 0 project skeleton.

## Product vision

The long-term product aims to help teams establish a brand, research topics with trustworthy sources, draft and approve social content, and publish to supported networks such as LinkedIn and X. The initial MVP objective is to support the workflow: brand setup, topic research, content drafting, approval, and publishing to LinkedIn and X.

## Current phase

Phase 1 implementation is in place: account registration and login, opaque cookie sessions, workspace membership and role authorization, audit logging, and the corresponding frontend. PostgreSQL deployment verification remains environment-dependent; use the migration and test commands below before deploying.

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

The Phase 1 schema is managed by Alembic. The Compose backend applies additive migrations before starting; for direct development, apply them explicitly:

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

### Phase 1 API

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

Cookies are set by registration/login; browser mutations must include the CSRF header. In local development, the configured `CORS_ORIGINS` default is `http://localhost:3000`. Set it to the exact frontend origin(s) in deployment. `NEXT_PUBLIC_API_BASE_URL` must point to the FastAPI origin; it contains no secret.

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
- Phase 2: Brand profiles and AI-provider configuration.
- Phase 3: LinkedIn and X account connections using official OAuth APIs.
- Phase 4: Research, source extraction, and citations.
- Phase 5: Content drafts, versions, platform validation, and approval workflows.
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
- Social account integrations
- Publishing workflows
- Scheduling and analytics
- Email verification delivery, password recovery, invitations, MFA, workspace deletion, and ownership transfer

## Preserved Phase 0 behavior

The existing landing page and `/api/v1/health` and `/api/v1/ready` endpoints remain available. The broader Phase 0 environment smoke test should still be run in the target Docker environment.
