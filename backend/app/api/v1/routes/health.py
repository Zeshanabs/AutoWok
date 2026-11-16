"""Health endpoints.

* ``GET /health`` and ``GET /health/live`` - liveness: the process answers. No
  dependency is touched, so an orchestrator does not restart the API because
  the database is briefly unavailable.
* ``GET /ready`` - readiness: 200 only when the database and Redis answer,
  otherwise 503 so a load balancer stops routing to this instance.
* ``GET /health/details`` - per-dependency detail, including background-worker
  availability and whether external providers are configured. Requires the
  monitoring token.

No endpoint returns credentials, connection strings, host names or versions.
"""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session as DBSession

from app.core import metrics
from app.core.config import get_settings
from app.core.error_reporting import reporter_status
from app.db.session import get_db
from app.services.redis_client import ping_redis

router = APIRouter()
settings = get_settings()


def require_monitoring_token(request: Request) -> None:
    """Bearer token check for monitoring endpoints. Open only in non-production
    environments that have not configured a token."""
    expected = settings.metrics_token.strip()
    if not expected:
        if settings.is_production:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
        return
    supplied = request.headers.get("authorization", "")
    scheme, _, token = supplied.partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token.strip().encode(), expected.encode()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Monitoring token required.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _database_ok(db: DBSession) -> bool:
    try:
        db.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        db.rollback()
        return False


@router.get("/health", status_code=status.HTTP_200_OK)
@router.get("/health/live", status_code=status.HTTP_200_OK, include_in_schema=False)
def health() -> dict:
    return {"status": "ok", "service": settings.app_name}


@router.get("/ready")
def readiness(db: DBSession = Depends(get_db)) -> JSONResponse:
    checks = {"database": _database_ok(db), "redis": ping_redis()}
    ready = all(checks.values())
    for name, ok in checks.items():
        metrics.DEPENDENCY_UP.labels(dependency=name).set(1 if ok else 0)
    return JSONResponse(
        status_code=status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"status": "ready" if ready else "degraded", "service": settings.app_name, "dependencies": checks},
    )


@router.get("/health/details", dependencies=[Depends(require_monitoring_token)])
def health_details(db: DBSession = Depends(get_db)) -> dict:
    workers = metrics.live_workers()
    return {
        "status": "ok",
        "dependencies": {"database": _database_ok(db), "redis": ping_redis()},
        "worker": {"alive": workers or 0, "available": bool(workers)},
        # Configuration presence only: no outbound request is made and no value is returned.
        "external": {
            "groq_configured": bool(settings.groq_api_key.strip()) and settings.groq_enabled,
            "meta_configured": bool(settings.meta_app_id.strip() and settings.meta_app_secret.strip()),
            "public_media_url_configured": bool(settings.public_media_base_url),
        },
        "error_reporting": reporter_status(),
    }
