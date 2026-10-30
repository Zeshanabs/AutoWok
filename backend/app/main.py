from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.routes.health import router as health_router
from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()
logger = configure_logging(settings.log_level)

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Autowok backend foundation for Phase 0.",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix=settings.api_v1_prefix)


@app.get("/")
def root() -> dict:
    return {"message": "Autowok backend is running."}


@app.on_event("startup")
def startup_event() -> None:
    logger.info("Starting %s in %s mode", settings.app_name, settings.app_env)


@app.on_event("shutdown")
def shutdown_event() -> None:
    logger.info("Shutting down %s", settings.app_name)
