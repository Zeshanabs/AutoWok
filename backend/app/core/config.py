from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List, Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    app_env: str = Field(default="development", alias="APP_ENV")
    app_name: str = Field(default="Autowok", alias="APP_NAME")
    app_debug: bool = Field(default=False, alias="APP_DEBUG")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    backend_host: str = Field(default="0.0.0.0", alias="BACKEND_HOST")
    backend_port: int = Field(default=8000, alias="BACKEND_PORT")
    api_v1_prefix: str = Field(default="/api/v1", alias="API_V1_PREFIX")
    cors_origins: str = Field(default="http://localhost:3000", alias="CORS_ORIGINS")
    database_url: str = Field(default="postgresql+psycopg://autowok:autowok@localhost:5432/autowok", alias="DATABASE_URL")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    local_storage_path: str = Field(default="./storage/local", alias="LOCAL_STORAGE_PATH")
    session_cookie_name: str = Field(default="autowok_session", alias="SESSION_COOKIE_NAME")
    session_cookie_secure: bool = Field(default=False, alias="SESSION_COOKIE_SECURE")
    session_ttl_days: int = Field(default=30, gt=0, le=365, alias="SESSION_TTL_DAYS")
    session_cookie_samesite: Literal["lax", "strict", "none"] = Field(
        default="lax", alias="SESSION_COOKIE_SAMESITE"
    )
    ai_encryption_key: str = Field(default="", alias="AI_ENCRYPTION_KEY")
    ai_encryption_key_previous: str = Field(default="", alias="AI_ENCRYPTION_KEY_PREVIOUS")
    ai_custom_endpoint_hosts: str = Field(default="", alias="AI_CUSTOM_ENDPOINT_HOSTS")
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    groq_api_base_url: str = Field(
        default="https://api.groq.com/openai/v1", alias="GROQ_API_BASE_URL"
    )
    groq_default_model: str = Field(default="", alias="GROQ_DEFAULT_MODEL")
    groq_timeout_seconds: float = Field(default=60, gt=0, le=300, alias="GROQ_TIMEOUT_SECONDS")
    groq_max_retries: int = Field(default=2, ge=0, le=5, alias="GROQ_MAX_RETRIES")
    groq_enabled: bool = Field(default=True, alias="GROQ_ENABLED")
    research_search_provider: str = Field(default="", alias="RESEARCH_SEARCH_PROVIDER")
    research_search_api_key: str = Field(default="", alias="RESEARCH_SEARCH_API_KEY")
    research_search_base_url: str = Field(default="", alias="RESEARCH_SEARCH_BASE_URL")
    research_max_results: int = Field(default=10, ge=1, le=50, alias="RESEARCH_MAX_RESULTS")
    research_timeout_seconds: int = Field(default=30, ge=1, le=180, alias="RESEARCH_TIMEOUT_SECONDS")
    meta_app_id: str = Field(default="", alias="META_APP_ID")
    meta_app_secret: str = Field(default="", alias="META_APP_SECRET")
    meta_graph_api_version: str = Field(default="v26.0", alias="META_GRAPH_API_VERSION")
    meta_redirect_uri: str = Field(default="", alias="META_REDIRECT_URI")
    meta_oauth_state_secret: str = Field(default="", alias="META_OAUTH_STATE_SECRET")
    meta_token_encryption_key: str = Field(default="", alias="TOKEN_ENCRYPTION_KEY")
    meta_token_encryption_key_previous: str = Field(
        default="", alias="TOKEN_ENCRYPTION_KEY_PREVIOUS"
    )
    meta_webhook_verify_token: str = Field(default="", alias="META_WEBHOOK_VERIFY_TOKEN")
    storage_provider: Literal["local"] = Field(default="local", alias="STORAGE_PROVIDER")
    media_max_image_bytes: int = Field(default=8 * 1024 * 1024, gt=0, alias="MEDIA_MAX_IMAGE_BYTES")
    media_max_video_bytes: int = Field(default=100 * 1024 * 1024, gt=0, alias="MEDIA_MAX_VIDEO_BYTES")
    media_url_signing_secret: str = Field(default="", alias="MEDIA_URL_SIGNING_SECRET")
    media_signed_url_ttl_seconds: int = Field(
        default=3600, ge=60, le=86400, alias="MEDIA_SIGNED_URL_TTL_SECONDS"
    )
    public_media_base_url: str = Field(default="", alias="PUBLIC_MEDIA_BASE_URL")
    publishing_max_attempts: int = Field(default=3, ge=1, le=10, alias="PUBLISHING_MAX_ATTEMPTS")
    publishing_backoff_base_seconds: float = Field(
        default=30, gt=0, le=3600, alias="PUBLISHING_BACKOFF_BASE_SECONDS"
    )
    publishing_backoff_max_seconds: float = Field(
        default=900, gt=0, le=86400, alias="PUBLISHING_BACKOFF_MAX_SECONDS"
    )
    publishing_lease_seconds: int = Field(default=600, ge=30, le=7200, alias="PUBLISHING_LEASE_SECONDS")
    worker_poll_interval_seconds: float = Field(
        default=15, gt=0, le=600, alias="WORKER_POLL_INTERVAL_SECONDS"
    )
    default_timezone: str = Field(default="UTC", alias="DEFAULT_TIMEZONE")
    schedule_min_lead_seconds: int = Field(default=60, ge=0, le=86400, alias="SCHEDULE_MIN_LEAD_SECONDS")
    schedule_max_horizon_days: int = Field(default=365, ge=1, le=1825, alias="SCHEDULE_MAX_HORIZON_DAYS")
    schedule_max_lateness_seconds: int = Field(
        default=6 * 3600, ge=60, le=7 * 86400, alias="SCHEDULE_MAX_LATENESS_SECONDS"
    )
    # Phase 9: analytics synchronization
    analytics_enabled: bool = Field(default=True, alias="ANALYTICS_ENABLED")
    analytics_sync_interval_hours: float = Field(default=12, ge=1, le=168, alias="ANALYTICS_SYNC_INTERVAL_HOURS")
    analytics_initial_lookback_days: int = Field(default=30, ge=1, le=90, alias="ANALYTICS_INITIAL_LOOKBACK_DAYS")
    analytics_incremental_lookback_days: int = Field(
        default=3, ge=1, le=30, alias="ANALYTICS_INCREMENTAL_LOOKBACK_DAYS"
    )
    analytics_post_lookback_days: int = Field(default=90, ge=1, le=730, alias="ANALYTICS_POST_LOOKBACK_DAYS")
    analytics_max_posts_per_sync: int = Field(default=100, ge=1, le=1000, alias="ANALYTICS_MAX_POSTS_PER_SYNC")
    analytics_sync_max_attempts: int = Field(default=3, ge=1, le=10, alias="ANALYTICS_SYNC_MAX_ATTEMPTS")
    analytics_sync_lease_seconds: int = Field(default=900, ge=60, le=7200, alias="ANALYTICS_SYNC_LEASE_SECONDS")
    analytics_manual_refresh_cooldown_minutes: int = Field(
        default=15, ge=0, le=1440, alias="ANALYTICS_MANUAL_REFRESH_COOLDOWN_MINUTES"
    )
    analytics_manual_refresh_limit_per_hour: int = Field(
        default=6, ge=1, le=100, alias="ANALYTICS_MANUAL_REFRESH_LIMIT_PER_HOUR"
    )
    # Phase 10: controlled workflow automations
    automation_enabled: bool = Field(default=True, alias="AUTOMATION_ENABLED")
    automation_max_per_workspace: int = Field(default=50, ge=1, le=1000, alias="AUTOMATION_MAX_PER_WORKSPACE")
    automation_max_actions: int = Field(default=10, ge=1, le=25, alias="AUTOMATION_MAX_ACTIONS")
    automation_max_conditions: int = Field(default=20, ge=1, le=100, alias="AUTOMATION_MAX_CONDITIONS")
    automation_max_condition_depth: int = Field(default=2, ge=1, le=4, alias="AUTOMATION_MAX_CONDITION_DEPTH")
    automation_max_executions_per_hour: int = Field(
        default=60, ge=1, le=10000, alias="AUTOMATION_MAX_EXECUTIONS_PER_HOUR"
    )
    automation_workspace_max_executions_per_day: int = Field(
        default=1000, ge=1, le=100000, alias="AUTOMATION_WORKSPACE_MAX_EXECUTIONS_PER_DAY"
    )
    automation_max_chain_depth: int = Field(default=3, ge=0, le=10, alias="AUTOMATION_MAX_CHAIN_DEPTH")
    automation_max_retries: int = Field(default=3, ge=0, le=10, alias="AUTOMATION_MAX_RETRIES")
    automation_execution_timeout_seconds: int = Field(
        default=60, ge=5, le=3600, alias="AUTOMATION_EXECUTION_TIMEOUT_SECONDS"
    )
    automation_lease_seconds: int = Field(default=300, ge=30, le=7200, alias="AUTOMATION_LEASE_SECONDS")
    automation_max_concurrent_executions: int = Field(
        default=2, ge=1, le=50, alias="AUTOMATION_MAX_CONCURRENT_EXECUTIONS"
    )
    automation_event_max_attempts: int = Field(default=5, ge=1, le=20, alias="AUTOMATION_EVENT_MAX_ATTEMPTS")
    automation_backoff_base_seconds: float = Field(
        default=15, gt=0, le=3600, alias="AUTOMATION_BACKOFF_BASE_SECONDS"
    )
    automation_backoff_max_seconds: float = Field(
        default=600, gt=0, le=86400, alias="AUTOMATION_BACKOFF_MAX_SECONDS"
    )

    model_config = SettingsConfigDict(
        env_file=_ROOT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def ai_custom_endpoint_hosts_list(self) -> list[str]:
        return [
            host.strip().encode("idna").decode("ascii").lower().rstrip(".")
            for host in self.ai_custom_endpoint_hosts.split(",")
            if host.strip()
        ]

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, value: str) -> str:
        origins = [origin.strip() for origin in value.split(",") if origin.strip()]
        if not origins or "*" in origins:
            raise ValueError("CORS_ORIGINS must contain explicit browser origins, not '*'.")
        normalized_origins: list[str] = []
        for origin in origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
                or parsed.username
                or parsed.password
            ):
                raise ValueError(f"Invalid CORS origin: {origin}")
            parsed.port
            normalized_origins.append(
                f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
            )
        return ",".join(normalized_origins)

    @property
    def secure_cookies(self) -> bool:
        return self.session_cookie_secure or self.app_env.lower() in {"production", "prod"}

    @field_validator("groq_api_base_url")
    @classmethod
    def validate_groq_api_base_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "api.groq.com"
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("GROQ_API_BASE_URL must use the official HTTPS Groq API host.")
        return value.rstrip("/")

    @field_validator("meta_graph_api_version")
    @classmethod
    def validate_meta_graph_api_version(cls, value: str) -> str:
        import re

        if not re.fullmatch(r"v\d+\.\d+", value):
            raise ValueError("META_GRAPH_API_VERSION must look like v26.0.")
        return value

    @field_validator("meta_redirect_uri")
    @classmethod
    def validate_meta_redirect_uri(cls, value: str) -> str:
        if not value:
            return value
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"https", "http"}
            or not parsed.hostname
            or (parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1"})
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("META_REDIRECT_URI must be an HTTPS URL (HTTP is allowed for localhost).")
        parsed.port
        return value

    @field_validator("public_media_base_url")
    @classmethod
    def validate_public_media_base_url(cls, value: str) -> str:
        if not value:
            return value
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("PUBLIC_MEDIA_BASE_URL must be a public HTTPS URL.")
        return value.rstrip("/")

    @field_validator("default_timezone")
    @classmethod
    def validate_default_timezone(cls, value: str) -> str:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("DEFAULT_TIMEZONE must be an IANA timezone such as UTC.") from exc
        return value

    @model_validator(mode="after")
    def validate_cookie_security(self) -> "Settings":
        if self.session_cookie_samesite == "none" and not self.secure_cookies:
            raise ValueError("SameSite=None requires secure session cookies.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
