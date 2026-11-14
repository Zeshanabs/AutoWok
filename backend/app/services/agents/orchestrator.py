"""Orchestrator: plans, runs and compiles multi-agent workflows.

State lives in the database, so a workflow survives worker restarts::

    workflow: pending ──claim──▶ running ──▶ succeeded | failed | cancelled
                 ▲                  │
                 └── retry later ───┘   (Groq rate limit / outage: bounded, with backoff)

    step:     pending ─▶ running ─▶ succeeded | failed        (others become skipped / cancelled)

* A workflow is claimed with a conditional UPDATE and a lease. If the worker
  dies, the lease expires, another worker claims the workflow, resets the step
  that was running and continues after the steps that already succeeded.
* Steps run in dependency order. Steps of one ``parallel_group`` are
  independent; they run one at a time unless ``AGENT_MAX_PARALLEL_CALLS`` > 1.
* Every model answer is parsed as JSON and validated against the agent's
  output schema, then checked by the agent's ``finalize``. Invalid output is
  retried, bounded by attempts per step and agent calls per workflow.
* The orchestrator only starts registered agents and registered tools. Nothing
  an agent returns is executed; it is stored and shown to people.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import and_, func, or_, update
from sqlalchemy.orm import Session as DBSession

from app.core.config import Settings, get_settings
from app.models import (
    AgentExecution,
    AgentMessage,
    AgentWorkflow,
    AgentWorkflowStep,
    User,
    WorkspaceMembership,
)
from app.models.agent import ACTIVE_WORKFLOW_STATUSES
from app.services import notifications as N
from app.services.agents import workflows as W
from app.services.agents.llm import AgentLLM, AgentOutputError, AgentRunError, LLMResult
from app.services.agents.registry import (
    ORCHESTRATOR_KEY,
    AgentRegistryError,
    AgentSpec,
    Finalized,
    Prepared,
    require_enabled,
    role_allows,
)
from app.services.agents.schemas import AgentResponse
from app.services.agents.tools import READ_TOOLS, AgentContext, ToolBox, ToolError
from app.services.audit import record_audit
from app.services.publishing.queue import enqueue_publication

logger = logging.getLogger("autowok.agents")

LLMFactory = Callable[[DBSession, UUID, Settings], Any]
ORCHESTRATOR_VERSION = "1.0.0"


class WorkflowLimitError(W.WorkflowError):
    """A workspace limit (active workflows, hourly starts, revisions) was reached."""


class WorkflowStateError(W.WorkflowError):
    """The action is not possible in the workflow's current state."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def backoff_seconds(attempt: int, settings: Settings) -> float:
    return min(settings.agent_backoff_max_seconds, settings.agent_backoff_base_seconds * (2 ** max(0, attempt - 1)))


def default_llm_factory(db: DBSession, workspace_id: UUID, settings: Settings) -> AgentLLM:
    return AgentLLM(db, workspace_id, settings)


# Creation -------------------------------------------------------------------------


def _add_steps(db: DBSession, workflow: AgentWorkflow, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        db.add(
            AgentWorkflowStep(
                workflow_id=workflow.id,
                step_order=row["step_order"],
                step_key=row["step_key"],
                base_key=row["base_key"],
                revision_round=row.get("revision_round", 0),
                kind=row["kind"],
                agent_key=row["agent_key"],
                label=row["label"],
                dependency_configuration={
                    "depends_on": row["depends_on"],
                    "parallel_group": row.get("parallel_group"),
                    "feedback": row.get("feedback"),
                },
                status="pending",
            )
        )


def active_workflow_count(db: DBSession, workspace_id: UUID, *, exclude: UUID | None = None) -> int:
    query = db.query(func.count(AgentWorkflow.id)).filter(
        AgentWorkflow.workspace_id == workspace_id, AgentWorkflow.status.in_(ACTIVE_WORKFLOW_STATUSES)
    )
    if exclude is not None:
        query = query.filter(AgentWorkflow.id != exclude)
    return int(query.scalar() or 0)


def check_start_limits(db: DBSession, workspace_id: UUID, settings: Settings, *, now: datetime | None = None) -> None:
    if not settings.agents_enabled:
        raise WorkflowStateError("AI agent workflows are disabled on this server.")
    if active_workflow_count(db, workspace_id) >= settings.agent_max_active_workflows:
        raise WorkflowLimitError(
            f"This workspace already has {settings.agent_max_active_workflows} workflow(s) in progress. "
            "Wait for one to finish or cancel it."
        )
    since = (now or utc_now()) - timedelta(hours=1)
    recent = (
        db.query(func.count(AgentWorkflow.id))
        .filter(AgentWorkflow.workspace_id == workspace_id, AgentWorkflow.created_at >= since)
        .scalar()
    )
    if int(recent or 0) >= settings.agent_max_workflows_per_hour:
        raise WorkflowLimitError("The hourly limit for AI agent workflows was reached. Try again later.")


def create_workflow(
    db: DBSession,
    *,
    workspace_id: UUID,
    user: User,
    workflow_type: str,
    task: str,
    data: dict[str, Any],
    name: str | None = None,
) -> AgentWorkflow:
    """Validate, plan and persist a workflow. The worker runs it."""
    settings = get_settings()
    definition = W.get_workflow(workflow_type)
    check_start_limits(db, workspace_id, settings)
    for agent_key in definition.agent_keys:
        require_enabled(db, workspace_id, agent_key)
    input_data = W.validate_inputs(db, workspace_id, definition, data)
    cleaned_task = " ".join(task.split())
    workflow = AgentWorkflow(
        workspace_id=workspace_id,
        brand_id=UUID(input_data["brand_id"]) if input_data["brand_id"] else None,
        workflow_type=definition.key,
        name=(name or f"{definition.name}: {cleaned_task}")[:200],
        task=cleaned_task,
        input_data=input_data,
        status="pending",
        created_by=user.id,
    )
    db.add(workflow)
    db.flush()
    _add_steps(db, workflow, W.plan_steps(definition))
    record_audit(
        db,
        action="agent_workflow.started",
        resource_type="agent_workflow",
        actor_user_id=user.id,
        workspace_id=workspace_id,
        resource_id=workflow.id,
        metadata={"workflow_type": definition.key, "agents": definition.agent_keys},
    )
    db.commit()
    db.refresh(workflow)
    enqueue_publication(workflow.id)  # wake the worker; the database poll is the fallback
    return workflow


# Claiming -------------------------------------------------------------------------


def _claimable(now: datetime):
    return or_(
        and_(
            AgentWorkflow.status == "pending",
            or_(AgentWorkflow.next_attempt_at.is_(None), AgentWorkflow.next_attempt_at <= now),
        ),
        and_(
            AgentWorkflow.status == "running",
            or_(AgentWorkflow.lease_expires_at.is_(None), AgentWorkflow.lease_expires_at < now),
        ),
    )


def due_workflow_ids(db: DBSession, *, now: datetime | None = None, limit: int = 5) -> list[UUID]:
    now = now or utc_now()
    rows = (
        db.query(AgentWorkflow.id)
        .filter(_claimable(now))
        .order_by(AgentWorkflow.created_at.asc())
        .limit(limit)
        .all()
    )
    return [row.id for row in rows]


def claim_workflow(db: DBSession, workflow_id: UUID, *, worker_id: str, now: datetime) -> bool:
    lease = now + timedelta(seconds=get_settings().agent_lease_seconds)
    result = db.execute(
        update(AgentWorkflow)
        .where(AgentWorkflow.id == workflow_id, _claimable(now))
        .values(status="running", locked_by=worker_id, lease_expires_at=lease, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return result.rowcount == 1


# Finishing ------------------------------------------------------------------------


def _steps(db: DBSession, workflow: AgentWorkflow) -> list[AgentWorkflowStep]:
    return (
        db.query(AgentWorkflowStep)
        .filter(AgentWorkflowStep.workflow_id == workflow.id)
        .order_by(AgentWorkflowStep.step_order.asc())
        .populate_existing()
        .all()
    )


def _release(workflow: AgentWorkflow) -> None:
    workflow.locked_by = None
    workflow.lease_expires_at = None


def _finish(db: DBSession, workflow: AgentWorkflow, *, status: str, now: datetime, error: str | None = None) -> None:
    workflow.status = status
    workflow.completed_at = now
    workflow.error_message = error
    workflow.next_attempt_at = None
    _release(workflow)
    if status == "succeeded":
        workflow.review_status = "pending"
    record_audit(
        db,
        action=f"agent_workflow.{status}",
        resource_type="agent_workflow",
        workspace_id=workflow.workspace_id,
        resource_id=workflow.id,
        metadata={
            "workflow_type": workflow.workflow_type,
            "agent_calls": workflow.agent_call_count,
            "total_tokens": workflow.total_tokens,
            "error": (error or "")[:300] or None,
        },
    )
    if workflow.created_by is not None and status in {"succeeded", "failed"}:
        N.notify(
            db,
            workspace_id=workflow.workspace_id,
            user_id=workflow.created_by,
            category="agent_workflow",
            title=("AI workflow ready for review: " if status == "succeeded" else "AI workflow failed: ") + workflow.name,
            message=(
                "The agents finished. Review the output before using it."
                if status == "succeeded"
                else (error or "The workflow could not complete.")
            )[:500],
            resource_type="agent_workflow",
            resource_id=workflow.id,
            dedupe_key=f"agent_workflow:{workflow.id}:{status}:{workflow.revision_count}",
        )


def _close_open_steps(db: DBSession, workflow: AgentWorkflow, *, status: str, reason: str) -> None:
    for step in _steps(db, workflow):
        if step.status in {"pending", "running"}:
            step.status = status
            step.error_message = reason
    running = (
        db.query(AgentExecution)
        .filter(AgentExecution.workflow_id == workflow.id, AgentExecution.status == "running")
        .all()
    )
    for execution in running:
        execution.status = "cancelled" if status == "cancelled" else "failed"
        execution.error_message = reason
        execution.completed_at = utc_now()


def _fail(db: DBSession, workflow: AgentWorkflow, message: str, *, now: datetime) -> str:
    _close_open_steps(db, workflow, status="skipped", reason="Skipped because the workflow failed.")
    _finish(db, workflow, status="failed", now=now, error=message[:1000])
    db.commit()
    return "failed"


def _cancel(db: DBSession, workflow: AgentWorkflow, *, now: datetime) -> str:
    _close_open_steps(db, workflow, status="cancelled", reason="Cancelled by a user.")
    _finish(db, workflow, status="cancelled", now=now, error="Cancelled by a user.")
    db.commit()
    return "cancelled"


def request_cancel(db: DBSession, workflow: AgentWorkflow, *, user: User) -> AgentWorkflow:
    """User action. A queued workflow stops now; a running one stops before its next step."""
    if workflow.status not in ACTIVE_WORKFLOW_STATUSES:
        raise WorkflowStateError("Only a queued or running workflow can be cancelled.")
    now = utc_now()
    workflow.cancel_requested = True
    record_audit(
        db,
        action="agent_workflow.cancel_requested",
        resource_type="agent_workflow",
        actor_user_id=user.id,
        workspace_id=workflow.workspace_id,
        resource_id=workflow.id,
    )
    db.commit()
    result = db.execute(
        update(AgentWorkflow)
        .where(AgentWorkflow.id == workflow.id, AgentWorkflow.status == "pending")
        .values(status="cancelled", completed_at=now, error_message="Cancelled by a user.", next_attempt_at=None)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    db.refresh(workflow)
    if result.rowcount == 1:
        _close_open_steps(db, workflow, status="cancelled", reason="Cancelled by a user.")
        record_audit(
            db,
            action="agent_workflow.cancelled",
            resource_type="agent_workflow",
            workspace_id=workflow.workspace_id,
            resource_id=workflow.id,
        )
        db.commit()
        db.refresh(workflow)
    return workflow


# Run state ------------------------------------------------------------------------


def build_state(db: DBSession, workflow: AgentWorkflow, steps: list[AgentWorkflowStep], current: AgentWorkflowStep | None) -> W.RunState:
    state = W.RunState(workflow=workflow, inputs=dict(workflow.input_data or {}))
    for step in steps:
        if step.status != "succeeded" or step.execution_id is None:
            continue
        execution = db.get(AgentExecution, step.execution_id)
        if execution is None or not execution.output_data:
            continue
        state.envelopes[step.step_key] = execution.output_data
        state.results[step.step_key] = execution.output_data.get("result") or {}
        state.rounds[step.step_key] = (step.base_key, step.revision_round)
    if current is not None:
        state.round = current.revision_round
        state.feedback = (current.dependency_configuration or {}).get("feedback")
    else:
        state.round = max((step.revision_round for step in steps), default=0)
    return state


def _message(db: DBSession, workflow: AgentWorkflow, sender: str, receiver: str, kind: str, payload: dict[str, Any]) -> None:
    db.add(
        AgentMessage(
            workflow_id=workflow.id,
            sender_agent=sender,
            receiver_agent=receiver,
            message_type=kind,
            structured_payload=payload,
        )
    )


def _start_execution(
    db: DBSession, workflow: AgentWorkflow, step: AgentWorkflowStep, *, version: str, input_data: dict[str, Any], now: datetime
) -> AgentExecution:
    execution = AgentExecution(
        workflow_id=workflow.id,
        workspace_id=workflow.workspace_id,
        step_id=step.id,
        step_key=step.step_key,
        agent_key=step.agent_key,
        agent_version=version,
        attempt_number=step.attempt_count + 1,
        status="running",
        input_data=input_data,
        started_at=now,
    )
    db.add(execution)
    db.flush()
    step.status = "running"
    step.execution_id = execution.id
    step.error_message = None
    _message(
        db, workflow, ORCHESTRATOR_KEY, step.agent_key, "task",
        {"step_key": step.step_key, "execution_id": str(execution.id), "attempt": execution.attempt_number},
    )
    return execution


def _envelope(
    workflow: AgentWorkflow,
    execution: AgentExecution,
    *,
    status: str,
    result: dict[str, Any] | None = None,
    evidence: list[dict[str, Any]] | None = None,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
    usage: dict[str, Any] | None = None,
    duration_ms: int = 0,
    model: str | None = None,
) -> dict[str, Any]:
    return AgentResponse(
        agent_id=execution.agent_key,
        agent_version=execution.agent_version or ORCHESTRATOR_VERSION,
        task_id=str(workflow.id),
        execution_id=str(execution.id),
        status=status,  # type: ignore[arg-type]
        result=result or {},
        evidence=evidence or [],
        warnings=warnings or [],
        errors=errors or [],
        token_usage=usage or {},
        duration_ms=duration_ms,
        model=model,
    ).model_dump(mode="json")


def _complete(
    db: DBSession,
    workflow: AgentWorkflow,
    step: AgentWorkflowStep,
    execution: AgentExecution,
    *,
    result: dict[str, Any],
    evidence: list[dict[str, Any]],
    warnings: list[str],
    usage: dict[str, Any] | None,
    model: str | None,
    duration_ms: int,
) -> None:
    execution.status = "succeeded"
    execution.completed_at = utc_now()
    execution.execution_duration_ms = duration_ms
    execution.model_name = model
    execution.token_usage = usage
    execution.output_data = _envelope(
        workflow, execution, status="succeeded", result=result, evidence=evidence, warnings=warnings,
        usage=usage, duration_ms=duration_ms, model=model,
    )
    step.status = "succeeded"
    step.error_message = None
    if usage:
        workflow.prompt_tokens += int(usage.get("prompt_tokens") or 0)
        workflow.completion_tokens += int(usage.get("completion_tokens") or 0)
        workflow.total_tokens += int(usage.get("total_tokens") or 0)
    _message(
        db, workflow, step.agent_key, ORCHESTRATOR_KEY, "result",
        {"step_key": step.step_key, "execution_id": str(execution.id), "status": "succeeded", "warnings": len(warnings)},
    )


def _record_failure(
    db: DBSession, workflow: AgentWorkflow, step: AgentWorkflowStep, execution: AgentExecution | None, message: str, *, duration_ms: int = 0
) -> None:
    if execution is not None:
        execution.status = "failed"
        execution.completed_at = utc_now()
        execution.execution_duration_ms = duration_ms
        execution.error_message = message[:1000]
        execution.output_data = _envelope(workflow, execution, status="failed", errors=[message[:1000]], duration_ms=duration_ms)
        _message(
            db, workflow, step.agent_key, ORCHESTRATOR_KEY, "result",
            {"step_key": step.step_key, "execution_id": str(execution.id), "status": "failed", "error": message[:300]},
        )
    step.attempt_count += 1
    step.error_message = message[:1000]


# Step execution -------------------------------------------------------------------


@dataclass
class _Job:
    step: AgentWorkflowStep
    spec: AgentSpec | None = None
    execution: AgentExecution | None = None
    prepared: Prepared | None = None
    future: Future | None = None
    llm_result: LLMResult | None = None
    error: AgentRunError | None = None
    started: float = 0.0

    @property
    def duration_ms(self) -> int:
        return int((time.monotonic() - self.started) * 1000) if self.started else 0


@dataclass
class _BatchOutcome:
    failure: str | None = None  # permanent failure message
    retry_delay: float | None = None  # > 0: release the workflow and try again later


def _system_step(
    db: DBSession, workflow: AgentWorkflow, step: AgentWorkflowStep, definition: W.WorkflowDef, ctx: AgentContext,
    steps: list[AgentWorkflowStep], settings: Settings,
) -> _BatchOutcome:
    """Run a context or compile step. No model call, read-only tools."""
    started = time.monotonic()
    execution = _start_execution(db, workflow, step, version=ORCHESTRATOR_VERSION, input_data={"kind": step.kind}, now=utc_now())
    db.commit()
    try:
        step_def = definition.step(step.base_key)
        state = build_state(db, workflow, steps, step)
        tools = ToolBox(ctx, READ_TOOLS, caller=ORCHESTRATOR_KEY)
        result = dict(step_def.run(ctx, tools, state))  # type: ignore[misc]
        warnings = list(result.pop("_warnings", []))
        if step.kind == "compile" and definition.review_gate is not None:
            result = _apply_review_gate(db, workflow, definition, state, result, settings)
        _complete(
            db, workflow, step, execution, result=result, evidence=list(result.get("evidence") or []) if step.kind == "compile" else [],
            warnings=warnings, usage=None, model=None, duration_ms=int((time.monotonic() - started) * 1000),
        )
        db.commit()
        return _BatchOutcome()
    except (ToolError, W.WorkflowError, AgentRunError) as exc:
        message = str(exc)
    except Exception as exc:  # noqa: BLE001 - deterministic code: do not retry, report
        logger.exception("Workflow %s step %s crashed", workflow.id, step.step_key)
        db.rollback()
        message = f"{step.label} failed unexpectedly ({type(exc).__name__})."
    step = db.get(AgentWorkflowStep, step.id, populate_existing=True)
    execution = db.get(AgentExecution, execution.id, populate_existing=True)
    _record_failure(db, workflow, step, execution, message, duration_ms=int((time.monotonic() - started) * 1000))
    step.status = "failed"
    db.commit()
    return _BatchOutcome(failure=f"{step.label}: {message}")


def _apply_review_gate(
    db: DBSession, workflow: AgentWorkflow, definition: W.WorkflowDef, state: W.RunState, deliverable: dict[str, Any], settings: Settings
) -> dict[str, Any]:
    """After reviewers ran: ask the writer for a bounded revision, or finalize with open issues listed."""
    reasons = definition.review_gate(state, settings)  # type: ignore[misc]
    can_revise = (
        bool(reasons)
        and workflow.auto_revision_count < settings.agent_max_auto_revisions
        and workflow.revision_count < settings.agent_max_revisions
    )
    if can_revise:
        append_revision_round(db, workflow, definition, feedback=None, auto=True, reasons=reasons)
        return {"decision": "revision_requested", "reasons": reasons, "revision_round": workflow.revision_count}
    deliverable["decision"] = "final"
    deliverable["open_issues"] = reasons
    deliverable["revision_limit_reached"] = bool(reasons)
    return deliverable


def append_revision_round(
    db: DBSession, workflow: AgentWorkflow, definition: W.WorkflowDef, *, feedback: str | None, auto: bool, reasons: list[str]
) -> int:
    """Add one more writer + reviewers + compile round. Callers enforce the limits."""
    steps = _steps(db, workflow)
    round_number = workflow.revision_count + 1
    order = max(step.step_order for step in steps)
    latest: dict[str, str] = {}
    for step in steps:
        latest[step.base_key] = step.step_key  # steps are ordered, so the last one wins
    revised = set(definition.revision_steps)
    rows = []
    for base in definition.revision_steps:
        step_def = definition.step(base)
        order += 1
        rows.append(
            {
                "step_order": order,
                "step_key": f"{base}:r{round_number}",
                "base_key": base,
                "revision_round": round_number,
                "kind": step_def.kind,
                "agent_key": step_def.agent_key,
                "label": f"{step_def.label} (revision {round_number})",
                "depends_on": [f"{dep}:r{round_number}" if dep in revised else latest[dep] for dep in step_def.depends_on],
                "parallel_group": step_def.parallel_group,
                "feedback": feedback,
            }
        )
    _add_steps(db, workflow, rows)
    workflow.revision_count = round_number
    if auto:
        workflow.auto_revision_count += 1
    _message(
        db, workflow, ORCHESTRATOR_KEY, "content_writer", "revision_request",
        {"round": round_number, "requested_by": "orchestrator" if auto else "user", "reasons": reasons[:20], "feedback": feedback},
    )
    db.flush()
    return round_number


def _prepare_job(
    db: DBSession, workflow: AgentWorkflow, job: _Job, definition: W.WorkflowDef, ctx: AgentContext,
    steps: list[AgentWorkflowStep], settings: Settings,
) -> None:
    step = job.step
    job.started = time.monotonic()
    try:
        if workflow.agent_call_count >= settings.agent_max_calls_per_workflow:
            raise AgentRunError(
                f"The workflow reached its limit of {settings.agent_max_calls_per_workflow} agent calls.", kind="call_limit"
            )
        job.spec = require_enabled(db, workflow.workspace_id, step.agent_key)
        if not role_allows(ctx.membership.role, job.spec.required_role):
            raise AgentRunError(f"The {job.spec.name} requires the {job.spec.required_role} role.", kind="forbidden")
        step_def = definition.step(step.base_key)
        state = build_state(db, workflow, steps, step)
        try:
            inputs = job.spec.input_model.model_validate(step_def.build_input(state))  # type: ignore[misc]
        except ValidationError as exc:
            raise AgentRunError(f"The input for the {job.spec.name} is invalid: {_validation_summary(exc)}", kind="invalid_input") from exc
        job.execution = _start_execution(
            db, workflow, step, version=job.spec.version, input_data=inputs.model_dump(mode="json"), now=utc_now()
        )
        workflow.agent_call_count += 1
        db.commit()
        tools = ToolBox(ctx, job.spec.tools, caller=job.spec.key)
        job.prepared = job.spec.prepare(ctx, tools, inputs)
        db.commit()  # keep controlled writes made through tools (for example a new research project)
    except AgentRunError as exc:
        job.error = exc
    except (ToolError, AgentRegistryError) as exc:
        job.error = AgentRunError(str(exc), kind="tool_error")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Preparing step %s of workflow %s crashed", step.step_key, workflow.id)
        db.rollback()
        job.error = AgentRunError(f"The agent could not be prepared ({type(exc).__name__}).", retryable=True, delay_seconds=0, kind="crash")


def _validation_summary(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors()[:5]:
        location = ".".join(str(item) for item in error["loc"]) or "output"
        parts.append(f"{location}: {error['msg']}")
    return "; ".join(parts)


def _infer(jobs: list[_Job], llm: Any, settings: Settings) -> None:
    """Run the model calls for a batch. More than one job means they are independent of each other."""
    pending = [job for job in jobs if job.error is None and job.prepared is not None and job.prepared.prompt]
    if not pending:
        return
    executor = ThreadPoolExecutor(max_workers=len(pending), thread_name_prefix="agent-llm")
    try:
        for job in pending:
            job.future = executor.submit(
                llm.complete_json,
                job.prepared.prompt,
                temperature=job.spec.model.temperature,
                max_tokens=job.spec.model.max_tokens,
            )
        for job in pending:
            timeout = job.spec.limits.timeout_seconds or settings.agent_step_timeout_seconds
            remaining = max(0.05, timeout - (time.monotonic() - job.started))
            try:
                job.llm_result = job.future.result(timeout=remaining)
            except FutureTimeout:
                job.future.cancel()
                job.error = AgentRunError(
                    f"The {job.spec.name} timed out after {timeout} seconds.", retryable=True, kind="timeout"
                )
            except AgentRunError as exc:
                job.error = exc
            except Exception as exc:  # noqa: BLE001
                logger.exception("Model call for step %s crashed", job.step.step_key)
                job.error = AgentRunError(f"The model call failed ({type(exc).__name__}).", retryable=True, kind="crash")
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _finalize_job(db: DBSession, workflow: AgentWorkflow, job: _Job, ctx: AgentContext) -> None:
    try:
        raw = job.prepared.static_result if job.prepared.prompt is None else job.llm_result.data
        try:
            output = job.spec.output_model.model_validate(raw)
        except ValidationError as exc:
            raise AgentOutputError(f"The model output is missing required fields or has the wrong shape: {_validation_summary(exc)}") from exc
        finalized: Finalized = job.spec.finalize(ctx, job.prepared, output)
        usage = job.llm_result.usage if job.llm_result else None
        _complete(
            db, workflow, job.step, job.execution,
            result=finalized.result,
            evidence=finalized.evidence,
            warnings=list(job.prepared.warnings) + list(finalized.warnings),
            usage=usage,
            model=job.llm_result.model if job.llm_result else None,
            duration_ms=job.duration_ms,
        )
        db.commit()
    except AgentRunError as exc:
        job.error = exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Validating step %s of workflow %s crashed", job.step.step_key, workflow.id)
        db.rollback()
        job.error = AgentRunError(f"The agent output could not be validated ({type(exc).__name__}).", retryable=True, delay_seconds=0, kind="crash")


def _agent_batch(
    db: DBSession, workflow: AgentWorkflow, batch: list[AgentWorkflowStep], definition: W.WorkflowDef, ctx: AgentContext,
    steps: list[AgentWorkflowStep], settings: Settings, llm_factory: LLMFactory,
) -> _BatchOutcome:
    jobs = [_Job(step=step) for step in batch]
    for job in jobs:
        _prepare_job(db, workflow, job, definition, ctx, steps, settings)
    if any(job.error is None and job.prepared and job.prepared.prompt for job in jobs):
        try:
            llm = llm_factory(db, workflow.workspace_id, settings)
        except AgentRunError as exc:
            llm = None
            for job in jobs:
                if job.error is None and job.prepared and job.prepared.prompt:
                    job.error = exc
        if llm is not None:
            _infer(jobs, llm, settings)
    for job in jobs:
        if job.error is None:
            _finalize_job(db, workflow, job, ctx)

    outcome = _BatchOutcome()
    for job in jobs:
        if job.error is None:
            continue
        step = db.get(AgentWorkflowStep, job.step.id, populate_existing=True)
        execution = db.get(AgentExecution, job.execution.id, populate_existing=True) if job.execution is not None else None
        _record_failure(db, workflow, step, execution, str(job.error), duration_ms=job.duration_ms)
        max_attempts = (job.spec.limits.max_attempts if job.spec else None) or settings.agent_max_step_attempts
        if job.error.retryable and step.attempt_count < max_attempts:
            step.status = "pending"
            delay = job.error.delay_seconds
            if delay is None:
                delay = backoff_seconds(step.attempt_count, settings)
            if delay > 0:
                outcome.retry_delay = max(outcome.retry_delay or 0, delay)
        else:
            step.status = "failed"
            label = job.spec.name if job.spec else step.label
            suffix = f" (after {step.attempt_count} attempts)" if step.attempt_count > 1 else ""
            outcome.failure = outcome.failure or f"{label} failed{suffix}: {job.error}"
    db.commit()
    return outcome


# The run loop ---------------------------------------------------------------------


def _actor(db: DBSession, workflow: AgentWorkflow) -> tuple[User, WorkspaceMembership] | None:
    """The member whose permissions the workflow runs with: the person who started it."""
    if workflow.created_by is None:
        return None
    membership = (
        db.query(WorkspaceMembership)
        .filter(WorkspaceMembership.workspace_id == workflow.workspace_id, WorkspaceMembership.user_id == workflow.created_by)
        .first()
    )
    if membership is None or not membership.user.is_active:
        return None
    return membership.user, membership


def _reset_interrupted(db: DBSession, workflow: AgentWorkflow) -> None:
    """After a worker restart: the step that was running starts again; finished steps are kept."""
    for step in _steps(db, workflow):
        if step.status == "running":
            step.status = "pending"
    interrupted = (
        db.query(AgentExecution)
        .filter(AgentExecution.workflow_id == workflow.id, AgentExecution.status == "running")
        .all()
    )
    for execution in interrupted:
        execution.status = "failed"
        execution.completed_at = utc_now()
        execution.error_message = "Interrupted by a worker restart; the step was run again."
    db.commit()


def _next_batch(steps: list[AgentWorkflowStep], max_parallel: int) -> list[AgentWorkflowStep]:
    status = {step.step_key: step.status for step in steps}
    ready = [
        step
        for step in steps
        if step.status == "pending"
        and all(status.get(dep) == "succeeded" for dep in (step.dependency_configuration or {}).get("depends_on") or [])
    ]
    if not ready:
        return []
    first = ready[0]
    group = (first.dependency_configuration or {}).get("parallel_group")
    if first.kind != "agent" or not group or max_parallel <= 1:
        return [first]
    same = [
        step
        for step in ready
        if step.kind == "agent"
        and (step.dependency_configuration or {}).get("parallel_group") == group
        and step.revision_round == first.revision_round
    ]
    return same[:max_parallel]


def run_workflow(
    db: DBSession,
    workflow_id: UUID,
    *,
    worker_id: str = "agents",
    now: datetime | None = None,
    llm_factory: LLMFactory | None = None,
) -> str | None:
    """Claim and run one workflow as far as it can go. Returns its status, or None if not claimed."""
    settings = get_settings()
    clock: Callable[[], datetime] = (lambda: now) if now is not None else utc_now
    if not claim_workflow(db, workflow_id, worker_id=worker_id, now=clock()):
        return None
    workflow = db.get(AgentWorkflow, workflow_id, populate_existing=True)
    if workflow is None:
        return None
    workflow.started_at = workflow.started_at or clock()
    if workflow.deadline_at is None:
        workflow.deadline_at = clock() + timedelta(seconds=settings.agent_max_workflow_seconds)
    workflow.next_attempt_at = None
    db.commit()
    _reset_interrupted(db, workflow)

    try:
        definition = W.get_workflow(workflow.workflow_type)
    except W.UnknownWorkflowError as exc:
        return _fail(db, workflow, str(exc), now=clock())
    actor = _actor(db, workflow)
    if actor is None:
        return _fail(db, workflow, "The member who started this workflow no longer has access to the workspace.", now=clock())
    ctx = AgentContext(db=db, workflow=workflow, actor=actor[0], membership=actor[1], settings=settings)
    llm_factory = llm_factory or default_llm_factory

    while True:
        db.refresh(workflow)
        if workflow.cancel_requested:
            return _cancel(db, workflow, now=clock())
        if not settings.agents_enabled:
            return _fail(db, workflow, "AI agent workflows are disabled on this server.", now=clock())
        if clock() > _utc(workflow.deadline_at):
            return _fail(
                db, workflow, f"The workflow exceeded its time limit of {settings.agent_max_workflow_seconds} seconds.", now=clock()
            )
        steps = _steps(db, workflow)
        batch = _next_batch(steps, settings.agent_max_parallel_calls)
        if not batch:
            if all(step.status == "succeeded" for step in steps):
                return _succeed(db, workflow, steps, now=clock())
            return _fail(db, workflow, "The workflow has no runnable steps left.", now=clock())
        if batch[0].kind == "agent":
            outcome = _agent_batch(db, workflow, batch, definition, ctx, steps, settings, llm_factory)
        else:
            outcome = _system_step(db, workflow, batch[0], definition, ctx, steps, settings)
        if outcome.failure:
            return _fail(db, workflow, outcome.failure, now=clock())
        if outcome.retry_delay:
            workflow.status = "pending"
            workflow.next_attempt_at = clock() + timedelta(seconds=outcome.retry_delay)
            workflow.error_message = "Waiting to retry after a temporary Groq limit or outage."
            _release(workflow)
            db.commit()
            return "pending"
        # Renew the lease between steps so a long workflow is not taken over by another worker.
        workflow.lease_expires_at = utc_now() + timedelta(seconds=settings.agent_lease_seconds)
        workflow.error_message = None
        db.commit()


def _succeed(db: DBSession, workflow: AgentWorkflow, steps: list[AgentWorkflowStep], *, now: datetime) -> str:
    final: dict[str, Any] | None = None
    for step in reversed(steps):
        if step.kind == "compile" and step.execution_id is not None:
            execution = db.get(AgentExecution, step.execution_id)
            result = (execution.output_data or {}).get("result") if execution else None
            if result and result.get("decision") != "revision_requested":
                final = result
                break
    if final is None:
        return _fail(db, workflow, "The workflow finished without a compiled deliverable.", now=now)
    final["usage"] = {
        "agent_calls": workflow.agent_call_count,
        "prompt_tokens": workflow.prompt_tokens,
        "completion_tokens": workflow.completion_tokens,
        "total_tokens": workflow.total_tokens,
    }
    workflow.final_output = final
    _finish(db, workflow, status="succeeded", now=now)
    db.commit()
    return "succeeded"


def run_due_workflows(
    db: DBSession, *, worker_id: str = "agents", now: datetime | None = None, limit: int = 5, llm_factory: LLMFactory | None = None
) -> int:
    if not get_settings().agents_enabled:
        return 0
    handled = 0
    for workflow_id in due_workflow_ids(db, now=now, limit=limit):
        try:
            if run_workflow(db, workflow_id, worker_id=worker_id, now=now, llm_factory=llm_factory) is not None:
                handled += 1
        except Exception:  # noqa: BLE001 - one bad workflow must not stop the others
            logger.exception("Agent workflow %s failed unexpectedly", workflow_id)
            db.rollback()
    return handled
