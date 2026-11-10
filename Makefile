.PHONY: up down backend frontend worker tests lint typecheck build docs help

help:
	@echo "Autowok local commands"
	@echo "  make up          Start all stack services with Docker Compose"
	@echo "  make down        Stop services without removing persistent data"
	@echo "  make logs        View logs from all services"
	@echo "  make backend     Start the FastAPI backend directly"
	@echo "  make frontend    Start the Next.js frontend directly"
	@echo "  make worker      Start the publishing/scheduling worker directly"
	@echo "  make tests       Run backend tests"
	@echo "  make lint        Run frontend lint checks"
	@echo "  make typecheck   Run frontend TypeScript checks"
	@echo "  make build       Build the frontend for production"
	@echo "  make migrate     Apply Alembic migrations"
	@echo "  make status      Show repository status"

up:
	docker compose up --build -d

down:
	docker compose down
logs:
	docker compose logs -f
backend:
	cd backend && python -m venv .venv && . .venv/Scripts/activate && pip install -r requirements.txt && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
frontend:
	cd frontend && npm install && npm run dev
worker:
	cd backend && python -m app.worker

tests:
	cd backend && python -m pytest
lint:
	cd frontend && npm run lint

typecheck:
	cd frontend && npx tsc --noEmit
build:
	cd frontend && npm run build
migrate:
	cd backend && alembic upgrade head
status:
	git status --short --branch
