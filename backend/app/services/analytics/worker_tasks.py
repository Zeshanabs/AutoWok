"""Analytics work for the background worker (``python -m app.worker``).

Two periodic tasks run on every worker iteration:

1. ``schedule_analytics_syncs`` creates scheduled jobs for eligible accounts
   whose last job is older than ``ANALYTICS_SYNC_INTERVAL_HOURS``.
2. ``run_analytics_syncs`` claims and processes due jobs (new, retry-due or
   abandoned after a crash). Jobs are claimed atomically, so several workers
   can run at once.
"""

from __future__ import annotations

from typing import Callable

from sqlalchemy.orm import Session as DBSession

from app.core.config import get_settings
from app.services.analytics.sync import run_due_syncs, schedule_due_syncs
from app.services.publishing.service import default_worker_id

_WORKER_ID = default_worker_id()


def schedule_analytics_syncs(db: DBSession) -> int:
    if not get_settings().analytics_enabled:
        return 0
    return schedule_due_syncs(db)


def run_analytics_syncs(db: DBSession) -> int:
    if not get_settings().analytics_enabled:
        return 0
    return run_due_syncs(db, worker_id=_WORKER_ID)


def register(tasks: list[Callable[[DBSession], int]]) -> None:
    for task in (schedule_analytics_syncs, run_analytics_syncs):
        if task not in tasks:
            tasks.append(task)
