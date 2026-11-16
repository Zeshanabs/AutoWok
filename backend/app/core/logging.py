"""Structured logging.

Every record carries a timestamp, level, service, environment and the active
request context (request id, correlation id, workspace id, operation). In
production the output is one JSON object per line; elsewhere it is readable
text. A redaction filter masks anything that looks like a credential before a
record is written, so a careless ``logger.info(payload)`` cannot leak a token.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Any

from app.core import context

_STANDARD = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}

_SENSITIVE_KEY = re.compile(
    r"(pass(word|wd)?|secret|token|authorization|api[_-]?key|cookie|credential|signature|encryption[_-]?key|dsn)",
    re.IGNORECASE,
)
_PAIR = re.compile(
    r"(?i)(\"?(?:[a-z0-9_-]*(?:pass(?:word|wd)?|secret|token|authorization|api[_-]?key|cookie|signature)[a-z0-9_-]*)\"?\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|[^\s,&;}\]]+)"
)
_PLAIN_VALUE = re.compile(r"^[\"']?(?:\d+(?:\.\d+)?|true|false|null|none)[\"']?$", re.IGNORECASE)
_REDACTIONS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"), "Bearer [REDACTED]"),
    # OAuth authorization codes in query strings
    (re.compile(r"(?i)([?&]code=)[^&\s]+"), r"\1[REDACTED]"),
    # Groq keys, Meta access tokens, Fernet tokens, connection-string passwords
    (re.compile(r"\bgsk_[A-Za-z0-9]{16,}"), "[REDACTED]"),
    (re.compile(r"\bEAA[A-Za-z0-9]{24,}"), "[REDACTED]"),
    (re.compile(r"\bgAAAAA[A-Za-z0-9_-]{24,}={0,2}"), "[REDACTED]"),
    (re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://[^:/\s@]+:)[^@/\s]+@"), r"\1[REDACTED]@"),
]


def _mask_pair(match: re.Match[str]) -> str:
    # Counters such as tokens_used=123 are not credentials.
    return match.group(0) if _PLAIN_VALUE.match(match.group(2)) else f"{match.group(1)}[REDACTED]"


def redact(text: str) -> str:
    # Token shapes first, so "Authorization: Bearer <token>" cannot leave the token behind.
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return _PAIR.sub(_mask_pair, text)


def _redact_value(key: str, value: Any) -> Any:
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if _SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {str(k): _redact_value(str(k), v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_value(key, item) for item in value]
    return redact(str(value))


class RedactionFilter(logging.Filter):
    """Formats the message once and masks credentials in it."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - a bad format string must not break logging
            message = str(record.msg)
        record.msg = redact(message)
        record.args = None
        return True


class _ContextMixin:
    service: str
    environment: str

    def _fields(self, record: logging.LogRecord) -> dict[str, Any]:
        fields: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "service": self.service,
            "environment": self.environment,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in context.current().items():
            fields[key] = _redact_value(key, value)
        for key, value in record.__dict__.items():
            if key not in _STANDARD and not key.startswith("_"):
                fields[key] = _redact_value(key, value)
        if record.exc_info:
            fields["exception_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
            fields["exception"] = redact(logging.Formatter().formatException(record.exc_info))
        return fields


class JsonFormatter(_ContextMixin, logging.Formatter):
    def __init__(self, service: str, environment: str) -> None:
        super().__init__()
        self.service = service
        self.environment = environment

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(self._fields(record), default=str, ensure_ascii=False)


class TextFormatter(_ContextMixin, logging.Formatter):
    def __init__(self, service: str, environment: str) -> None:
        super().__init__()
        self.service = service
        self.environment = environment

    def format(self, record: logging.LogRecord) -> str:
        fields = self._fields(record)
        head = f"{fields.pop('timestamp')} {fields.pop('level')} {fields.pop('logger')} {fields.pop('message')}"
        exception = fields.pop("exception", None)
        fields.pop("service", None)
        fields.pop("environment", None)
        fields.pop("exception_type", None)
        extras = " ".join(f"{key}={value}" for key, value in fields.items())
        text = f"{head} [{extras}]" if extras else head
        return f"{text}\n{exception}" if exception else text


def configure_logging(
    level: str = "INFO",
    *,
    json_format: bool = False,
    service: str = "autowok-api",
    environment: str = "development",
) -> logging.Logger:
    """Configure the ``autowok`` logger tree. Safe to call more than once."""
    logger = logging.getLogger("autowok")
    logger.setLevel(level.upper())
    logger.propagate = False
    formatter: logging.Formatter = (
        JsonFormatter(service, environment) if json_format else TextFormatter(service, environment)
    )
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.addFilter(RedactionFilter())
        logger.addHandler(handler)
    for handler in logger.handlers:
        handler.setFormatter(formatter)
    # HTTP client libraries log full request URLs at INFO; Meta's OAuth endpoints
    # carry secrets in the query string, so keep them at WARNING.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return logger
