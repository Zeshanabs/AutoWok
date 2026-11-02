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

    model_config = SettingsConfigDict(
        env_file=_ROOT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

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

    @model_validator(mode="after")
    def validate_cookie_security(self) -> "Settings":
        if self.session_cookie_samesite == "none" and not self.secure_cookies:
            raise ValueError("SameSite=None requires secure session cookies.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
