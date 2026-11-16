"""Receives runtime errors reported by the browser application.

The endpoint is deliberately small: bounded fields, a per-address rate limit,
and no authentication requirement (errors on the login page matter too). The
report goes to the same error-reporting interface as backend failures.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core import metrics
from app.core.config import get_settings
from app.core.error_reporting import report_error
from app.services.rate_limit import enforce_rate_limit

router = APIRouter(tags=["monitoring"])
settings = get_settings()


class ClientErrorReport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message: str = Field(min_length=1, max_length=500)
    stack: str | None = Field(default=None, max_length=4000)
    source: Literal["error-boundary", "window-error", "unhandled-rejection"]
    digest: str | None = Field(default=None, max_length=100)
    path: str | None = Field(default=None, max_length=300)
    user_agent: str | None = Field(default=None, max_length=300)


@router.post("/client-errors", status_code=status.HTTP_204_NO_CONTENT, include_in_schema=False)
def report_client_error(payload: ClientErrorReport, request: Request) -> Response:
    enforce_rate_limit(
        request,
        action="client-error",
        identity="address",
        limit=settings.rate_limit_client_errors_per_hour,
        window_seconds=3600,
        category="Error reporting",
    )
    metrics.CLIENT_ERRORS.labels(source=payload.source).inc()
    report_error(
        "frontend",
        f"Frontend error: {payload.message}",
        client_source=payload.source,
        client_path=payload.path,
        client_stack=payload.stack,
        client_digest=payload.digest,
        client_user_agent=payload.user_agent,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
