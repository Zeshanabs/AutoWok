"""Execution engine: dispatch events to automations and run executions.

Dispatch (``dispatch_events``)::

    event(pending) ──claim──▶ processing ──▶ processed   (dispatch_summary records
                                 │                        every automation and why it
                                 └── error ──▶ pending (retry) | failed      did or did not match)

For each enabled automation with the event's trigger type in the same
workspace the dispatcher applies, in order: chain-depth limit, self-trigger
block, brand scope, trigger configuration (reminder deadline), lifetime cap,
cooldown, per-automation hourly limit, workspace daily limit, conditions. A
match creates an ``AutomationExecution`` whose unique idempotency key makes a
second dispatch of the same event a no-op.

Run (``run_executions``)::

    pending ──claim──▶ running ──▶ succeeded
       ▲                 │
       └── retryable ────┴──▶ failed | cancelled (automation no longer enabled)

Claims are conditional UPDATEs with a lease, so several workers can run at
once and abandoned work is recovered after the lease expires. Each step is
recorded; retried executions skip steps that already succeeded.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.core.config import get_settings
from app.models import (
    Automation,
    AutomationEvent,
    AutomationExecution,
    AutomationExecutionStep,
    WorkspaceMembership,
)
from app.services import notifications as N
from app.services.audit import record_audit
from app.services.automation import actions as A
from app.services.automation.conditions import evaluate_conditions
from app.services.automation.events import execution_scope
from app.services.automation.registry import TRIGGERS, TriggerSpec, get_trigger
from app.services.publishing.queue import enqueue_publication

logger = logging.getLogger("autowok.automation")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def backoff_seconds(attempt: int, rng: random.Random | None = None) -> float:
    settings = get_settings()
    rng = rng or random.Random()
    exponential = min(settings.automation_backoff_max_seconds, settings.automation_backoff_base_seconds * (2 ** max(0, attempt - 1)))
    return exponential / 2 + rng.uniform(0, exponential / 2)


def automation_actor(db: DBSession, automation: Automation) -> WorkspaceMembership | None:
    """The member whose permissions an automation runs with (last editor, else creator)."""
    for user_id in (automation.updated_by, automation.created_by):
        if user_id is None:
            continue
        membership = (
            db.query(WorkspaceMembership)
            .filter(WorkspaceMembership.workspace_id == automation.workspace_id, WorkspaceMembership.user_id == user_id)
            .first()
        )
        if membership is not None and membership.user.is_active:
            return membership
    return None


# Dispatch -----------------------------------------------------------------------


def _event_claimable(now: datetime):
    return or_(
        and_(
            AutomationEvent.status == "pending",
            or_(AutomationEvent.next_attempt_at.is_(None), AutomationEvent.next_attempt_at <= now),
        ),
        and_(
            AutomationEvent.status == "processing",
            or_(AutomationEvent.lease_expires_at.is_(None), AutomationEvent.lease_expires_at < now),
        ),
    )


def due_event_ids(db: DBSession, *, now: datetime | None = None, limit: int = 50) -> list[UUID]:
    now = now or utc_now()
    rows = (
        db.query(AutomationEvent.id)
        .filter(_event_claimable(now))
        .order_by(AutomationEvent.occurred_at.asc())
        .limit(limit)
        .all()
    )
    return [row.id for row in rows]


def claim_event(db: DBSession, event_id: UUID, *, worker_id: str, now: datetime) -> bool:
    lease = now + timedelta(seconds=get_settings().automation_lease_seconds)
    result = db.execute(
        update(AutomationEvent)
        .where(AutomationEvent.id == event_id, _event_claimable(now))
        .values(status="processing", locked_by=worker_id, lease_expires_at=lease)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return result.rowcount == 1


def _executions_since(db: DBSession, *, since: datetime, automation_id: UUID | None = None, workspace_id: UUID | None = None) -> int:
    query = db.query(func.count(AutomationExecution.id)).filter(AutomationExecution.created_at >= since)
    if automation_id is not None:
        query = query.filter(AutomationExecution.automation_id == automation_id)
    if workspace_id is not None:
        query = query.filter(AutomationExecution.workspace_id == workspace_id)
    return int(query.scalar() or 0)


def _reminder_scope(automation: Automation, event: AutomationEvent) -> str | None:
    """Idempotency scope for reminders: one execution per approval per automation."""
    if event.event_type == "APPROVAL_REMINDER_DUE":
        approval_id = event.event_payload.get("approval_id")
        if approval_id:
            return f"approval:{approval_id}"
    return None


def evaluate_match(
    db: DBSession,
    automation: Automation,
    event: AutomationEvent,
    spec: TriggerSpec,
    *,
    now: datetime,
) -> tuple[str, dict[str, Any]]:
    """Decide whether an event should start an execution. Returns (outcome, details)."""
    settings = get_settings()
    payload = event.event_payload or {}
    if automation.status != "enabled":
        return "not_enabled", {}
    if event.chain_depth > settings.automation_max_chain_depth:
        return "chain_depth_exceeded", {"chain_depth": event.chain_depth}
    if event.origin_automation_id is not None and event.origin_automation_id == automation.id:
        return "self_trigger_blocked", {"origin_execution_id": str(event.origin_execution_id)}
    if automation.brand_id is not None and str(payload.get("brand_id") or "") != str(automation.brand_id):
        return "brand_mismatch", {}
    if event.event_type == "APPROVAL_REMINDER_DUE":
        deadline = int((automation.trigger_configuration or {}).get("deadline_hours") or 0)
        pending_hours = payload.get("pending_hours") or 0
        if deadline <= 0 or pending_hours < deadline:
            return "deadline_not_reached", {"deadline_hours": deadline, "pending_hours": pending_hours}
    if automation.max_executions is not None and automation.execution_count >= automation.max_executions:
        return "execution_limit_reached", {"max_executions": automation.max_executions}
    if automation.cooldown_seconds and automation.last_executed_at is not None:
        ready_at = _utc(automation.last_executed_at) + timedelta(seconds=automation.cooldown_seconds)
        if ready_at > now:
            return "cooldown", {"ready_at": ready_at.isoformat()}
    hourly = _executions_since(db, since=now - timedelta(hours=1), automation_id=automation.id)
    if hourly >= settings.automation_max_executions_per_hour:
        return "rate_limited", {"executions_last_hour": hourly}
    daily = _executions_since(db, since=now - timedelta(days=1), workspace_id=automation.workspace_id)
    if daily >= settings.automation_workspace_max_executions_per_day:
        return "workspace_limit_reached", {"executions_last_day": daily}
    result = evaluate_conditions(spec, automation.conditions, payload)
    if not result.passed:
        return "conditions_not_met", {"conditions": result.as_dict()}
    return "matched", {"conditions": result.as_dict()}


def dispatch_event(db: DBSession, event_id: UUID, *, worker_id: str, now: datetime | None = None) -> list[dict[str, Any]] | None:
    """Claim and dispatch one event. Returns the dispatch summary, or None if not claimed."""
    now = now or utc_now()
    settings = get_settings()
    if not claim_event(db, event_id, worker_id=worker_id, now=now):
        return None
    event = db.get(AutomationEvent, event_id, populate_existing=True)
    if event is None:
        return None
    event.attempt_count += 1
    summary: list[dict[str, Any]] = []
    try:
        spec = TRIGGERS.get(event.event_type)
        if spec is None:
            event.status = "failed"
            event.last_error = f"Unknown trigger {event.event_type}"
            event.processed_at = now
            event.locked_by = None
            event.lease_expires_at = None
            db.commit()
            return summary
        automations = (
            db.query(Automation)
            .filter(
                Automation.workspace_id == event.workspace_id,
                Automation.trigger_type == event.event_type,
                Automation.status == "enabled",
            )
            .order_by(Automation.created_at.asc())
            .all()
        )
        queued_ids: list[UUID] = []
        for automation in automations:
            outcome, details = evaluate_match(db, automation, event, spec, now=now)
            entry: dict[str, Any] = {"automation_id": str(automation.id), "name": automation.name, "outcome": outcome, **details}
            if outcome == "matched":
                scope = _reminder_scope(automation, event) or f"event:{event.id}"
                key = f"{automation.id}:{scope}"[:200]
                existing = db.query(AutomationExecution.id).filter(AutomationExecution.idempotency_key == key).first()
                if existing is not None:
                    entry["outcome"] = "duplicate"
                    entry["execution_id"] = str(existing.id)
                else:
                    execution = AutomationExecution(
                        automation_id=automation.id,
                        workspace_id=automation.workspace_id,
                        trigger_event_id=event.id,
                        idempotency_key=key,
                        status="pending",
                        trigger_type=event.event_type,
                        execution_context={
                            "payload": dict(event.event_payload or {}),
                            "conditions": details.get("conditions"),
                            "event_occurred_at": _utc(event.occurred_at).isoformat() if event.occurred_at else None,
                        },
                        max_retries=settings.automation_max_retries,
                        chain_depth=event.chain_depth,
                    )
                    db.add(execution)
                    db.flush()
                    automation.execution_count += 1
                    automation.last_executed_at = now
                    entry["outcome"] = "queued"
                    entry["execution_id"] = str(execution.id)
                    queued_ids.append(execution.id)
            summary.append(entry)
        event.status = "processed"
        event.processed_at = now
        event.dispatch_summary = summary
        event.locked_by = None
        event.lease_expires_at = None
        event.last_error = None
        db.commit()
        for execution_id in queued_ids:
            enqueue_publication(execution_id)
        return summary
    except Exception as exc:  # noqa: BLE001 - keep the event for a retry
        db.rollback()
        logger.exception("Dispatching automation event %s failed", event_id)
        event = db.get(AutomationEvent, event_id, populate_existing=True)
        if event is None:
            return None
        event.attempt_count += 1
        event.last_error = str(exc)[:1000]
        event.locked_by = None
        event.lease_expires_at = None
        if event.attempt_count >= settings.automation_event_max_attempts:
            event.status = "failed"
            event.processed_at = now
        else:
            event.status = "pending"
            event.next_attempt_at = now + timedelta(seconds=backoff_seconds(event.attempt_count))
        db.commit()
        return None


def dispatch_events(db: DBSession, *, worker_id: str = "automation", now: datetime | None = None, limit: int = 50) -> int:
    if not get_settings().automation_enabled:
        return 0
    handled = 0
    for event_id in due_event_ids(db, now=now, limit=limit):
        try:
            if dispatch_event(db, event_id, worker_id=worker_id, now=now) is not None:
                handled += 1
        except Exception:  # noqa: BLE001
            logger.exception("Unexpected failure dispatching event %s", event_id)
            db.rollback()
    return handled


# Execution ----------------------------------------------------------------------


def _execution_claimable(now: datetime):
    return or_(
        and_(
            AutomationExecution.status == "pending",
            or_(AutomationExecution.next_attempt_at.is_(None), AutomationExecution.next_attempt_at <= now),
        ),
        and_(
            AutomationExecution.status == "running",
            or_(AutomationExecution.lease_expires_at.is_(None), AutomationExecution.lease_expires_at < now),
        ),
    )


def due_execution_ids(db: DBSession, *, now: datetime | None = None, limit: int = 20) -> list[UUID]:
    now = now or utc_now()
    rows = (
        db.query(AutomationExecution.id)
        .filter(_execution_claimable(now))
        .order_by(AutomationExecution.next_attempt_at.asc(), AutomationExecution.created_at.asc())
        .limit(limit)
        .all()
    )
    return [row.id for row in rows]


def claim_execution(db: DBSession, execution_id: UUID, *, worker_id: str, now: datetime) -> bool:
    settings = get_settings()
    lease = now + timedelta(seconds=settings.automation_lease_seconds)
    automation_id = (
        db.query(AutomationExecution.automation_id).filter(AutomationExecution.id == execution_id).scalar()
    )
    if automation_id is None:
        return False
    # Concurrency limit: executions of the same automation that are running with a live lease.
    running = (
        select(func.count(AutomationExecution.id))
        .where(
            AutomationExecution.automation_id == automation_id,
            AutomationExecution.id != execution_id,
            AutomationExecution.status == "running",
            AutomationExecution.lease_expires_at.is_not(None),
            AutomationExecution.lease_expires_at >= now,
        )
        .scalar_subquery()
    )
    result = db.execute(
        update(AutomationExecution)
        .where(
            AutomationExecution.id == execution_id,
            _execution_claimable(now),
            running < settings.automation_max_concurrent_executions,
        )
        .values(status="running", locked_by=worker_id, lease_expires_at=lease, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return result.rowcount == 1


def _finish_execution(db: DBSession, execution: AutomationExecution, automation: Automation, *, status: str, now: datetime, error: str | None) -> None:
    execution.status = status
    execution.completed_at = now
    execution.error_message = error
    execution.locked_by = None
    execution.lease_expires_at = None
    execution.next_attempt_at = None
    if status == "succeeded":
        automation.success_count += 1
    elif status == "failed":
        automation.failure_count += 1
        owner = automation.updated_by or automation.created_by
        if owner is not None:
            N.notify(
                db,
                workspace_id=automation.workspace_id,
                user_id=owner,
                category="automation_failure",
                title=f"Automation failed: {automation.name}",
                message=(error or "The automation could not complete.")[:500],
                resource_type="automation",
                resource_id=automation.id,
                automation_id=automation.id,
                execution_id=execution.id,
                dedupe_key=f"execution_failed:{execution.id}",
            )
    record_audit(
        db,
        action=f"automation.execution_{status}",
        resource_type="automation_execution",
        workspace_id=automation.workspace_id,
        resource_id=execution.id,
        metadata={"automation_id": str(automation.id), "trigger_type": execution.trigger_type, "error": (error or "")[:300] or None},
    )


def _retry_or_fail(db: DBSession, execution: AutomationExecution, automation: Automation, *, now: datetime, error: str) -> None:
    if execution.retry_count < execution.max_retries:
        execution.retry_count += 1
        execution.status = "pending"
        execution.error_message = error
        execution.locked_by = None
        execution.lease_expires_at = None
        execution.next_attempt_at = now + timedelta(seconds=backoff_seconds(execution.retry_count))
        return
    _finish_execution(db, execution, automation, status="failed", now=now, error=error)


def run_execution(db: DBSession, execution_id: UUID, *, worker_id: str = "automation", now: datetime | None = None) -> str | None:
    """Claim and run one execution. Returns the resulting status, or None if not claimed."""
    now = now or utc_now()
    settings = get_settings()
    if not claim_execution(db, execution_id, worker_id=worker_id, now=now):
        return None
    execution = db.get(AutomationExecution, execution_id, populate_existing=True)
    if execution is None:
        return None
    automation = db.get(Automation, execution.automation_id)
    execution.started_at = execution.started_at or now
    if automation is None:
        execution.status = "cancelled"
        execution.completed_at = now
        execution.error_message = "The automation was deleted."
        execution.locked_by = None
        execution.lease_expires_at = None
        db.commit()
        return execution.status
    if automation.status != "enabled":
        _finish_execution(
            db, execution, automation, status="cancelled", now=now, error=f"The automation is {automation.status}; the execution was not run."
        )
        db.commit()
        return execution.status

    spec = get_trigger(execution.trigger_type)
    payload = dict((execution.execution_context or {}).get("payload") or {})
    actor = automation_actor(db, automation)
    existing_steps = {step.execution_order: step for step in execution.steps}
    actions = sorted(automation.actions, key=lambda item: item.execution_order)
    deadline = now + timedelta(seconds=settings.automation_execution_timeout_seconds)
    failure: str | None = None
    retryable = False

    for position, action in enumerate(actions, start=1):
        step = existing_steps.get(position)
        if step is None:
            step = AutomationExecutionStep(
                execution_id=execution.id,
                action_id=action.id,
                action_type=action.action_type,
                execution_order=position,
                status="pending",
            )
            db.add(step)
            existing_steps[position] = step
        if failure is not None:
            if step.status != "succeeded":
                step.status = "skipped"
                step.error_message = "Skipped because an earlier step failed."
            continue
        if step.status == "succeeded":
            continue  # already done in a previous attempt
        if utc_now() > deadline:
            failure = f"Execution exceeded the {settings.automation_execution_timeout_seconds}s time limit."
            step.status = "skipped"
            step.error_message = failure
            continue
        step.status = "running"
        step.started_at = utc_now()
        step.error_message = None
        try:
            action_spec = A.get_action(action.action_type)
            A.check_actor_permission(action_spec, actor)
            config = action_spec.config_model.model_validate(action.action_configuration or {})
            ctx = A.ActionContext(
                db=db,
                automation=automation,
                execution=execution,
                spec=spec,
                payload=payload,
                now=utc_now(),
                actor=actor,
                step_order=position,
            )
            with execution_scope(execution):
                result = action_spec.run(ctx, config)
            step.status = "succeeded"
            step.completed_at = utc_now()
            step.result_summary = {"summary": result.summary, **result.details}
            # Renew the lease between steps so long chains are not stolen by another worker.
            execution.lease_expires_at = utc_now() + timedelta(seconds=settings.automation_lease_seconds)
            db.commit()
        except A.ActionRetryable as exc:
            db.rollback()
            step = _reload_step(db, execution, position, action)
            step.status = "failed"
            step.completed_at = utc_now()
            step.error_message = str(exc)[:1000]
            failure, retryable = f"Step {position} ({action.action_type}) failed temporarily: {exc}", True
        except A.ActionError as exc:
            db.rollback()
            step = _reload_step(db, execution, position, action)
            step.status = "failed"
            step.completed_at = utc_now()
            step.error_message = str(exc)[:1000]
            failure = f"Step {position} ({action.action_type}) failed: {exc}"
        except Exception as exc:  # noqa: BLE001 - unexpected errors are retried, bounded
            db.rollback()
            logger.exception("Automation step %s of execution %s crashed", position, execution.id)
            step = _reload_step(db, execution, position, action)
            step.status = "failed"
            step.completed_at = utc_now()
            step.error_message = f"{type(exc).__name__}: {exc}"[:1000]
            failure, retryable = f"Step {position} ({action.action_type}) crashed: {type(exc).__name__}", True

    execution = db.get(AutomationExecution, execution_id, populate_existing=True)
    automation = db.get(Automation, execution.automation_id)
    finished = utc_now()
    if failure is None:
        _finish_execution(db, execution, automation, status="succeeded", now=finished, error=None)
    elif retryable:
        _retry_or_fail(db, execution, automation, now=finished, error=failure)
    else:
        _finish_execution(db, execution, automation, status="failed", now=finished, error=failure)
    db.commit()
    return execution.status


def _reload_step(db: DBSession, execution: AutomationExecution, position: int, action) -> AutomationExecutionStep:
    """After a rollback, re-attach (or recreate) the step row for ``position``."""
    step = (
        db.query(AutomationExecutionStep)
        .filter(AutomationExecutionStep.execution_id == execution.id, AutomationExecutionStep.execution_order == position)
        .first()
    )
    if step is None:
        step = AutomationExecutionStep(
            execution_id=execution.id,
            action_id=action.id,
            action_type=action.action_type,
            execution_order=position,
            status="pending",
        )
        db.add(step)
    return step


def run_executions(db: DBSession, *, worker_id: str = "automation", now: datetime | None = None, limit: int = 20) -> int:
    if not get_settings().automation_enabled:
        return 0
    processed = 0
    for execution_id in due_execution_ids(db, now=now, limit=limit):
        try:
            if run_execution(db, execution_id, worker_id=worker_id, now=now) is not None:
                processed += 1
        except Exception:  # noqa: BLE001 - one bad execution must not stop the others
            logger.exception("Automation execution %s failed unexpectedly", execution_id)
            db.rollback()
    return processed


def retry_execution(db: DBSession, execution: AutomationExecution, *, user_id: UUID) -> AutomationExecution:
    """User action: queue an eligible failed execution again."""
    if execution.status != "failed":
        raise ValueError("Only failed executions can be retried.")
    automation = db.get(Automation, execution.automation_id)
    if automation is None or automation.status != "enabled":
        raise ValueError("Enable the automation before retrying its executions.")
    execution.status = "pending"
    execution.next_attempt_at = None
    execution.max_retries = execution.retry_count + get_settings().automation_max_retries
    execution.completed_at = None
    execution.error_message = None
    execution.retried_by = user_id
    for step in execution.steps:
        if step.status in {"failed", "skipped"}:
            step.status = "pending"
            step.error_message = None
    record_audit(
        db,
        action="automation.execution_retried",
        resource_type="automation_execution",
        actor_user_id=user_id,
        workspace_id=execution.workspace_id,
        resource_id=execution.id,
        metadata={"automation_id": str(automation.id)},
    )
    db.commit()
    db.refresh(execution)
    enqueue_publication(execution.id)
    return execution
