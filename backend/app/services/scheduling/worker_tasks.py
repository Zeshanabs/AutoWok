"""Scheduling work for the background worker.

``app.worker`` calls :func:`register` with its task list at start-up. The
registration is explicit because ``python -m app.worker`` runs the worker
module as ``__main__``, so importing ``app.worker`` here would modify a
different module object.
"""

from __future__ import annotations

from typing import Callable

from sqlalchemy.orm import Session as DBSession

from app.services.scheduling.service import register_hooks, schedule_due_posts


def run_scheduler(db: DBSession) -> int:
    return schedule_due_posts(db)


def register(tasks: list[Callable[[DBSession], int]]) -> None:
    register_hooks()
    if run_scheduler not in tasks:
        tasks.append(run_scheduler)
