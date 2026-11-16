"""Provider-neutral error reporting.

``report_error`` is the single place where the backend reports an unexpected
failure. It always writes a structured log line and increments a metric. If
``SENTRY_DSN`` is configured and the optional ``sentry-sdk`` package is
installed, the event is also sent there; nothing else in the code base depends
on a monitoring vendor. Local development needs no configuration.

Categories used across the application:
``backend``, ``frontend``, ``background_job``, ``external_api``, ``ai_provider``,
``publishing``, ``analytics_sync``.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from app.core import context, metrics
from app.core.logging import redact

logger = logging.getLogger("autowok.errors")


class ErrorReporter(Protocol):
    def capture(self, *, category: str, message: str, exc: BaseException | None, fields: dict[str, Any]) -> None: ...


class LogReporter:
    """Default reporter: structured log only."""

    def capture(self, *, category: str, message: str, exc: BaseException | None, fields: dict[str, Any]) -> None:
        logger.error(
            message,
            exc_info=(type(exc), exc, exc.__traceback__) if exc is not None else None,
            extra={"error_category": category, **fields},
        )


class SentryReporter(LogReporter):
    """Logs, then forwards to a Sentry-compatible service."""

    def __init__(self, sdk: Any) -> None:
        self._sdk = sdk

    def capture(self, *, category: str, message: str, exc: BaseException | None, fields: dict[str, Any]) -> None:
        super().capture(category=category, message=message, exc=exc, fields=fields)
        try:
            with self._sdk.push_scope() as scope:
                scope.set_tag("error_category", category)
                for key, value in {**context.current(), **fields}.items():
                    scope.set_extra(key, redact(str(value)))
                if exc is not None:
                    self._sdk.capture_exception(exc)
                else:
                    self._sdk.capture_message(redact(message), level="error")
        except Exception:  # noqa: BLE001 - reporting must never raise
            logger.warning("The error could not be sent to the monitoring service.")


_reporter: ErrorReporter = LogReporter()
_status = "log"


def configure_error_reporting(settings: Any) -> str:
    """Select the reporter. Returns "sentry", "log" or "sentry-unavailable"."""
    global _reporter, _status
    _reporter, _status = LogReporter(), "log"
    dsn = (settings.sentry_dsn or "").strip()
    if dsn:
        try:
            import sentry_sdk  # type: ignore[import-not-found]

            sentry_sdk.init(
                dsn=dsn,
                environment=settings.app_env,
                release=settings.release_version or None,
                send_default_pii=False,
                traces_sample_rate=0.0,
                max_request_body_size="never",
            )
            _reporter, _status = SentryReporter(sentry_sdk), "sentry"
        except ImportError:
            _status = "sentry-unavailable"
            logger.warning("SENTRY_DSN is set but sentry-sdk is not installed; errors are logged only.")
    return _status


def reporter_status() -> str:
    return _status


def set_reporter(reporter: ErrorReporter) -> None:
    """Install a custom reporter (another vendor, or a test double)."""
    global _reporter
    _reporter = reporter


def report_error(category: str, message: str, exc: BaseException | None = None, **fields: Any) -> None:
    metrics.ERRORS.labels(category=category).inc()
    metrics.record_worker(f"errors:{category}", 1)
    try:
        _reporter.capture(category=category, message=message, exc=exc, fields=fields)
    except Exception:  # noqa: BLE001
        logger.exception("Error reporter failed.")
