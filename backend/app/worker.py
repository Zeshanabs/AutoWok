"""Autowok background worker.

Run with ``python -m app.worker``. Several worker processes (on one or many
hosts) can run at once: jobs are claimed with atomic database updates, so each
job is processed by exactly one worker at a time.

Each loop iteration:

1. Waits up to ``WORKER_POLL_INTERVAL_SECONDS`` for a Redis wake-up message.
2. Runs the tasks that must come before publishing (the scheduler, which turns
   due scheduled posts into publishing jobs).
3. Publishes due jobs (new, retry-due, or abandoned jobs whose lease expired
   after a crash). Publishing is never queued behind slower work.
4. Runs the remaining periodic tasks (analytics synchronization, automations,
   AI agent workflows) until ``WORKER_TASK_BUDGET_SECONDS`` is used up; tasks
   that did not get a turn go first in the next iteration.

Operations:

* A heartbeat is written to Redis (and optionally to a file for a container
  health check) on every iteration.
* ``SIGTERM``/``SIGINT`` stop the worker after the job in progress; no new job
  is started. A job interrupted by a hard kill is recovered through its lease.
* When the database is unavailable the loop backs off exponentially instead of
  spinning.
* Every job and task runs in its own logging context and is timed.
"""

from __future__ import annotations

import logging
import os
import signal
import time
from pathlib import Path
from typing import Any, Callable
from uuid import UUID

from sqlalchemy.orm import Session as DBSession

from app.core import context, metrics
from app.core.config import get_settings
from app.core.error_reporting import configure_error_reporting, report_error
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.services.publishing.queue import wait_for_publication
from app.services.publishing.service import default_worker_id, due_publication_ids, process_publication

logger = logging.getLogger("autowok.worker")

# Periodic tasks receive a database session and return the number of items handled.
# Optional attributes on a task function:
#   before_publishing = True   run before publishing jobs (the scheduler)
#   min_interval_seconds = N   run at most once every N seconds
PERIODIC_TASKS: list[Callable[[DBSession], int]] = []

_NEVER: Callable[[], bool] = lambda: False  # noqa: E731


def _task_name(task: Any) -> str:
    return getattr(task, "__name__", str(task))


def _run_task(db: DBSession, task: Callable[[DBSession], int], worker_id: str) -> int:
    name = _task_name(task)
    started = time.perf_counter()
    with context.scope(correlation_id=context.new_id(), operation=f"worker.{name}", worker_id=worker_id):
        try:
            handled = task(db)
            metrics.record_worker(f"task_runs:{name}", 1)
            if handled:
                metrics.record_worker(f"task_items:{name}", handled)
            return handled
        except Exception as exc:  # noqa: BLE001 - one task must not stop the others
            db.rollback()
            metrics.record_worker(f"task_failures:{name}", 1)
            report_error("background_job", f"Periodic task {name} failed", exc, task=name)
            return 0
        finally:
            metrics.record_worker(f"task_seconds:{name}", time.perf_counter() - started)


def _due(task: Any, state: dict[str, Any] | None) -> bool:
    interval = getattr(task, "min_interval_seconds", None)
    if state is None or not interval:
        return True
    last = state.setdefault("last_run", {}).get(_task_name(task))
    return last is None or time.monotonic() - last >= interval


def _mark(task: Any, state: dict[str, Any] | None) -> None:
    if state is not None:
        state.setdefault("last_run", {})[_task_name(task)] = time.monotonic()


def run_once(
    session_factory: Callable[[], DBSession] = SessionLocal,
    *,
    worker_id: str,
    hinted_id: str | None = None,
    batch_size: int = 20,
    tasks: list[Callable[[DBSession], int]] | None = None,
    should_stop: Callable[[], bool] = _NEVER,
    task_budget_seconds: float | None = None,
    state: dict[str, Any] | None = None,
) -> int:
    """One worker iteration. ``state`` carries throttling and fairness between
    iterations in the long-running loop; without it every task runs each time."""
    processed = 0
    all_tasks = PERIODIC_TASKS if tasks is None else tasks
    first = [task for task in all_tasks if getattr(task, "before_publishing", False)]
    later = [task for task in all_tasks if not getattr(task, "before_publishing", False)]
    with session_factory() as db:
        for task in first:
            if should_stop():
                return processed
            if _due(task, state):
                processed += _run_task(db, task, worker_id)
                _mark(task, state)

        candidates: list[UUID] = []
        if hinted_id:
            try:
                candidates.append(UUID(hinted_id))
            except ValueError:
                logger.warning("Ignoring malformed queue message.")
        candidates.extend(job_id for job_id in due_publication_ids(db, limit=batch_size) if job_id not in candidates)
        for job_id in candidates:
            if should_stop():
                return processed
            started = time.perf_counter()
            with context.scope(
                correlation_id=context.new_id(), operation="worker.publish", worker_id=worker_id, job_id=str(job_id)
            ):
                try:
                    status = process_publication(db, job_id, worker_id=worker_id)
                except Exception as exc:  # noqa: BLE001
                    db.rollback()
                    metrics.record_worker("publishing:error", 1)
                    report_error("publishing", "Unexpected failure while processing a publishing job", exc)
                    continue
                finally:
                    metrics.record_worker("publishing_seconds", time.perf_counter() - started)
                if status is not None:
                    processed += 1
                    metrics.record_worker(f"publishing:{status}", 1)
                    logger.info("Publishing job finished attempt with status %s", status, extra={"job_status": status})

        if later:
            # Rotate the starting task so a task that ran out of budget goes first next time.
            offset = (state or {}).get("offset", 0) % len(later)
            ordered = later[offset:] + later[:offset]
            deadline = None if task_budget_seconds is None else time.monotonic() + task_budget_seconds
            ran = 0
            for task in ordered:
                if should_stop():
                    break
                if deadline is not None and time.monotonic() >= deadline:
                    logger.info("Task budget used up; remaining periodic tasks run in the next iteration.")
                    break
                ran += 1
                if _due(task, state):
                    processed += _run_task(db, task, worker_id)
                    _mark(task, state)
            if state is not None:
                state["offset"] = (offset + ran) % len(later) if ran < len(later) else 0
    return processed


def beat(worker_id: str, settings: Any) -> None:
    """Record that this worker is alive. Failures are ignored: the heartbeat
    must never stop the work it reports on."""
    from app.services import redis_client as redis_module

    try:
        redis_module.redis_client.set(
            f"{metrics.HEARTBEAT_PREFIX}{worker_id}", str(int(time.time())), ex=settings.worker_heartbeat_ttl_seconds
        )
    except Exception:  # noqa: BLE001
        pass
    if settings.worker_heartbeat_file:
        try:
            Path(settings.worker_heartbeat_file).write_text(str(int(time.time())), encoding="ascii")
        except OSError:
            pass


def healthcheck() -> int:
    """Exit status for a container health check: 0 when the heartbeat file is fresh."""
    settings = get_settings()
    path = settings.worker_heartbeat_file
    if not path:
        return 1
    try:
        age = time.time() - os.path.getmtime(path)
    except OSError:
        return 1
    return 0 if age <= settings.worker_heartbeat_ttl_seconds else 1


def main() -> None:
    settings = get_settings()
    service = "autowok-worker" if settings.service_name == "autowok-api" else settings.service_name
    configure_logging(settings.log_level, json_format=settings.use_json_logs, service=service, environment=settings.app_env)
    configure_error_reporting(settings)
    metrics.SHARE_COUNTERS = True
    from app.services.agents import worker_tasks as agent_tasks
    from app.services.analytics import worker_tasks as analytics_tasks
    from app.services.automation import worker_tasks as automation_tasks
    from app.services.scheduling import worker_tasks

    worker_tasks.register(PERIODIC_TASKS)
    analytics_tasks.register(PERIODIC_TASKS)
    automation_tasks.register(PERIODIC_TASKS)
    agent_tasks.register(PERIODIC_TASKS)

    worker_id = default_worker_id()
    stopping = False

    def stop(*_args: object) -> None:
        nonlocal stopping
        stopping = True
        logger.info("Worker %s received a stop signal; finishing the job in progress.", worker_id)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    logger.info("Autowok worker %s started.", worker_id)
    state: dict[str, Any] = {}
    failures = 0
    should_stop = lambda: stopping  # noqa: E731
    while not stopping:
        beat(worker_id, settings)
        hinted = wait_for_publication(settings.worker_poll_interval_seconds, should_stop=should_stop)
        if stopping:
            break
        started = time.perf_counter()
        try:
            run_once(
                worker_id=worker_id,
                hinted_id=hinted,
                should_stop=should_stop,
                task_budget_seconds=settings.worker_task_budget_seconds,
                state=state,
            )
            failures = 0
            metrics.record_worker("iterations", 1)
            metrics.record_worker("iteration_seconds", time.perf_counter() - started)
        except Exception as exc:  # noqa: BLE001 - keep the worker alive (e.g. database restart)
            failures += 1
            delay = min(60.0, 2.0 ** min(failures, 6))
            report_error("background_job", "Worker iteration failed; backing off", exc, retry_in_seconds=delay)
            end = time.monotonic() + delay
            while not stopping and time.monotonic() < end:
                time.sleep(0.5)
    logger.info("Autowok worker %s stopped.", worker_id)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "healthcheck":
        raise SystemExit(healthcheck())
    main()
