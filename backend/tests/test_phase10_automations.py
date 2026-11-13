"""Phase 10: controlled workflow automations (triggers, conditions, actions, safety, dry run, notifications)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from app.core.config import get_settings
from app.models import (
    Automation,
    AutomationEvent,
    AutomationExecution,
    ContentApproval,
    ContentProject,
    ContentTask,
    Notification,
    WorkspaceMembership,
)
from app.models.analytics import AnalyticsSyncJob
from app.services.automation import actions as A
from app.services.automation import engine, events
from app.services.automation.conditions import ConditionError, evaluate_conditions, validate_conditions
from app.services.automation.registry import TRIGGERS, UnknownTriggerError, get_trigger, normalize_payload
from app.services.automation.reminders import emit_due_approval_reminders
from app.services.automation import worker_tasks as automation_tasks
from app.worker import run_once
from publishing_helpers import CSRF, FakeMeta, add_member, connect_account, create_approved_content, create_workspace, meta_error, register, run_job

UTC = timezone.utc


# Helpers ---------------------------------------------------------------------------


def me(client) -> dict:
    return client.get("/api/v1/auth/me").json()["user"]


def setup_workspace(client_factory, db_factory):
    owner = client_factory()
    register(owner, "owner@example.com")
    workspace_id = create_workspace(owner, "Automation workspace")
    member = client_factory()
    register(member, "member@example.com")
    add_member(owner, workspace_id, "member@example.com")
    return owner, member, workspace_id


def create_automation(client, workspace_id: str, **overrides) -> dict:
    body = {
        "name": "Notify reviewers",
        "description": "Tell admins when content is submitted.",
        "trigger_type": "CONTENT_SUBMITTED_FOR_APPROVAL",
        "actions": [
            {"action_type": "notify_admins", "configuration": {"message": "“{title}” is waiting for review."}},
            {"action_type": "add_label", "configuration": {"label": "needs-review"}},
        ],
        **overrides,
    }
    response = client.post(f"/api/v1/workspaces/{workspace_id}/automations", json=body, headers=CSRF)
    assert response.status_code == 201, response.text
    return response.json()


def enable(client, workspace_id: str, automation_id: str) -> dict:
    response = client.post(f"/api/v1/workspaces/{workspace_id}/automations/{automation_id}/enable", json={}, headers=CSRF)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "enabled"
    return response.json()


def create_project(client, workspace_id: str, title: str = "Launch post", **extra) -> dict:
    response = client.post(
        "/api/v1/content/projects",
        json={"workspace_id": workspace_id, "title": title, "selected_platforms": ["facebook"], **extra},
        headers=CSRF,
    )
    assert response.status_code == 201, response.text
    return response.json()


def submit(client, project_id: str) -> dict:
    draft = client.post(
        f"/api/v1/content/projects/{project_id}/drafts",
        json={"platform": "facebook", "title": "Launch", "body": "We launched.", "hashtags": ["#launch"]},
        headers=CSRF,
    )
    assert draft.status_code == 201, draft.text
    response = client.post(f"/api/v1/content/projects/{project_id}/submit-for-approval", json={}, headers=CSRF)
    assert response.status_code == 200, response.text
    return response.json()


def process_all(db_factory, *, now: datetime | None = None, worker_id: str = "test-worker") -> tuple[int, int]:
    with db_factory() as db:
        dispatched = engine.dispatch_events(db, worker_id=worker_id, now=now)
        executed = engine.run_executions(db, worker_id=worker_id, now=now)
    return dispatched, executed


def events_of(db_factory, event_type: str) -> list[AutomationEvent]:
    with db_factory() as db:
        rows = db.query(AutomationEvent).filter(AutomationEvent.event_type == event_type).order_by(AutomationEvent.occurred_at).all()
        for row in rows:
            db.expunge(row)
        return rows


def executions_of(db_factory, automation_id: str) -> list[AutomationExecution]:
    with db_factory() as db:
        rows = (
            db.query(AutomationExecution)
            .filter(AutomationExecution.automation_id == UUID(automation_id))
            .order_by(AutomationExecution.created_at)
            .all()
        )
        for row in rows:
            _ = row.steps
            db.expunge(row)
        return rows


# Trigger registry --------------------------------------------------------------------


def test_trigger_registry_is_stable_and_normalizes_payloads():
    expected = {
        "CONTENT_CREATED", "CONTENT_SUBMITTED_FOR_APPROVAL", "CONTENT_APPROVED", "CONTENT_REJECTED", "CONTENT_UPDATED",
        "POST_SCHEDULED", "POST_PUBLISHING", "POST_PUBLISHED", "POST_PUBLISH_FAILED", "POST_CANCELLED",
        "ANALYTICS_SYNC_COMPLETED", "ANALYTICS_SYNC_FAILED", "TEAM_MEMBER_ASSIGNED", "APPROVAL_REMINDER_DUE",
    }
    assert set(TRIGGERS) == expected
    for spec in TRIGGERS.values():
        normalized = normalize_payload(spec, spec.sample)
        assert set(normalized) == {field.name for field in spec.fields}
    spec = get_trigger("POST_PUBLISH_FAILED")
    payload = normalize_payload(spec, {"attempt_count": "3", "platform": "facebook", "access_token": "secret", "requires_user_action": "true", "unknown": 1})
    assert payload["attempt_count"] == 3 and payload["requires_user_action"] is True
    assert "access_token" not in payload and "unknown" not in payload
    assert normalize_payload(spec, {"attempt_count": "many"})["attempt_count"] is None
    with pytest.raises(UnknownTriggerError):
        get_trigger("SOMETHING_ELSE")


def test_emit_rejects_unknown_triggers_and_deduplicates(client_factory, db_factory):
    owner, _member, workspace_id = setup_workspace(client_factory, db_factory)
    with db_factory() as db:
        assert events.emit(db, "NOT_A_TRIGGER", workspace_id=UUID(workspace_id), payload={}) is None
        first = events.emit(db, "CONTENT_CREATED", workspace_id=UUID(workspace_id), payload={"title": "A"}, dedupe_key="content_created:x")
        second = events.emit(db, "CONTENT_CREATED", workspace_id=UUID(workspace_id), payload={"title": "A"}, dedupe_key="content_created:x")
        db.commit()
        assert first is not None and second is None
        assert db.query(AutomationEvent).count() == 1
    settings = get_settings()
    with db_factory() as db, pytest.MonkeyPatch.context() as patch:
        patch.setattr(settings, "automation_enabled", False)
        assert events.emit(db, "CONTENT_CREATED", workspace_id=UUID(workspace_id), payload={}) is None


# Conditions ------------------------------------------------------------------------


def test_conditions_validate_fields_operators_types_and_limits(monkeypatch):
    spec = get_trigger("POST_PUBLISH_FAILED")
    valid = validate_conditions(
        spec,
        {"logic": "and", "rules": [
            {"field": "platform", "operator": "equals", "value": "facebook"},
            {"logic": "or", "rules": [
                {"field": "error_category", "operator": "in", "value": ["token_expired", "permission"]},
                {"field": "attempt_count", "operator": "greater_than", "value": 2},
            ]},
        ]},
    )
    assert valid["rules"][1]["logic"] == "or"
    assert validate_conditions(spec, None) == {"logic": "and", "rules": []}

    with pytest.raises(ConditionError, match="unknown field"):
        validate_conditions(spec, {"rules": [{"field": "secret", "operator": "equals", "value": "x"}]})
    with pytest.raises(ConditionError, match="not supported"):
        validate_conditions(spec, {"rules": [{"field": "attempt_count", "operator": "contains", "value": 1}]})
    with pytest.raises(ConditionError, match="must be a number"):
        validate_conditions(spec, {"rules": [{"field": "attempt_count", "operator": "greater_than", "value": "two"}]})
    with pytest.raises(ConditionError, match="must be one of"):
        validate_conditions(spec, {"rules": [{"field": "platform", "operator": "equals", "value": "tiktok"}]})
    with pytest.raises(ConditionError, match="logic must be"):
        validate_conditions(spec, {"logic": "xor", "rules": []})
    with pytest.raises(ConditionError, match="non-empty list"):
        validate_conditions(spec, {"rules": [{"field": "platform", "operator": "in", "value": "facebook"}]})
    with pytest.raises(ConditionError, match="does not take a value"):
        validate_conditions(spec, {"rules": [{"field": "error_code", "operator": "is_empty", "value": "x"}]})
    with pytest.raises(ConditionError, match="unknown keys"):
        validate_conditions(spec, {"rules": [{"field": "platform", "operator": "equals", "value": "facebook", "eval": "1"}]})

    settings = get_settings()
    monkeypatch.setattr(settings, "automation_max_conditions", 2)
    with pytest.raises(ConditionError, match="Too many conditions"):
        validate_conditions(spec, {"rules": [{"field": "platform", "operator": "equals", "value": "facebook"}] * 3})
    monkeypatch.setattr(settings, "automation_max_condition_depth", 1)
    with pytest.raises(ConditionError, match="nested too deeply"):
        validate_conditions(spec, {"rules": [{"logic": "or", "rules": [{"field": "platform", "operator": "equals", "value": "facebook"}]}]})


def test_conditions_evaluate_and_or_and_every_operator():
    spec = get_trigger("POST_PUBLISH_FAILED")
    payload = normalize_payload(spec, {**spec.sample, "platform": "Facebook", "attempt_count": 3, "error_code": None, "requires_user_action": True})
    tree = validate_conditions(spec, {"logic": "and", "rules": [
        {"field": "platform", "operator": "equals", "value": "facebook"},
        {"logic": "or", "rules": [
            {"field": "attempt_count", "operator": "greater_than_or_equal", "value": 5},
            {"field": "error_category", "operator": "in", "value": ["token_expired"]},
        ]},
        {"field": "error_code", "operator": "is_empty"},
        {"field": "requires_user_action", "operator": "equals", "value": True},
        {"field": "title", "operator": "contains", "value": "launch"},
        {"field": "source", "operator": "not_in", "value": ["manual"]},
    ]})
    result = evaluate_conditions(spec, tree, payload)
    assert result.passed and result.as_dict()["children"][1]["logic"] == "or"
    failing = validate_conditions(spec, {"logic": "or", "rules": [
        {"field": "attempt_count", "operator": "less_than", "value": 1},
        {"field": "platform", "operator": "not_equals", "value": "facebook"},
    ]})
    assert not evaluate_conditions(spec, failing, payload).passed
    content = get_trigger("CONTENT_CREATED")
    content_payload = normalize_payload(content, {**content.sample, "platforms": ["facebook"], "labels": []})
    assert evaluate_conditions(content, validate_conditions(content, {"rules": [{"field": "platforms", "operator": "contains", "value": "facebook"}, {"field": "labels", "operator": "is_empty"}]}), content_payload).passed
    assert not evaluate_conditions(content, validate_conditions(content, {"rules": [{"field": "platforms", "operator": "not_contains", "value": "facebook"}]}), content_payload).passed


# API: management, permissions, validation -------------------------------------------


def test_automation_crud_permissions_and_validation(client_factory, db_factory):
    owner, member, workspace_id = setup_workspace(client_factory, db_factory)
    catalog = owner.get(f"/api/v1/workspaces/{workspace_id}/automations/catalog").json()
    assert {item["type"] for item in catalog["triggers"]} == set(TRIGGERS)
    assert {item["type"] for item in catalog["actions"]} == set(A.ACTIONS)
    assert catalog["limits"]["max_actions"] == get_settings().automation_max_actions

    # Members can read but not manage.
    forbidden = member.post(f"/api/v1/workspaces/{workspace_id}/automations", json={"name": "X", "trigger_type": "CONTENT_CREATED", "actions": []}, headers=CSRF)
    assert forbidden.status_code == 403
    automation = create_automation(owner, workspace_id)
    assert automation["status"] == "draft" and automation["can_enable"] is True
    assert member.get(f"/api/v1/workspaces/{workspace_id}/automations").status_code == 200
    assert member.post(f"/api/v1/workspaces/{workspace_id}/automations/{automation['id']}/enable", json={}, headers=CSRF).status_code == 403

    # Invalid definitions are rejected with explicit errors.
    bad_trigger = owner.post(f"/api/v1/workspaces/{workspace_id}/automations", json={"name": "Bad", "trigger_type": "RUN_SHELL", "actions": []}, headers=CSRF)
    assert bad_trigger.status_code == 422 and "Unknown trigger" in bad_trigger.text
    bad_action = owner.post(
        f"/api/v1/workspaces/{workspace_id}/automations",
        json={"name": "Bad", "trigger_type": "CONTENT_CREATED", "actions": [{"action_type": "http_request", "configuration": {"url": "https://x"}}]},
        headers=CSRF,
    )
    assert bad_action.status_code == 422 and "not allowed" in bad_action.text
    bad_config = owner.post(
        f"/api/v1/workspaces/{workspace_id}/automations",
        json={"name": "Bad", "trigger_type": "CONTENT_CREATED", "actions": [{"action_type": "notify_admins", "configuration": {"message": "hi", "shell": "rm"}}]},
        headers=CSRF,
    )
    assert bad_config.status_code == 422
    wrong_trigger_action = owner.post(
        f"/api/v1/workspaces/{workspace_id}/automations",
        json={"name": "Bad", "trigger_type": "ANALYTICS_SYNC_FAILED", "actions": [{"action_type": "add_label", "configuration": {"label": "x"}}]},
        headers=CSRF,
    )
    assert wrong_trigger_action.status_code == 422 and "cannot be used with the trigger" in wrong_trigger_action.text
    bad_placeholder = owner.post(
        f"/api/v1/workspaces/{workspace_id}/automations",
        json={"name": "Bad", "trigger_type": "CONTENT_CREATED", "actions": [{"action_type": "notify_admins", "configuration": {"message": "{access_token}"}}]},
        headers=CSRF,
    )
    assert bad_placeholder.status_code == 422 and "unknown placeholder" in bad_placeholder.text
    stranger = owner.post(
        f"/api/v1/workspaces/{workspace_id}/automations",
        json={"name": "Bad", "trigger_type": "CONTENT_CREATED", "actions": [{"action_type": "notify_member", "configuration": {"user_id": str(uuid4()), "message": "x"}}]},
        headers=CSRF,
    )
    assert stranger.status_code == 422 and "does not belong" in stranger.text
    bad_condition = owner.post(
        f"/api/v1/workspaces/{workspace_id}/automations",
        json={"name": "Bad", "trigger_type": "CONTENT_CREATED", "conditions": {"rules": [{"field": "nope", "operator": "equals", "value": 1}]}, "actions": []},
        headers=CSRF,
    )
    assert bad_condition.status_code == 422 and "unknown field" in bad_condition.text
    validation = owner.post(
        f"/api/v1/workspaces/{workspace_id}/automations/validate",
        json={"name": "Check", "trigger_type": "CONTENT_CREATED", "actions": [{"action_type": "notify_admins", "configuration": {"message": "ok"}}]},
        headers=CSRF,
    ).json()
    assert validation["valid"] and "No conditions" in validation["warnings"][0]

    # Lifecycle: enable → pause → resume → archive → delete; edit, duplicate.
    enable(owner, workspace_id, automation["id"])
    empty = owner.post(f"/api/v1/workspaces/{workspace_id}/automations", json={"name": "Empty", "trigger_type": "CONTENT_CREATED", "actions": []}, headers=CSRF).json()
    assert owner.post(f"/api/v1/workspaces/{workspace_id}/automations/{empty['id']}/enable", json={}, headers=CSRF).status_code == 422
    paused = owner.post(f"/api/v1/workspaces/{workspace_id}/automations/{automation['id']}/pause", json={}, headers=CSRF).json()
    assert paused["status"] == "paused" and paused["paused_at"]
    resumed = owner.post(f"/api/v1/workspaces/{workspace_id}/automations/{automation['id']}/resume", json={}, headers=CSRF).json()
    assert resumed["status"] == "enabled"
    edited = owner.patch(f"/api/v1/workspaces/{workspace_id}/automations/{automation['id']}", json={"name": "Renamed", "cooldown_seconds": 60}, headers=CSRF).json()
    assert edited["name"] == "Renamed" and edited["cooldown_seconds"] == 60
    copy = owner.post(f"/api/v1/workspaces/{workspace_id}/automations/{automation['id']}/duplicate", json={}, headers=CSRF).json()
    assert copy["status"] == "draft" and copy["name"] == "Renamed (copy)" and len(copy["actions"]) == 2
    assert owner.delete(f"/api/v1/workspaces/{workspace_id}/automations/{automation['id']}", headers=CSRF).status_code == 409
    archived = owner.post(f"/api/v1/workspaces/{workspace_id}/automations/{automation['id']}/archive", json={}, headers=CSRF).json()
    assert archived["status"] == "archived"
    assert owner.patch(f"/api/v1/workspaces/{workspace_id}/automations/{automation['id']}", json={"name": "Nope"}, headers=CSRF).status_code == 409
    assert owner.delete(f"/api/v1/workspaces/{workspace_id}/automations/{automation['id']}", headers=CSRF).status_code == 204
    listed = owner.get(f"/api/v1/workspaces/{workspace_id}/automations").json()
    assert {item["name"] for item in listed} == {"Empty", "Renamed (copy)"}


def test_cross_workspace_isolation(client_factory, db_factory):
    owner, _member, workspace_id = setup_workspace(client_factory, db_factory)
    other = client_factory()
    register(other, "other@example.com")
    other_workspace = create_workspace(other, "Other")
    automation = create_automation(owner, workspace_id)
    enable(owner, workspace_id, automation["id"])
    assert other.get(f"/api/v1/workspaces/{workspace_id}/automations").status_code == 404
    assert other.get(f"/api/v1/workspaces/{other_workspace}/automations/{automation['id']}").status_code == 404
    assert other.post(f"/api/v1/workspaces/{other_workspace}/automations/{automation['id']}/enable", json={}, headers=CSRF).status_code == 404
    # An event in the other workspace never reaches this workspace's automation.
    submit(other, create_project(other, other_workspace)["id"])
    process_all(db_factory)
    assert executions_of(db_factory, automation["id"]) == []
    events_other = events_of(db_factory, "CONTENT_SUBMITTED_FOR_APPROVAL")
    assert len(events_other) == 1 and events_other[0].status == "processed" and events_other[0].dispatch_summary == []
    # Members of the other workspace cannot be used as recipients here.
    other_id = me(other)["id"]
    response = owner.post(
        f"/api/v1/workspaces/{workspace_id}/automations",
        json={"name": "Leak", "trigger_type": "CONTENT_CREATED", "actions": [{"action_type": "notify_member", "configuration": {"user_id": other_id, "message": "x"}}]},
        headers=CSRF,
    )
    assert response.status_code == 422


# End-to-end execution -----------------------------------------------------------------


def test_submitted_content_notifies_admins_and_labels_project(client_factory, db_factory):
    owner, member, workspace_id = setup_workspace(client_factory, db_factory)
    automation = create_automation(
        owner,
        workspace_id,
        conditions={"rules": [{"field": "platforms", "operator": "contains", "value": "facebook"}]},
    )
    enable(owner, workspace_id, automation["id"])
    project = create_project(member, workspace_id, "Big launch")
    submit(member, project["id"])

    pending = events_of(db_factory, "CONTENT_SUBMITTED_FOR_APPROVAL")
    assert len(pending) == 1 and pending[0].status == "pending" and pending[0].event_payload["title"] == "Big launch"
    # The worker loop picks the work up through the registered periodic tasks.
    tasks: list = []
    automation_tasks.register(tasks)
    assert run_once(db_factory, worker_id="w1", tasks=tasks) >= 2

    executions = executions_of(db_factory, automation["id"])
    assert len(executions) == 1 and executions[0].status == "succeeded"
    assert [step.status for step in executions[0].steps] == ["succeeded", "succeeded"]
    assert "Notified 1 member" in executions[0].steps[0].result_summary["summary"]
    notifications = owner.get(f"/api/v1/workspaces/{workspace_id}/notifications").json()
    assert notifications["unread_count"] == 1
    assert "Big launch" in notifications["items"][0]["message"]
    assert member.get(f"/api/v1/workspaces/{workspace_id}/notifications").json()["unread_count"] == 0
    assert owner.get(f"/api/v1/content/projects/{project['id']}").json()["labels"] == ["needs-review"]

    detail = owner.get(f"/api/v1/workspaces/{workspace_id}/automations/{automation['id']}").json()
    assert detail["execution_count"] == 1 and detail["success_count"] == 1 and detail["last_execution"]["status"] == "succeeded"
    listed = owner.get(f"/api/v1/workspaces/{workspace_id}/automation-executions?automation_id={automation['id']}").json()
    assert len(listed) == 1
    single = owner.get(f"/api/v1/workspaces/{workspace_id}/automation-executions/{listed[0]['id']}").json()
    assert single["execution_context"]["payload"]["project_id"] == project["id"] and len(single["steps"]) == 2

    # Duplicate delivery: re-dispatching the same event or re-emitting it creates nothing new.
    with db_factory() as db:
        event = db.query(AutomationEvent).filter(AutomationEvent.event_type == "CONTENT_SUBMITTED_FOR_APPROVAL").one()
        event.status = "pending"
        db.commit()
        summary = engine.dispatch_event(db, event.id, worker_id="w2")
    assert summary[0]["outcome"] == "duplicate"
    assert len(executions_of(db_factory, automation["id"])) == 1
    assert owner.get(f"/api/v1/workspaces/{workspace_id}/notifications").json()["unread_count"] == 1

    # Rejection notifies the creator through the "content owner" action.
    reject = create_automation(
        owner,
        workspace_id,
        name="Tell the author",
        trigger_type="CONTENT_REJECTED",
        actions=[{"action_type": "notify_content_owner", "configuration": {"target": "creator", "message": "“{title}” was {decision}."}}],
    )
    enable(owner, workspace_id, reject["id"])
    approval_id = owner.get(f"/api/v1/content/projects/{project['id']}/approvals").json()[0]["id"]
    decided = owner.post(f"/api/v1/content/projects/{project['id']}/approvals/{approval_id}/decision", json={"status": "rejected", "comments": "No."}, headers=CSRF)
    assert decided.status_code == 200
    process_all(db_factory)
    mine = member.get(f"/api/v1/workspaces/{workspace_id}/notifications").json()
    assert mine["unread_count"] == 1 and "was rejected" in mine["items"][0]["message"]
    marked = member.post(f"/api/v1/workspaces/{workspace_id}/notifications/{mine['items'][0]['id']}/read", json={}, headers=CSRF)
    assert marked.status_code == 200 and marked.json()["read_at"]
    assert owner.post(f"/api/v1/workspaces/{workspace_id}/notifications/{mine['items'][0]['id']}/read", json={}, headers=CSRF).status_code == 404
    assert owner.post(f"/api/v1/workspaces/{workspace_id}/notifications/read-all", json={}, headers=CSRF).json()["unread_count"] == 0


def test_publish_failure_records_incident_and_scheduling_publishing_events(client_factory, db_factory, token_key):
    owner, _member, workspace_id = setup_workspace(client_factory, db_factory)
    incident = create_automation(
        owner,
        workspace_id,
        name="Publishing incidents",
        trigger_type="POST_PUBLISH_FAILED",
        conditions={"rules": [{"field": "platform", "operator": "equals", "value": "facebook"}]},
        actions=[
            {"action_type": "record_publishing_incident", "configuration": {"severity": "high", "note": "Code {error_code}"}},
            {"action_type": "create_task", "configuration": {"title": "Fix {title}", "kind": "followup", "assignee_type": "requester", "due_in_hours": 24}},
        ],
    )
    enable(owner, workspace_id, incident["id"])
    no_creator = owner.post(
        f"/api/v1/workspaces/{workspace_id}/automations",
        json={"name": "Bad", "trigger_type": "POST_PUBLISH_FAILED", "actions": [{"action_type": "notify_content_owner", "configuration": {"target": "creator", "message": "x"}}]},
        headers=CSRF,
    )
    assert no_creator.status_code == 422 and "has no creator" in no_creator.text
    content = create_approved_content(owner, workspace_id, platforms=("facebook",))
    account = connect_account(db_factory, workspace_id)
    job = owner.post(
        f"/api/v1/content/drafts/{content['drafts']['facebook']}/publish",
        json={"social_account_id": account, "confirm": True, "idempotency_key": "auto-test-0001"},
        headers=CSRF,
    )
    assert job.status_code == 202, job.text
    fake = FakeMeta({("POST", "/page-1/feed"): meta_error(400, 100, "Invalid parameter")})
    assert run_job(db_factory, job.json()["id"], fake) == "failed"

    assert len(events_of(db_factory, "POST_PUBLISHING")) == 1
    failed = events_of(db_factory, "POST_PUBLISH_FAILED")
    assert len(failed) == 1 and failed[0].event_payload["publication_id"] == job.json()["id"]
    process_all(db_factory)
    executions = executions_of(db_factory, incident["id"])
    assert len(executions) == 1 and executions[0].status == "succeeded", executions[0].error_message
    tasks = owner.get(f"/api/v1/workspaces/{workspace_id}/tasks").json()
    kinds = {task["kind"]: task for task in tasks}
    assert set(kinds) == {"incident", "followup"}
    assert kinds["incident"]["severity"] == "high" and "Code 100" in kinds["incident"]["description"]
    assert kinds["followup"]["title"] == "Fix Launch post" and kinds["followup"]["due_at"]
    assert kinds["followup"]["assigned_to"] == me(owner)["id"]
    assert owner.get(f"/api/v1/workspaces/{workspace_id}/notifications").json()["unread_count"] == 2  # incident + task
    done = owner.post(f"/api/v1/workspaces/{workspace_id}/tasks/{kinds['followup']['id']}/complete", json={}, headers=CSRF).json()
    assert done["status"] == "done"
    # Approval and publishing rules are untouched: the job stayed failed and content stayed approved.
    assert owner.get(f"/api/v1/publishing/jobs/{job.json()['id']}").json()["status"] == "failed"
    assert owner.get(f"/api/v1/content/projects/{content['project_id']}").json()["status"] == "approved"


def test_scheduling_and_analytics_events_are_emitted(client_factory, db_factory, token_key):
    owner, _member, workspace_id = setup_workspace(client_factory, db_factory)
    content = create_approved_content(owner, workspace_id, platforms=("facebook",))
    account = connect_account(db_factory, workspace_id)
    local = (datetime.now(UTC) + timedelta(days=2)).strftime("%Y-%m-%dT09:30")
    scheduled = owner.post(
        f"/api/v1/workspaces/{workspace_id}/scheduled-posts",
        json={"draft_id": content["drafts"]["facebook"], "social_account_id": account, "scheduled_local": local, "timezone": "UTC", "confirm": True},
        headers=CSRF,
    )
    assert scheduled.status_code == 201, scheduled.text
    posted = events_of(db_factory, "POST_SCHEDULED")
    assert len(posted) == 1 and posted[0].event_payload["scheduled_post_id"] == scheduled.json()["id"]

    with db_factory() as db:
        for status in ("failed", "failed"):
            job = AnalyticsSyncJob(workspace_id=UUID(workspace_id), social_account_id=UUID(account), platform="facebook_page", status=status, trigger="scheduled", attempt_count=3, max_attempts=3, error_category="token_expired", error_code="190")
            db.add(job)
            db.flush()
            events.emit_sync_finished(db, job)
        db.commit()
    failed = events_of(db_factory, "ANALYTICS_SYNC_FAILED")
    assert [event.event_payload["consecutive_failures"] for event in failed] == [1, 2]


# Safety -------------------------------------------------------------------------------


def test_self_trigger_and_chain_depth_are_blocked(client_factory, db_factory, monkeypatch):
    owner, member, workspace_id = setup_workspace(client_factory, db_factory)
    member_id = me(member)["id"]
    owner_id = me(owner)["id"]
    # Assigning emits TEAM_MEMBER_ASSIGNED, which is this automation's own trigger.
    loop = create_automation(
        owner,
        workspace_id,
        name="Reassign",
        trigger_type="TEAM_MEMBER_ASSIGNED",
        actions=[{"action_type": "assign_content", "configuration": {"user_id": owner_id}}],
    )
    enable(owner, workspace_id, loop["id"])
    project = create_project(owner, workspace_id)
    assigned = owner.post(f"/api/v1/content/projects/{project['id']}/assign", json={"user_id": member_id}, headers=CSRF)
    assert assigned.status_code == 200 and assigned.json()["assigned_to"] == member_id
    process_all(db_factory)
    assert owner.get(f"/api/v1/content/projects/{project['id']}").json()["assigned_to"] == owner_id
    process_all(db_factory)
    process_all(db_factory)
    derived = events_of(db_factory, "TEAM_MEMBER_ASSIGNED")
    assert len(derived) == 2  # the manual assignment and the one caused by the automation, nothing after that
    assert derived[1].origin_automation_id == UUID(loop["id"]) and derived[1].chain_depth == 1
    assert derived[1].dispatch_summary[0]["outcome"] == "self_trigger_blocked"
    assert len(executions_of(db_factory, loop["id"])) == 1

    # A second automation reacting to the derived event is cut off by the chain-depth limit.
    monkeypatch.setattr(get_settings(), "automation_max_chain_depth", 0)
    listener = create_automation(
        owner, workspace_id, name="Listener", trigger_type="TEAM_MEMBER_ASSIGNED",
        actions=[{"action_type": "notify_admins", "configuration": {"message": "assigned"}}],
    )
    enable(owner, workspace_id, listener["id"])
    with db_factory() as db:
        event = db.get(AutomationEvent, derived[1].id)
        event.status = "pending"
        db.commit()
        summary = engine.dispatch_event(db, event.id, worker_id="w")
    outcomes = {item["name"]: item["outcome"] for item in summary}
    assert outcomes == {"Listener": "chain_depth_exceeded", "Reassign": "chain_depth_exceeded"}


def test_rate_limits_cooldown_lifetime_cap_and_workspace_limit(client_factory, db_factory, monkeypatch):
    owner, _member, workspace_id = setup_workspace(client_factory, db_factory)
    settings = get_settings()
    automation = create_automation(
        owner, workspace_id, name="Created", trigger_type="CONTENT_CREATED", max_executions=3,
        actions=[{"action_type": "notify_admins", "configuration": {"message": "new"}}],
    )
    enable(owner, workspace_id, automation["id"])
    monkeypatch.setattr(settings, "automation_max_executions_per_hour", 1)
    create_project(owner, workspace_id, "One")
    create_project(owner, workspace_id, "Two")
    process_all(db_factory)
    created = events_of(db_factory, "CONTENT_CREATED")
    assert [event.dispatch_summary[0]["outcome"] for event in created] == ["queued", "rate_limited"]
    monkeypatch.setattr(settings, "automation_max_executions_per_hour", 1000)

    owner.patch(f"/api/v1/workspaces/{workspace_id}/automations/{automation['id']}", json={"cooldown_seconds": 3600}, headers=CSRF)
    create_project(owner, workspace_id, "Three")
    process_all(db_factory)
    assert events_of(db_factory, "CONTENT_CREATED")[-1].dispatch_summary[0]["outcome"] == "cooldown"
    owner.patch(f"/api/v1/workspaces/{workspace_id}/automations/{automation['id']}", json={"cooldown_seconds": 0}, headers=CSRF)

    monkeypatch.setattr(settings, "automation_workspace_max_executions_per_day", 1)
    create_project(owner, workspace_id, "Four")
    process_all(db_factory)
    assert events_of(db_factory, "CONTENT_CREATED")[-1].dispatch_summary[0]["outcome"] == "workspace_limit_reached"
    monkeypatch.setattr(settings, "automation_workspace_max_executions_per_day", 1000)

    with db_factory() as db:
        row = db.get(Automation, UUID(automation["id"]))
        row.execution_count = 3
        db.commit()
    create_project(owner, workspace_id, "Five")
    process_all(db_factory)
    assert events_of(db_factory, "CONTENT_CREATED")[-1].dispatch_summary[0]["outcome"] == "execution_limit_reached"
    assert len(executions_of(db_factory, automation["id"])) == 1


def test_paused_disabled_and_unauthorized_automations_do_not_run(client_factory, db_factory):
    owner, member, workspace_id = setup_workspace(client_factory, db_factory)
    automation = create_automation(
        owner, workspace_id, name="Created", trigger_type="CONTENT_CREATED",
        actions=[{"action_type": "notify_admins", "configuration": {"message": "new"}}],
    )
    # Draft automations never match.
    create_project(owner, workspace_id, "Draft time")
    process_all(db_factory)
    assert events_of(db_factory, "CONTENT_CREATED")[-1].dispatch_summary == []
    enable(owner, workspace_id, automation["id"])
    # Pause after dispatch but before execution: the pending execution is cancelled, not run.
    create_project(owner, workspace_id, "Paused time")
    with db_factory() as db:
        engine.dispatch_events(db, worker_id="w")
    owner.post(f"/api/v1/workspaces/{workspace_id}/automations/{automation['id']}/pause", json={}, headers=CSRF)
    with db_factory() as db:
        engine.run_executions(db, worker_id="w")
    executions = executions_of(db_factory, automation["id"])
    assert len(executions) == 1 and executions[0].status == "cancelled" and "paused" in executions[0].error_message
    assert owner.get(f"/api/v1/workspaces/{workspace_id}/notifications").json()["unread_count"] == 0
    create_project(owner, workspace_id, "Still paused")
    process_all(db_factory)
    assert events_of(db_factory, "CONTENT_CREATED")[-1].dispatch_summary == []

    # An admin-only action stops running when the automation owner loses the role.
    owner.post(f"/api/v1/workspaces/{workspace_id}/automations/{automation['id']}/resume", json={}, headers=CSRF)
    member_id = me(member)["id"]
    owner.patch(f"/api/v1/workspaces/{workspace_id}/members/{member_id}/role", json={"role": "ADMIN"}, headers=CSRF)
    admin_only = create_automation(
        owner, workspace_id, name="Assign", trigger_type="CONTENT_CREATED",
        actions=[{"action_type": "assign_content", "configuration": {"user_id": member_id, "notify": False}}],
    )
    assert member.post(f"/api/v1/workspaces/{workspace_id}/automations/{admin_only['id']}/enable", json={}, headers=CSRF).status_code == 200
    owner.patch(f"/api/v1/workspaces/{workspace_id}/members/{member_id}/role", json={"role": "MEMBER"}, headers=CSRF)
    project = create_project(owner, workspace_id, "After demotion")
    process_all(db_factory)
    executions = executions_of(db_factory, admin_only["id"])
    assert len(executions) == 1 and executions[0].status == "failed" and "requires the Owner or Admin role" in executions[0].error_message
    assert owner.get(f"/api/v1/content/projects/{project['id']}").json()["assigned_to"] is None
    # The owner of the failing automation is told once.
    failures = [item for item in member.get(f"/api/v1/workspaces/{workspace_id}/notifications").json()["items"] if item["category"] == "automation_failure"]
    assert len(failures) == 1
    detail = owner.get(f"/api/v1/workspaces/{workspace_id}/automations/{admin_only['id']}").json()
    assert any("requires the Owner or Admin role" in issue for issue in detail["issues"])


def test_retry_recovery_timeout_and_concurrency(client_factory, db_factory, monkeypatch):
    owner, _member, workspace_id = setup_workspace(client_factory, db_factory)
    settings = get_settings()
    automation = create_automation(
        owner, workspace_id, name="Created", trigger_type="CONTENT_CREATED",
        actions=[
            {"action_type": "notify_admins", "configuration": {"message": "first"}},
            {"action_type": "create_task", "configuration": {"title": "Follow up on {title}"}},
        ],
    )
    enable(owner, workspace_id, automation["id"])
    create_project(owner, workspace_id, "Retry me")

    # Temporary failure in step 2 → retry with backoff; step 1 is not repeated (no duplicate notification).
    calls = {"count": 0}
    original = A.ACTIONS["create_task"].run

    def flaky(ctx, config):
        calls["count"] += 1
        if calls["count"] == 1:
            raise A.ActionRetryable("database busy")
        return original(ctx, config)

    spec = A.ACTIONS["create_task"]
    monkeypatch.setitem(A.ACTIONS, "create_task", replace(spec, run=flaky))
    process_all(db_factory)
    [execution] = executions_of(db_factory, automation["id"])
    assert execution.status == "pending" and execution.retry_count == 1 and execution.next_attempt_at is not None
    assert [step.status for step in execution.steps] == ["succeeded", "failed"]
    later = datetime.now(UTC) + timedelta(hours=1)
    with db_factory() as db:
        engine.run_executions(db, worker_id="w", now=later)
    [execution] = executions_of(db_factory, automation["id"])
    assert execution.status == "succeeded" and [step.status for step in execution.steps] == ["succeeded", "succeeded"]
    assert owner.get(f"/api/v1/workspaces/{workspace_id}/notifications").json()["unread_count"] == 1
    assert len(owner.get(f"/api/v1/workspaces/{workspace_id}/tasks").json()) == 1

    # Permanent failure → failed; a user can retry an eligible failed execution.
    def broken(ctx, config):
        raise A.ActionError("bad config")

    monkeypatch.setitem(A.ACTIONS, "create_task", replace(spec, run=broken))
    create_project(owner, workspace_id, "Fail me")
    process_all(db_factory)
    failed = [item for item in executions_of(db_factory, automation["id"]) if item.status == "failed"]
    assert len(failed) == 1 and "bad config" in failed[0].error_message
    monkeypatch.setitem(A.ACTIONS, "create_task", spec)
    retried = owner.post(f"/api/v1/workspaces/{workspace_id}/automation-executions/{failed[0].id}/retry", json={}, headers=CSRF)
    assert retried.status_code == 200 and retried.json()["status"] == "pending"
    assert owner.post(f"/api/v1/workspaces/{workspace_id}/automation-executions/{failed[0].id}/retry", json={}, headers=CSRF).status_code == 409
    process_all(db_factory)
    assert {item.status for item in executions_of(db_factory, automation["id"])} == {"succeeded"}

    # Crash recovery: a claimed event/execution whose lease expired is picked up again.
    create_project(owner, workspace_id, "Crash")
    with db_factory() as db:
        event = db.query(AutomationEvent).filter(AutomationEvent.status == "pending").one()
        assert engine.claim_event(db, event.id, worker_id="dead", now=datetime.now(UTC))
        assert engine.due_event_ids(db) == []
        after_lease = datetime.now(UTC) + timedelta(seconds=settings.automation_lease_seconds + 5)
        assert engine.due_event_ids(db, now=after_lease) == [event.id]
        engine.dispatch_events(db, worker_id="alive", now=after_lease)
        execution = db.query(AutomationExecution).filter(AutomationExecution.status == "pending").one()
        assert engine.claim_execution(db, execution.id, worker_id="dead", now=after_lease)
        assert engine.due_execution_ids(db, now=after_lease) == []
        recovered_at = after_lease + timedelta(seconds=settings.automation_lease_seconds + 5)
        assert engine.due_execution_ids(db, now=recovered_at) == [execution.id]
        assert engine.run_execution(db, execution.id, worker_id="alive", now=recovered_at) == "succeeded"

    # Concurrency: with one slot, a second execution of the same automation is not claimed while one runs.
    monkeypatch.setattr(settings, "automation_max_concurrent_executions", 1)
    create_project(owner, workspace_id, "Slot A")
    create_project(owner, workspace_id, "Slot B")
    with db_factory() as db:
        engine.dispatch_events(db, worker_id="w")
        pending = db.query(AutomationExecution).filter(AutomationExecution.status == "pending").order_by(AutomationExecution.created_at).all()
        assert len(pending) == 2
        now = datetime.now(UTC)
        assert engine.claim_execution(db, pending[0].id, worker_id="w1", now=now)
        assert not engine.claim_execution(db, pending[1].id, worker_id="w2", now=now)
        db.get(AutomationExecution, pending[0].id).lease_expires_at = now - timedelta(seconds=1)
        db.commit()
        assert engine.claim_execution(db, pending[1].id, worker_id="w2", now=now)

    # Time limit: an execution that starts past its deadline fails without running more steps.
    monkeypatch.setattr(settings, "automation_max_concurrent_executions", 10)
    create_project(owner, workspace_id, "Slow")
    with db_factory() as db:
        engine.dispatch_events(db, worker_id="w")
        execution = db.query(AutomationExecution).filter(AutomationExecution.status == "pending").one()
        long_ago = datetime.now(UTC) - timedelta(hours=1)
        assert engine.run_execution(db, execution.id, worker_id="w", now=long_ago) == "failed"
        db.refresh(execution)
        assert "time limit" in execution.error_message and all(step.status == "skipped" for step in execution.steps)


def test_approval_reminders_fire_once_per_approval(client_factory, db_factory):
    owner, member, workspace_id = setup_workspace(client_factory, db_factory)
    reminder = create_automation(
        owner, workspace_id, name="Nudge reviewers", trigger_type="APPROVAL_REMINDER_DUE",
        trigger_configuration={"deadline_hours": 24},
        actions=[{"action_type": "create_approval_reminder", "configuration": {"message": "“{title}” has waited {pending_hours}h."}}],
    )
    bad = owner.post(
        f"/api/v1/workspaces/{workspace_id}/automations",
        json={"name": "Bad", "trigger_type": "APPROVAL_REMINDER_DUE", "trigger_configuration": {"deadline_hours": 0}, "actions": []},
        headers=CSRF,
    )
    assert bad.status_code == 422 and "deadline_hours" in bad.text
    enable(owner, workspace_id, reminder["id"])
    project = create_project(member, workspace_id, "Waiting post")
    approval = submit(member, project["id"])
    now = datetime.now(UTC)
    with db_factory() as db:
        row = db.get(ContentApproval, UUID(approval["id"]))
        row.created_at = now - timedelta(hours=10)
        db.commit()
        assert emit_due_approval_reminders(db, now=now) == 1
        assert emit_due_approval_reminders(db, now=now) == 0  # same hour bucket: deduplicated
    process_all(db_factory, now=now)
    assert events_of(db_factory, "APPROVAL_REMINDER_DUE")[0].dispatch_summary[0]["outcome"] == "deadline_not_reached"
    with db_factory() as db:
        db.get(ContentApproval, UUID(approval["id"])).created_at = now - timedelta(hours=30)
        db.commit()
        assert emit_due_approval_reminders(db, now=now) == 1
    process_all(db_factory, now=now)
    executions = executions_of(db_factory, reminder["id"])
    assert len(executions) == 1 and executions[0].status == "succeeded"
    tasks = owner.get(f"/api/v1/workspaces/{workspace_id}/tasks?kind=reminder").json()
    assert len(tasks) == 1 and "has waited 30h" in tasks[0]["description"]
    assert owner.get(f"/api/v1/workspaces/{workspace_id}/notifications").json()["unread_count"] == 1
    # One hour later another reminder event is recorded, but the automation already ran for this approval.
    with db_factory() as db:
        assert emit_due_approval_reminders(db, now=now + timedelta(hours=1)) == 1
    process_all(db_factory, now=now + timedelta(hours=1))
    assert events_of(db_factory, "APPROVAL_REMINDER_DUE")[-1].dispatch_summary[0]["outcome"] == "duplicate"
    assert len(executions_of(db_factory, reminder["id"])) == 1
    # Once decided, no further reminder events are produced.
    owner.post(f"/api/v1/content/projects/{project['id']}/approvals/{approval['id']}/decision", json={"status": "approved"}, headers=CSRF)
    with db_factory() as db:
        assert emit_due_approval_reminders(db, now=now + timedelta(hours=2)) == 0


# Dry run ------------------------------------------------------------------------------


def test_dry_run_simulates_without_side_effects(client_factory, db_factory):
    owner, member, workspace_id = setup_workspace(client_factory, db_factory)
    member_id = me(member)["id"]
    definition = {
        "name": "Failed publishing",
        "trigger_type": "POST_PUBLISH_FAILED",
        "conditions": {"rules": [{"field": "platform", "operator": "equals", "value": "facebook"}, {"field": "attempt_count", "operator": "greater_than_or_equal", "value": 3}]},
        "actions": [
            {"action_type": "notify_admins", "configuration": {"message": "Publishing failed for {title}"}},
            {"action_type": "record_publishing_incident", "configuration": {"severity": "low"}},
            {"action_type": "notify_member", "configuration": {"user_id": member_id, "message": "Please check"}},
        ],
    }
    result = owner.post(f"/api/v1/workspaces/{workspace_id}/automations/dry-run", json={"automation": definition}, headers=CSRF)
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["simulated"] is True and body["would_execute"] is True and body["payload_source"] == "sample"
    assert body["conditions_passed"] and [item["passed"] for item in body["condition_results"]["children"]] == [True, True]
    assert [item["order"] for item in body["actions"]] == [1, 2, 3]
    assert all(item["status"] == "would_run" for item in body["actions"])
    assert "Would notify 1 administrator" in body["actions"][0]["detail"]
    assert "Spring launch announcement" in body["actions"][0]["detail"]
    assert "Simulated" in body["notice"]
    with db_factory() as db:
        assert db.query(Notification).count() == 0 and db.query(ContentTask).count() == 0 and db.query(AutomationExecution).count() == 0

    failing = {**definition, "conditions": {"rules": [{"field": "platform", "operator": "equals", "value": "instagram"}]}}
    body = owner.post(f"/api/v1/workspaces/{workspace_id}/automations/dry-run", json={"automation": failing}, headers=CSRF).json()
    assert body["would_execute"] is False and body["conditions_passed"] is False
    assert body["condition_results"]["children"][0]["actual"] == "facebook"

    invalid = {**definition, "actions": [{"action_type": "notify_member", "configuration": {"user_id": str(uuid4()), "message": "x"}}]}
    body = owner.post(f"/api/v1/workspaces/{workspace_id}/automations/dry-run", json={"automation": invalid}, headers=CSRF).json()
    assert body["would_execute"] is False and body["actions"][0]["status"] == "blocked" and body["errors"]

    overridden = owner.post(
        f"/api/v1/workspaces/{workspace_id}/automations/dry-run",
        json={"automation": definition, "payload_overrides": {"attempt_count": 1}},
        headers=CSRF,
    ).json()
    assert overridden["conditions_passed"] is False
    bad_override = owner.post(
        f"/api/v1/workspaces/{workspace_id}/automations/dry-run",
        json={"automation": definition, "payload_overrides": {"token": "x"}},
        headers=CSRF,
    ).json()
    assert any("Unknown field 'token'" in error for error in bad_override["errors"])

    # Saved automations keep their last simulated result and can use the latest recorded event.
    automation = create_automation(owner, workspace_id, **definition)
    assert owner.get(f"/api/v1/workspaces/{workspace_id}/automations/{automation['id']}/dry-run").json() is None
    stored = owner.post(f"/api/v1/workspaces/{workspace_id}/automations/{automation['id']}/dry-run", json={"payload_source": "latest_event"}, headers=CSRF).json()
    assert stored["payload_source"] == "sample" and any("No recorded event" in error for error in stored["errors"])
    assert owner.get(f"/api/v1/workspaces/{workspace_id}/automations/{automation['id']}/dry-run").json()["simulated"] is True
    assert owner.get(f"/api/v1/workspaces/{workspace_id}/automations/{automation['id']}").json()["last_dry_run_at"]
    assert member.post(f"/api/v1/workspaces/{workspace_id}/automations/{automation['id']}/dry-run", json={}, headers=CSRF).status_code == 403


def test_assignment_endpoint_validates_members_and_emits_event(client_factory, db_factory):
    owner, member, workspace_id = setup_workspace(client_factory, db_factory)
    other = client_factory()
    register(other, "stranger@example.com")
    project = create_project(owner, workspace_id)
    assert owner.post(f"/api/v1/content/projects/{project['id']}/assign", json={"user_id": me(other)["id"]}, headers=CSRF).status_code == 404
    assert other.post(f"/api/v1/content/projects/{project['id']}/assign", json={"user_id": me(member)["id"]}, headers=CSRF).status_code == 404
    assigned = owner.post(f"/api/v1/content/projects/{project['id']}/assign", json={"user_id": me(member)["id"]}, headers=CSRF)
    assert assigned.status_code == 200 and assigned.json()["assigned_to"] == me(member)["id"]
    assert len(events_of(db_factory, "TEAM_MEMBER_ASSIGNED")) == 1
    cleared = owner.post(f"/api/v1/content/projects/{project['id']}/assign", json={"user_id": None}, headers=CSRF)
    assert cleared.json()["assigned_to"] is None
    assert len(events_of(db_factory, "TEAM_MEMBER_ASSIGNED")) == 1
