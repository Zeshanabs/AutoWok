"""Scheduling work for the background worker.

``app.worker`` calls :func:`register` with its task list at start-up. The
registration is explicit because ``python -m app.worker`` runs the worker
module as ``__main__``, so importing ``app.worker`` here would modify a
different module object.
"""

from __future__ import annotations

import time
from typing import Callable

from sqlalchemy.orm import Session as DBSession

from app.core.config import get_settings
from app.services.scheduling.service import reconcile_scheduled_posts, register_hooks, schedule_due_posts


_last_reconcile = 0.0


def run_scheduler(db: DBSession) -> int:
    """Queue due posts; about once a minute also repair posts whose job finished
    without the post being updated."""
    global _last_reconcile
    handled = schedule_due_posts(db)
    if time.monotonic() - _last_reconcile >= get_settings().worker_housekeeping_interval_seconds:
        _last_reconcile = time.monotonic()
        handled += reconcile_scheduled_posts(db)
    return handled


def register(tasks: list[Callable[[DBSession], int]]) -> None:
    register_hooks()
    if run_scheduler not in tasks:
        tasks.append(run_scheduler)


# The scheduler creates publishing jobs, so it runs before the publishing step
# of the same worker iteration.
run_scheduler.before_publishing = True  # type: ignore[attr-defined]
