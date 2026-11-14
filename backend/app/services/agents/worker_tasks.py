"""Agent workflow work for the background worker (``python -m app.worker``).

One periodic task runs due workflows: new ones, ones whose retry delay has
passed, and ones abandoned by a crashed worker (expired lease). Workflow state
is in the database, so a worker restart or a Redis outage delays work by at
most one poll interval and never loses it.
"""

from __future__ import annotations

from typing import Callable

from sqlalchemy.orm import Session as DBSession

from app.core.config import get_settings
from app.services.agents.orchestrator import run_due_workflows
from app.services.publishing.service import default_worker_id

_WORKER_ID = default_worker_id()


def run_agent_workflows(db: DBSession) -> int:
    if not get_settings().agents_enabled:
        return 0
    return run_due_workflows(db, worker_id=_WORKER_ID)


def register(tasks: list[Callable[[DBSession], int]]) -> None:
    if run_agent_workflows not in tasks:
        tasks.append(run_agent_workflows)
