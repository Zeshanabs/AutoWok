from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.routes.auth import router as auth_router
from app.api.v1.routes.ai_providers import router as ai_providers_router
from app.api.v1.routes.brands import router as brands_router
from app.api.v1.routes.health import router as health_router
from app.api.v1.routes.groq_providers import router as groq_providers_router
from app.api.v1.routes.social_accounts import router as social_accounts_router
from app.api.v1.routes.workspaces import router as workspaces_router
from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()
logger = configure_logging(settings.log_level)

@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info("Starting %s in %s mode", settings.app_name, settings.app_env)
    yield
    logger.info("Shutting down %s", settings.app_name)


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Autowok authentication, workspace, brand profile, and AI provider configuration API.",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-CSRF-Protection"],
)

app.include_router(health_router, prefix=settings.api_v1_prefix)
app.include_router(auth_router, prefix=settings.api_v1_prefix)
app.include_router(workspaces_router, prefix=settings.api_v1_prefix)
app.include_router(brands_router, prefix=settings.api_v1_prefix)
app.include_router(ai_providers_router, prefix=settings.api_v1_prefix)
app.include_router(groq_providers_router, prefix=settings.api_v1_prefix)
app.include_router(social_accounts_router, prefix=settings.api_v1_prefix)


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


@app.middleware("http")
async def protect_browser_requests(request: Request, call_next):
    response = None
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
        response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if settings.secure_cookies:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.get("/")
def root() -> dict:
    return {"message": "Autowok backend is running."}
