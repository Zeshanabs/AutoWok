"""Operational metrics in Prometheus text format.

Labels are low-cardinality and never contain workspace, user or content
identifiers: routes are reported by their template (``/workspaces/{workspace_id}``),
never by the concrete path.

The API process exposes its own in-memory series. The worker is a separate
process without an HTTP port, so it writes its counters to Redis
(``record_worker``) and the API adds them to the scrape (``worker_snapshot``).
Queue depth and failure gauges are computed from the database at scrape time.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

logger = logging.getLogger("autowok.metrics")

REGISTRY = CollectorRegistry()
_LATENCY_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60)

HTTP_REQUESTS = Counter(
    "autowok_http_requests_total", "API requests", ["method", "route", "status"], registry=REGISTRY
)
HTTP_LATENCY = Histogram(
    "autowok_http_request_duration_seconds", "API response time", ["method", "route"],
    buckets=_LATENCY_BUCKETS, registry=REGISTRY,
)
HTTP_IN_FLIGHT = Gauge("autowok_http_requests_in_flight", "Requests being handled", registry=REGISTRY)
RATE_LIMITED = Counter("autowok_rate_limited_total", "Requests rejected by a rate limit", ["action"], registry=REGISTRY)
ERRORS = Counter("autowok_errors_total", "Reported errors", ["category"], registry=REGISTRY)
CLIENT_ERRORS = Counter("autowok_client_errors_total", "Frontend runtime errors", ["source"], registry=REGISTRY)
EXTERNAL_CALLS = Counter(
    "autowok_external_requests_total", "Calls to external services", ["service", "outcome"], registry=REGISTRY
)
EXTERNAL_LATENCY = Histogram(
    "autowok_external_request_duration_seconds", "External call time", ["service"],
    buckets=_LATENCY_BUCKETS, registry=REGISTRY,
)
AI_REQUESTS = Counter("autowok_ai_requests_total", "Groq requests", ["operation", "outcome"], registry=REGISTRY)
AI_LATENCY = Histogram(
    "autowok_ai_request_duration_seconds", "Groq response time", ["operation"],
    buckets=_LATENCY_BUCKETS, registry=REGISTRY,
)
AI_TOKENS = Counter("autowok_ai_tokens_total", "Groq tokens used (when reported)", ["kind"], registry=REGISTRY)
DEPENDENCY_UP = Gauge("autowok_dependency_up", "1 when the dependency answers", ["dependency"], registry=REGISTRY)

WORKER_KEY = "autowok:metrics:worker"
# Only the worker process shares counters through Redis (set by app.worker.main).
SHARE_COUNTERS = False
HEARTBEAT_PREFIX = "autowok:worker:heartbeat:"


def observe_external(service: str, outcome: str, seconds: float) -> None:
    EXTERNAL_CALLS.labels(service=service, outcome=outcome).inc()
    EXTERNAL_LATENCY.labels(service=service).observe(seconds)
    record_worker(f"external:{service}:{outcome}", 1)


def observe_ai(operation: str, outcome: str, seconds: float, usage: dict[str, Any] | None = None) -> None:
    AI_REQUESTS.labels(operation=operation, outcome=outcome).inc()
    AI_LATENCY.labels(operation=operation).observe(seconds)
    record_worker(f"ai:{outcome}", 1)
    record_worker("ai_seconds", seconds)
    for kind, key in (("prompt", "prompt_tokens"), ("completion", "completion_tokens")):
        value = (usage or {}).get(key)
        if isinstance(value, (int, float)) and value > 0:
            AI_TOKENS.labels(kind=kind).inc(value)
            record_worker(f"ai_tokens:{kind}", value)


def record_worker(field: str, amount: float = 1) -> None:
    """Add to a counter shared through Redis. Never raises: metrics must not break work."""
    if not SHARE_COUNTERS:
        return
    from app.services import redis_client as redis_module

    try:
        redis_module.redis_client.hincrbyfloat(WORKER_KEY, field, amount)
    except Exception:  # noqa: BLE001
        pass


def worker_snapshot() -> dict[str, float]:
    from app.services import redis_client as redis_module

    try:
        raw = redis_module.redis_client.hgetall(WORKER_KEY) or {}
        return {str(key): float(value) for key, value in raw.items()}
    except Exception:  # noqa: BLE001
        return {}


def live_workers() -> int | None:
    """Number of workers with a fresh heartbeat, or None when Redis cannot be asked."""
    from app.services import redis_client as redis_module

    try:
        return sum(1 for _ in redis_module.redis_client.scan_iter(match=f"{HEARTBEAT_PREFIX}*", count=100))
    except Exception:  # noqa: BLE001
        return None


def _line(name: str, value: float, labels: dict[str, str] | None = None) -> str:
    rendered = ",".join(f'{key}="{val}"' for key, val in (labels or {}).items())
    return f"{name}{{{rendered}}} {value}" if rendered else f"{name} {value}"


def _database_lines(db) -> list[str]:
    """Queue depth, failures and sync status, aggregated over all workspaces."""
    from sqlalchemy import func

    from app.models import (
        AgentWorkflow,
        AnalyticsSyncJob,
        AutomationEvent,
        AutomationExecution,
        ContentPublication,
        ScheduledPost,
    )

    lines: list[str] = []
    queues = {
        "publishing": (ContentPublication, ("pending", "processing", "publishing"), ("failed",)),
        "scheduled_posts": (ScheduledPost, ("scheduled", "queued", "processing"), ("failed",)),
        "analytics_sync": (AnalyticsSyncJob, ("pending", "running"), ("failed",)),
        "automation_events": (AutomationEvent, ("pending", "processing"), ("failed",)),
        "automation_executions": (AutomationExecution, ("pending", "running"), ("failed",)),
        "agent_workflows": (AgentWorkflow, ("pending", "running"), ("failed",)),
    }
    lines.append("# HELP autowok_queue_depth Jobs waiting or in progress, per queue")
    lines.append("# TYPE autowok_queue_depth gauge")
    failed_lines = [
        "# HELP autowok_jobs_by_status Jobs per queue and status (all time)",
        "# TYPE autowok_jobs_by_status gauge",
    ]
    for queue, (model, active, _failed) in queues.items():
        counts = dict(db.query(model.status, func.count()).group_by(model.status).all())
        lines.append(_line("autowok_queue_depth", sum(counts.get(status, 0) for status in active), {"queue": queue}))
        for status, count in sorted(counts.items()):
            failed_lines.append(_line("autowok_jobs_by_status", count, {"queue": queue, "status": str(status)}))
    lines.extend(failed_lines)
    last_sync = db.query(func.max(AnalyticsSyncJob.completed_at)).filter(AnalyticsSyncJob.status == "succeeded").scalar()
    if last_sync is not None:
        lines.append("# HELP autowok_analytics_last_success_timestamp_seconds Last successful analytics synchronization")
        lines.append("# TYPE autowok_analytics_last_success_timestamp_seconds gauge")
        lines.append(_line("autowok_analytics_last_success_timestamp_seconds", last_sync.timestamp()))
    return lines


_cache: dict[str, Any] = {"at": 0.0, "lines": []}


def render(db=None, *, cache_seconds: float = 10) -> bytes:
    """The full scrape: process metrics, worker counters and database gauges."""
    lines: list[str] = []
    if db is not None:
        now = time.monotonic()
        if now - _cache["at"] > cache_seconds:
            try:
                _cache["lines"] = _database_lines(db)
                _cache["at"] = now
                DEPENDENCY_UP.labels(dependency="database").set(1)
            except Exception:  # noqa: BLE001
                logger.warning("Database metrics could not be collected.")
                db.rollback()
                _cache["lines"] = []
                DEPENDENCY_UP.labels(dependency="database").set(0)
        lines.extend(_cache["lines"])
    workers = live_workers()
    DEPENDENCY_UP.labels(dependency="redis").set(0 if workers is None else 1)
    lines.append("# HELP autowok_workers_alive Workers with a fresh heartbeat")
    lines.append("# TYPE autowok_workers_alive gauge")
    lines.append(_line("autowok_workers_alive", workers or 0))
    snapshot = worker_snapshot()
    if snapshot:
        lines.append("# HELP autowok_worker_counter_total Counters reported by worker processes")
        lines.append("# TYPE autowok_worker_counter_total counter")
        for field, value in sorted(snapshot.items()):
            safe = field.replace('"', "").replace("\\", "")
            lines.append(_line("autowok_worker_counter_total", value, {"name": safe}))
    return generate_latest(REGISTRY) + ("\n".join(lines) + "\n").encode("utf-8")
