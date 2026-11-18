from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, Response

from app.api.v1.routes.agent_workflows import router as agent_workflows_router
from app.api.v1.routes.ai_content import router as ai_content_router
from app.api.v1.routes.auth import router as auth_router
from app.api.v1.routes.automations import router as automations_router
from app.api.v1.routes.ai_providers import router as ai_providers_router
from app.api.v1.routes.analytics import router as analytics_router
from app.api.v1.routes.brands import router as brands_router
from app.api.v1.routes.content import router as content_router
from app.api.v1.routes.health import router as health_router
from app.api.v1.routes.groq_providers import router as groq_providers_router
from app.api.v1.routes.media_assets import router as media_assets_router
from app.api.v1.routes.notifications import router as notifications_router
from app.api.v1.routes.publishing import router as publishing_router
from app.api.v1.routes.research import router as research_router
from app.api.v1.routes.scheduling import router as scheduling_router
from app.api.v1.routes.social_accounts import router as social_accounts_router
from app.api.v1.routes.invitations import router as invitations_router
from app.api.v1.routes.workspaces import router as workspaces_router
from app.api.v1.routes.client_errors import router as client_errors_router
from app.api.v1.routes.health import require_monitoring_token
from app.core import context, metrics
from app.core.config import get_settings
from app.core.error_reporting import configure_error_reporting, report_error
from app.core.http import BodyLimitMiddleware, route_template, security_headers
from app.core.logging import configure_logging
from app.db.session import SessionLocal

settings = get_settings()
logger = configure_logging(
    settings.log_level,
    json_format=settings.use_json_logs,
    service=settings.service_name,
    environment=settings.app_env,
)
access_logger = logging.getLogger("autowok.access")
configure_error_reporting(settings)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info("Starting %s in %s mode", settings.app_name, settings.app_env)
    yield
    logger.info("Shutting down %s", settings.app_name)


app = FastAPI(
    title=settings.app_name,
    version=settings.release_version or "0.1.0",
    description="Autowok workspace, brand, research, content, social account, analytics, automation, AI agent, and AI provider API.",
    # Interactive documentation is a development aid; it is off in production unless API_DOCS_ENABLED=true.
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
    lifespan=lifespan,
)

# Middleware order: the last one added is the outermost. From the outside in:
# request context/metrics/security headers -> trusted hosts -> CORS -> body limit -> routes.
app.add_middleware(BodyLimitMiddleware, settings=settings)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-CSRF-Protection", "Idempotency-Key", "X-Request-ID", "X-Correlation-ID"],
    expose_headers=["X-Request-ID", "Retry-After", "X-Total-Count"],
)
if settings.allowed_hosts_list:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts_list)

app.include_router(health_router, prefix=settings.api_v1_prefix)
app.include_router(auth_router, prefix=settings.api_v1_prefix)
app.include_router(workspaces_router, prefix=settings.api_v1_prefix)
app.include_router(invitations_router, prefix=settings.api_v1_prefix)
app.include_router(brands_router, prefix=settings.api_v1_prefix)
app.include_router(ai_providers_router, prefix=settings.api_v1_prefix)
app.include_router(groq_providers_router, prefix=settings.api_v1_prefix)
app.include_router(research_router, prefix=settings.api_v1_prefix)
app.include_router(content_router, prefix=settings.api_v1_prefix)
app.include_router(ai_content_router, prefix=settings.api_v1_prefix)
app.include_router(media_assets_router, prefix=settings.api_v1_prefix)
app.include_router(publishing_router, prefix=settings.api_v1_prefix)
app.include_router(scheduling_router, prefix=settings.api_v1_prefix)
app.include_router(social_accounts_router, prefix=settings.api_v1_prefix)
app.include_router(analytics_router, prefix=settings.api_v1_prefix)
app.include_router(automations_router, prefix=settings.api_v1_prefix)
app.include_router(notifications_router, prefix=settings.api_v1_prefix)
app.include_router(agent_workflows_router, prefix=settings.api_v1_prefix)
app.include_router(client_errors_router, prefix=settings.api_v1_prefix)


@app.exception_handler(RequestValidationError)
async def validation_error_response(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    errors = [
        {
            "loc": error["loc"],
            "msg": error["msg"],
            "type": error["type"],
        }
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": errors})


@app.exception_handler(Exception)
async def unexpected_error_response(request: Request, exc: Exception) -> JSONResponse:
    """Last resort: report the failure and return a generic message. The request
    id lets support match the response to the log entry; no internals leak."""
    report_error(
        "backend",
        "Unhandled exception while processing a request",
        exc,
        http_method=request.method,
        route=route_template(request),
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An unexpected error occurred. Please try again.",
            "request_id": context.current().get("request_id"),
        },
    )


@app.middleware("http")
async def protect_browser_requests(request: Request, call_next):
    request_id = context.safe_inbound_id(request.headers.get("x-request-id")) or context.new_id()
    correlation_id = context.safe_inbound_id(request.headers.get("x-correlation-id")) or request_id
    started = time.perf_counter()
    with context.scope(request_id=request_id, correlation_id=correlation_id):
        metrics.HTTP_IN_FLIGHT.inc()
        response = None
        try:
            if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                origin = request.headers.get("origin")
                if (
                    origin not in settings.cors_origins_list
                    or request.headers.get("x-csrf-protection") != "1"
                ):
                    response = JSONResponse(
                        status_code=403,
                        content={"detail": "Request origin could not be verified."},
                    )
            if response is None:
                try:
                    response = await call_next(request)
                except Exception as exc:  # noqa: BLE001 - reported, then answered generically
                    response = await unexpected_error_response(request, exc)
        finally:
            metrics.HTTP_IN_FLIGHT.dec()
        elapsed = time.perf_counter() - started
        route = route_template(request)
        metrics.HTTP_REQUESTS.labels(method=request.method, route=route, status=str(response.status_code)).inc()
        metrics.HTTP_LATENCY.labels(method=request.method, route=route).observe(elapsed)
        if route not in {"/api/v1/health", "/api/v1/health/live", "/api/v1/ready", "/metrics"}:
            access_logger.log(
                logging.ERROR if response.status_code >= 500 else logging.INFO,
                "%s %s -> %s",
                request.method,
                route,
                response.status_code,
                extra={
                    "operation": f"{request.method} {route}",
                    "http_status": response.status_code,
                    "duration_ms": round(elapsed * 1000, 1),
                },
            )
        response.headers["X-Request-ID"] = request_id
        for name, value in security_headers(settings, request.url.path).items():
            response.headers.setdefault(name, value)
        return response


@app.get("/metrics", include_in_schema=False, dependencies=[Depends(require_monitoring_token)])
def prometheus_metrics() -> Response:
    """Prometheus scrape endpoint. Not under /api/v1 so the public reverse proxy
    does not route to it; it also requires the monitoring token."""
    if not settings.metrics_enabled:
        return Response(status_code=404)
    with SessionLocal() as db:
        body = metrics.render(db)
    return Response(content=body, media_type="text/plain; version=0.0.4; charset=utf-8")


@app.get("/")
def root() -> dict:
    return {"message": "Autowok backend is running."}
