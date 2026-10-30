# Autowok architecture

## Purpose

This document describes the initial architecture for the Phase 0 foundation. It establishes boundaries between the frontend, backend, persistence layers, and infrastructure without implementing product features.

## Components

### Frontend

The frontend is a Next.js application using the App Router. It is responsible for serving the application shell, landing page, environment-based configuration, and future API client logic. In Phase 0, it focuses on a clean, accessible SaaS landing page and an environment-aware backend endpoint foundation.

### Backend

The backend is a FastAPI application that exposes a versioned API under `/api/v1`. It is responsible for configuration validation, structured logging, dependency checks, and future service/domain logic. No authentication or business tables are implemented in this phase.

### Database

PostgreSQL is used as the primary relational database. SQLAlchemy manages connection lifecycle and future session access while Alembic handles migration management. At this stage, the schema is intentionally empty except for the migration foundation.

### Infrastructure

Docker Compose provides PostgreSQL and Redis services plus backend and frontend containers. Persistent storage is mounted under `storage/local` and PostgreSQL uses a named volume so local development data remains available across restarts.

## Communication flow

1. The frontend uses a configured backend base URL for future API calls.
2. The backend validates configuration values on startup.
3. The backend attempts database connectivity via SQLAlchemy and checks Redis availability.
4. The frontend and backend are independently runnable in local development or run together through Docker Compose.
5. Future product modules sit behind the API layer and use the initial DB and service foundations.

## Phase 0 boundaries

The following product areas remain explicitly out of scope for this phase:

- Authentication and user sessions
- Workspace management
- Brand profiles and permissions
- AI workflows and integrations
- Publishing and scheduling
- Analytics and dashboards

## Future extension points

The current structure is designed to evolve into separate modules for:

- API routes and validation
- Database models and migrations
- Service integrations
- Background job infrastructure
- Local and cloud storage adapters
- UI pages and reusable component libraries
