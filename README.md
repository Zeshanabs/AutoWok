# Autowok

Autowok is a SaaS platform for brand-aware social media research, content workflows, and publishing automation. This repository currently contains Phase 0: project setup, infrastructure foundation, and application skeletons for the backend and frontend.

## Product vision

The long-term product aims to help teams establish a brand, research topics with trustworthy sources, draft and approve social content, and publish to supported networks such as LinkedIn and X. The initial MVP objective is to support the workflow: brand setup, topic research, content drafting, approval, and publishing to LinkedIn and X.

## Current phase

Phase 0 is in progress and focuses on building the technical foundation without implementing authentication, product workflows, or brand-management features.

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
│   │   ├── core/
│   │   ├── db/
│   │   └── services/
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

The backend includes Alembic configuration for future migrations. An empty initial schema is expected while no business tables have been created.

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

## Frontend validation and build commands

```powershell
cd frontend
npm run lint
npx tsc --noEmit
npm run build
```

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
- Phase 1: Authentication, sessions, workspaces, roles, permissions, and audit logging.
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

## Phase 0 exclusions

The following items are intentionally excluded from this phase and will be built in later phases:

- Authentication
- Workspaces and brand management
- AI generation and orchestration
- Social account integrations
- Publishing workflows
- Scheduling and analytics

## Definition of done for Phase 0

This phase is complete only when the environment boots successfully, the backend and frontend start, the health and readiness endpoints respond, database and Redis dependencies are validated, and the documentation reflects the Phase 0 boundaries.
