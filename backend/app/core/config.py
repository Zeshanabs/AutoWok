from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List, Literal
from urllib.parse import urlsplit

from pydantic import Field, ValidationError, field_validator, model_validator
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
    # Phase 11: multi-agent AI workflows (Groq inference only)
    agents_enabled: bool = Field(default=True, alias="AGENTS_ENABLED")
    # Optional Groq model for agents. Empty = the workspace model or GROQ_DEFAULT_MODEL.
    agent_groq_model: str = Field(default="", alias="AGENT_GROQ_MODEL")
    agent_max_calls_per_workflow: int = Field(default=24, ge=1, le=200, alias="AGENT_MAX_CALLS_PER_WORKFLOW")
    agent_max_workflow_seconds: int = Field(default=900, ge=30, le=7200, alias="AGENT_MAX_WORKFLOW_SECONDS")
    agent_step_timeout_seconds: int = Field(default=90, ge=5, le=600, alias="AGENT_STEP_TIMEOUT_SECONDS")
    agent_max_step_attempts: int = Field(default=3, ge=1, le=6, alias="AGENT_MAX_STEP_ATTEMPTS")
    agent_max_auto_revisions: int = Field(default=1, ge=0, le=3, alias="AGENT_MAX_AUTO_REVISIONS")
    agent_max_revisions: int = Field(default=3, ge=0, le=10, alias="AGENT_MAX_REVISIONS")
    # 1 = independent agents still run one after another (kindest to Groq rate limits).
    agent_max_parallel_calls: int = Field(default=1, ge=1, le=4, alias="AGENT_MAX_PARALLEL_CALLS")
    agent_lease_seconds: int = Field(default=300, ge=30, le=7200, alias="AGENT_LEASE_SECONDS")
    agent_max_active_workflows: int = Field(default=3, ge=1, le=50, alias="AGENT_MAX_ACTIVE_WORKFLOWS")
    agent_max_workflows_per_hour: int = Field(default=20, ge=1, le=1000, alias="AGENT_MAX_WORKFLOWS_PER_HOUR")
    agent_backoff_base_seconds: float = Field(default=20, gt=0, le=3600, alias="AGENT_BACKOFF_BASE_SECONDS")
    agent_backoff_max_seconds: float = Field(default=300, gt=0, le=3600, alias="AGENT_BACKOFF_MAX_SECONDS")
    agent_quality_revision_threshold: float = Field(
        default=6.0, ge=1, le=10, alias="AGENT_QUALITY_REVISION_THRESHOLD"
    )

    # Phase 12: production operations ------------------------------------------------
    service_name: str = Field(default="autowok-api", alias="SERVICE_NAME")
    # "auto" = JSON in production, readable text elsewhere.
    log_format: Literal["auto", "json", "text"] = Field(default="auto", alias="LOG_FORMAT")
    # API documentation (/docs, /redoc, /openapi.json). Unset = on outside production, off in production.
    api_docs_enabled: bool | None = Field(default=None, alias="API_DOCS_ENABLED")
    # Comma-separated Host header allowlist; empty disables the check (the reverse proxy should enforce it).
    allowed_hosts: str = Field(default="", alias="ALLOWED_HOSTS")
    # Database connection pool (per process)
    db_pool_size: int = Field(default=5, ge=1, le=100, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=10, ge=0, le=200, alias="DB_MAX_OVERFLOW")
    db_pool_timeout_seconds: float = Field(default=30, gt=0, le=300, alias="DB_POOL_TIMEOUT_SECONDS")
    db_pool_recycle_seconds: int = Field(default=1800, ge=-1, le=86400, alias="DB_POOL_RECYCLE_SECONDS")
    db_connect_timeout_seconds: int = Field(default=5, ge=1, le=120, alias="DB_CONNECT_TIMEOUT_SECONDS")
    # 0 disables the server-side statement timeout.
    db_statement_timeout_ms: int = Field(default=30000, ge=0, le=3600000, alias="DB_STATEMENT_TIMEOUT_MS")
    redis_socket_timeout_seconds: float = Field(default=5, gt=0, le=120, alias="REDIS_SOCKET_TIMEOUT_SECONDS")
    # Sessions: how often last_used_at is written (0 = every request).
    session_touch_interval_seconds: int = Field(default=300, ge=0, le=86400, alias="SESSION_TOUCH_INTERVAL_SECONDS")
    # Request bodies other than media uploads
    max_request_body_bytes: int = Field(default=1024 * 1024, ge=1024, alias="MAX_REQUEST_BODY_BYTES")
    upload_max_concurrent: int = Field(default=4, ge=1, le=64, alias="UPLOAD_MAX_CONCURRENT")
    # Monitoring
    metrics_enabled: bool = Field(default=True, alias="METRICS_ENABLED")
    # Bearer token required by /metrics and /api/v1/health/details. Required in production when metrics are on.
    metrics_token: str = Field(default="", alias="METRICS_TOKEN")
    # Optional Sentry-compatible DSN. Empty = errors are reported to the structured log only.
    sentry_dsn: str = Field(default="", alias="SENTRY_DSN")
    release_version: str = Field(default="", alias="RELEASE_VERSION")
    # Worker
    worker_heartbeat_file: str = Field(default="", alias="WORKER_HEARTBEAT_FILE")
    worker_heartbeat_ttl_seconds: int = Field(default=120, ge=15, le=3600, alias="WORKER_HEARTBEAT_TTL_SECONDS")
    # Periodic tasks stop starting new work after this many seconds in one loop, so due posts are not delayed.
    worker_task_budget_seconds: float = Field(default=120, ge=5, le=3600, alias="WORKER_TASK_BUDGET_SECONDS")
    worker_housekeeping_interval_seconds: float = Field(
        default=60, ge=1, le=3600, alias="WORKER_HOUSEKEEPING_INTERVAL_SECONDS"
    )
    # Rate limits, per user and per hour unless the name says otherwise.
    rate_limit_login_per_account_15m: int = Field(default=20, ge=1, le=1000, alias="RATE_LIMIT_LOGIN_PER_ACCOUNT_15M")
    rate_limit_ai_generate_per_hour: int = Field(default=30, ge=1, le=10000, alias="RATE_LIMIT_AI_GENERATE_PER_HOUR")
    rate_limit_ai_tools_per_hour: int = Field(default=120, ge=1, le=10000, alias="RATE_LIMIT_AI_TOOLS_PER_HOUR")
    rate_limit_research_per_hour: int = Field(default=30, ge=1, le=10000, alias="RATE_LIMIT_RESEARCH_PER_HOUR")
    rate_limit_upload_per_hour: int = Field(default=120, ge=1, le=10000, alias="RATE_LIMIT_UPLOAD_PER_HOUR")
    rate_limit_publish_per_hour: int = Field(default=60, ge=1, le=10000, alias="RATE_LIMIT_PUBLISH_PER_HOUR")
    rate_limit_schedule_per_hour: int = Field(default=240, ge=1, le=10000, alias="RATE_LIMIT_SCHEDULE_PER_HOUR")
    rate_limit_export_per_hour: int = Field(default=30, ge=1, le=10000, alias="RATE_LIMIT_EXPORT_PER_HOUR")
    rate_limit_member_add_per_hour: int = Field(default=20, ge=1, le=10000, alias="RATE_LIMIT_MEMBER_ADD_PER_HOUR")
    rate_limit_provider_test_per_hour: int = Field(default=30, ge=1, le=10000, alias="RATE_LIMIT_PROVIDER_TEST_PER_HOUR")
    rate_limit_automation_test_per_hour: int = Field(
        default=120, ge=1, le=10000, alias="RATE_LIMIT_AUTOMATION_TEST_PER_HOUR"
    )
    rate_limit_client_errors_per_hour: int = Field(default=60, ge=1, le=10000, alias="RATE_LIMIT_CLIENT_ERRORS_PER_HOUR")
    rate_limit_workspace_create_per_day: int = Field(
        default=10, ge=1, le=1000, alias="RATE_LIMIT_WORKSPACE_CREATE_PER_DAY"
    )
    max_workspaces_per_user: int = Field(default=25, ge=1, le=10000, alias="MAX_WORKSPACES_PER_USER")

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
    def is_production(self) -> bool:
        return self.app_env.lower() in {"production", "prod"}

    @property
    def docs_enabled(self) -> bool:
        return (not self.is_production) if self.api_docs_enabled is None else self.api_docs_enabled

    @property
    def use_json_logs(self) -> bool:
        return self.log_format == "json" or (self.log_format == "auto" and self.is_production)

    @property
    def allowed_hosts_list(self) -> list[str]:
        return [host.strip().lower() for host in self.allowed_hosts.split(",") if host.strip()]

    def production_problems(self) -> list[str]:
        """Settings that are unsafe for production. Only names are reported, never values."""
        from cryptography.fernet import Fernet

        def fernet_ok(value: str) -> bool:
            try:
                Fernet(value.strip().encode("ascii"))
                return True
            except (ValueError, UnicodeEncodeError):
                return False

        problems: list[str] = []
        if self.app_debug:
            problems.append("APP_DEBUG must be false")
        try:
            password = urlsplit(self.database_url).password
        except ValueError:
            password = None
        if not password or password in {"autowok", "postgres", "password", "changeme"}:
            problems.append("DATABASE_URL must not use a default or empty password")
        if any(not origin.startswith("https://") for origin in self.cors_origins_list):
            problems.append("CORS_ORIGINS must contain only https:// origins")
        if not fernet_ok(self.ai_encryption_key):
            problems.append("AI_ENCRYPTION_KEY must be a Fernet key")
        if not fernet_ok(self.meta_token_encryption_key):
            problems.append("TOKEN_ENCRYPTION_KEY must be a Fernet key")
        if self.ai_encryption_key.strip() and self.ai_encryption_key.strip() == self.meta_token_encryption_key.strip():
            problems.append("AI_ENCRYPTION_KEY and TOKEN_ENCRYPTION_KEY must be different keys")
        if len(self.media_url_signing_secret.strip()) < 32:
            problems.append("MEDIA_URL_SIGNING_SECRET must be at least 32 characters")
        if self.meta_app_id.strip():
            if not self.meta_app_secret.strip():
                problems.append("META_APP_SECRET is required when META_APP_ID is set")
            if len(self.meta_oauth_state_secret.strip()) < 32:
                problems.append("META_OAUTH_STATE_SECRET must be at least 32 characters")
            if not self.meta_redirect_uri.startswith("https://"):
                problems.append("META_REDIRECT_URI must be an https:// URL")
        if self.metrics_enabled and len(self.metrics_token.strip()) < 24:
            problems.append("METRICS_TOKEN must be at least 24 characters (or set METRICS_ENABLED=false)")
        if self.session_cookie_samesite == "none":
            problems.append("SESSION_COOKIE_SAMESITE must be lax or strict")
        return problems

    @property
    def secure_cookies(self) -> bool:
        return self.session_cookie_secure or self.is_production

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
        if self.agent_lease_seconds <= self.agent_step_timeout_seconds:
            raise ValueError("AGENT_LEASE_SECONDS must be greater than AGENT_STEP_TIMEOUT_SECONDS.")
        if self.is_production:
            problems = self.production_problems()
            if problems:
                # Fail closed: a production process must not start with unsafe configuration.
                raise ValueError("Unsafe production configuration: " + "; ".join(problems) + ".")
        return self


class ConfigurationError(RuntimeError):
    """The environment configuration is invalid. The message names the settings
    and the problem; it never contains a configured value."""


@lru_cache
def get_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        # Pydantic's own message echoes the input values, which include secrets.
        problems = []
        for error in exc.errors(include_input=False, include_url=False, include_context=False):
            location = ".".join(str(part) for part in error.get("loc", ())).upper()
            message = str(error.get("msg", "invalid value")).removeprefix("Value error, ")
            problems.append(f"{location}: {message}" if location else message)
        raise ConfigurationError("Invalid configuration. " + " | ".join(problems)) from None
