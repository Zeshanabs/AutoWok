from __future__ import annotations

from fastapi import APIRouter, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.redis_client import ping_redis

router = APIRouter()
settings = get_settings()


@router.get("/health", status_code=status.HTTP_200_OK)
def health() -> dict:
    return {"status": "ok", "service": settings.app_name, "environment": settings.app_env}


@router.get("/ready", status_code=status.HTTP_200_OK)
def readiness() -> dict:
    checks: dict[str, bool | str] = {"database": False, "redis": False}

    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
        checks["database"] = True
    except SQLAlchemyError:
        checks["database"] = False

    checks["redis"] = ping_redis()

    payload = {
        "status": "ready" if checks["database"] and checks["redis"] else "degraded",
        "service": settings.app_name,
        "dependencies": checks,
    }
    return payload
