"""Automation work for the background worker (``python -m app.worker``).

Three periodic tasks run on every worker iteration:

1. ``emit_approval_reminders`` records ``APPROVAL_REMINDER_DUE`` events.
2. ``dispatch_automation_events`` turns pending events into executions.
3. ``run_automation_executions`` runs due executions (new, retry-due, or
   abandoned after a crash).

Events, executions and the publishing hooks live in the database, so a worker
restart or a Redis outage delays automation work by at most one poll interval
and never loses it.
"""

from __future__ import annotations

from typing import Callable

from sqlalchemy.orm import Session as DBSession

from app.core.config import get_settings
from app.services.automation.engine import dispatch_events, run_executions
from app.services.automation.events import register_hooks
from app.services.automation.reminders import emit_due_approval_reminders
from app.services.publishing.service import default_worker_id

_WORKER_ID = default_worker_id()


def emit_approval_reminders(db: DBSession) -> int:
    if not get_settings().automation_enabled:
        return 0
    return emit_due_approval_reminders(db)


def dispatch_automation_events(db: DBSession) -> int:
    if not get_settings().automation_enabled:
        return 0
    return dispatch_events(db, worker_id=_WORKER_ID)


def run_automation_executions(db: DBSession) -> int:
    if not get_settings().automation_enabled:
        return 0
    return run_executions(db, worker_id=_WORKER_ID)


def register(tasks: list[Callable[[DBSession], int]]) -> None:
    register_hooks()
    for task in (emit_approval_reminders, dispatch_automation_events, run_automation_executions):
        if task not in tasks:
            tasks.append(task)
