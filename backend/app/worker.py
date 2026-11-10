"""Autowok background worker.

Run with ``python -m app.worker``. Several worker processes (on one or many
hosts) can run at once: jobs are claimed with atomic database updates, so each
job is processed by exactly one worker at a time.

Each loop iteration:
1. Waits up to ``WORKER_POLL_INTERVAL_SECONDS`` for a Redis wake-up message.
2. Runs registered periodic tasks (for example, the scheduler).
3. Processes due jobs found in the database (new, retry-due, or abandoned
   jobs whose lease expired after a crash).
"""

from __future__ import annotations

import logging
import signal
import time
from typing import Callable
from uuid import UUID

from sqlalchemy.orm import Session as DBSession

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.services.publishing.queue import wait_for_publication
from app.services.publishing.service import default_worker_id, due_publication_ids, process_publication

logger = logging.getLogger("autowok.worker")

# Periodic tasks receive a database session and return the number of items handled.
PERIODIC_TASKS: list[Callable[[DBSession], int]] = []


def run_once(
    session_factory: Callable[[], DBSession] = SessionLocal,
    *,
    worker_id: str,
    hinted_id: str | None = None,
    batch_size: int = 20,
    tasks: list[Callable[[DBSession], int]] | None = None,
) -> int:
    processed = 0
    with session_factory() as db:
        for task in PERIODIC_TASKS if tasks is None else tasks:
            try:
                processed += task(db)
            except Exception:  # noqa: BLE001
                logger.exception("Periodic task %s failed", getattr(task, "__name__", task))
                db.rollback()
        candidates: list[UUID] = []
        if hinted_id:
            try:
                candidates.append(UUID(hinted_id))
            except ValueError:
                logger.warning("Ignoring malformed queue message.")
        candidates.extend(job_id for job_id in due_publication_ids(db, limit=batch_size) if job_id not in candidates)
        for job_id in candidates:
            try:
                status = process_publication(db, job_id, worker_id=worker_id)
            except Exception:  # noqa: BLE001
                logger.exception("Unexpected failure while processing job %s", job_id)
                db.rollback()
                continue
            if status is not None:
                processed += 1
                logger.info("Publishing job %s finished attempt with status %s", job_id, status)
    return processed


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    from app.services.scheduling import worker_tasks

    worker_tasks.register(PERIODIC_TASKS)

    worker_id = default_worker_id()
    stopping = False

    def stop(*_args: object) -> None:
        nonlocal stopping
        stopping = True
        logger.info("Worker %s stopping after the current iteration.", worker_id)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    logger.info("Autowok worker %s started.", worker_id)
    while not stopping:
        hinted = wait_for_publication(settings.worker_poll_interval_seconds)
        try:
            run_once(worker_id=worker_id, hinted_id=hinted)
        except Exception:  # noqa: BLE001 - keep the worker alive (e.g. database restart)
            logger.exception("Worker iteration failed; retrying shortly.")
            time.sleep(min(30, settings.worker_poll_interval_seconds))


if __name__ == "__main__":
    main()
