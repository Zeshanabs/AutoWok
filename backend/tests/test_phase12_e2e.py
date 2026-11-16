"""Phase 12 end-to-end regression: the complete Autowok workflow, in order.

Everything external is mocked so the test is deterministic in CI:

* Meta (OAuth discovery, publishing, insights) - scripted Graph API responses.
* Groq (agent workflow) - a scripted model.
* Redis - an in-memory fake. Database - in-memory SQLite.

A pass here means the application logic works end to end against those mocks.
It does NOT verify a live Meta or Groq integration.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

from app.models import AuditLog, ContentPublication, MetaAuthorization, ScheduledPost
from app.services.publishing import service as publishing_service
from app.services.scheduling import worker_tasks as scheduling_tasks
from app.services.token_encryption import encrypt_token
from app.worker import run_once
from tests.agent_helpers import FakeGroq, add_research, detail, run, start
from tests.publishing_helpers import CSRF, FB_SCOPES, PASSWORD, FakeMeta, add_member, jpeg_bytes, upload
from tests.test_phase3_integrations import meta_settings
from tests.test_phase9_analytics import fake_facebook, run_sync
from tests.test_phase10_automations import create_automation, enable, process_all

API = "/api/v1"


def test_complete_workflow_from_registration_to_reviewed_ai_deliverable(client_factory, db_factory, token_key, monkeypatch):
    from cryptography.fernet import Fernet

    from app.api.v1.routes import social_accounts
    from app.services import ai_encryption, meta_graph

    owner = client_factory()
    reviewer = client_factory()

    # 1. User registers ---------------------------------------------------------------
    registered = owner.post(
        f"{API}/auth/register",
        json={"full_name": "Olivia Owner", "email": "olivia@example.com", "password": PASSWORD},
        headers=CSRF,
    )
    assert registered.status_code == 201 and registered.json()["workspace"]["role"] == "OWNER"
    assert "password" not in registered.text.lower() or PASSWORD not in registered.text

    # 2. User logs in (fresh session) ---------------------------------------------------
    assert owner.post(f"{API}/auth/logout", headers=CSRF).status_code == 200
    assert owner.get(f"{API}/auth/me").status_code == 401
    assert owner.post(f"{API}/auth/login", json={"email": "olivia@example.com", "password": PASSWORD}, headers=CSRF).status_code == 200
    me = owner.get(f"{API}/auth/me").json()
    assert me["user"]["email"] == "olivia@example.com"

    # 3. User creates a workspace and adds a reviewer -----------------------------------
    workspace = owner.post(f"{API}/workspaces", json={"name": "Bean & Co marketing"}, headers=CSRF)
    assert workspace.status_code == 201
    workspace_id = workspace.json()["id"]
    assert reviewer.post(
        f"{API}/auth/register", json={"full_name": "Ravi Reviewer", "email": "ravi@example.com", "password": PASSWORD}, headers=CSRF
    ).status_code == 201
    add_member(owner, workspace_id, "ravi@example.com")
    promoted = owner.patch(
        f"{API}/workspaces/{workspace_id}/members/{reviewer.get(f'{API}/auth/me').json()['user']['id']}/role",
        json={"role": "ADMIN"},
        headers=CSRF,
    )
    assert promoted.status_code == 200

    # 4. User configures a brand --------------------------------------------------------
    brand = owner.post(f"{API}/workspaces/{workspace_id}/brands", json={"name": "Bean & Co", "industry": "Food and drink"}, headers=CSRF)
    assert brand.status_code == 201
    brand_id = brand.json()["id"]
    voice = owner.put(f"{API}/brands/{brand_id}/voice", json={"tone": "Warm and practical", "prohibited_phrases": ["best in the world"]}, headers=CSRF)
    assert voice.status_code == 200
    assert owner.get(f"{API}/brands/{brand_id}/context").status_code == 200

    # 5. User configures Groq (the key is stored encrypted and never returned) ----------
    ai_key = Fernet.generate_key().decode("ascii")
    monkeypatch.setattr(ai_encryption, "get_settings", lambda: SimpleNamespace(ai_encryption_key=ai_key, ai_encryption_key_previous=""))
    provider = owner.post(
        f"{API}/workspaces/{workspace_id}/ai-providers",
        json={"provider_name": "groq", "display_name": "Groq", "model_name": "test-model", "api_key": "gsk_e2e_test_key_value_0001"},
        headers=CSRF,
    )
    assert provider.status_code == 201 and "gsk_e2e_test_key_value_0001" not in provider.text
    assert "gsk_e2e_test_key_value_0001" not in owner.get(f"{API}/workspaces/{workspace_id}/ai-providers").text

    # 6. User connects an eligible Meta account (mocked Graph API) -----------------------
    settings = meta_settings("oauth-state-secret")
    settings.meta_token_encryption_key = token_key
    monkeypatch.setattr(social_accounts, "get_settings", lambda: settings)
    monkeypatch.setattr(meta_graph, "get_settings", lambda: settings)

    class FakeMetaGraph:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def list_pages(self, access_token):
            return [{"id": "page-1", "name": "Bean & Co Page", "tasks": ["MANAGE", "CREATE_CONTENT"], "access_token": "page-access-secret"}]

        def get_social_account(self, *, account_id, platform, access_token):
            return {"id": account_id, "name": "Bean & Co Page"}

    monkeypatch.setattr(social_accounts, "MetaGraphClient", FakeMetaGraph)
    with db_factory() as db:
        db.add(
            MetaAuthorization(
                workspace_id=UUID(workspace_id),
                authorized_by=UUID(me["user"]["id"]),
                meta_user_id="meta-user-1",
                encrypted_user_access_token=encrypt_token("user-access-secret"),
                granted_scopes=[*FB_SCOPES, "read_insights"],
                access_token_expires_at=datetime.now(UTC) + timedelta(days=50),
            )
        )
        db.commit()
    pages = owner.get(f"{API}/workspaces/{workspace_id}/social-accounts/meta/facebook-pages")
    assert pages.status_code == 200 and pages.json()[0]["platform_account_id"] == "page-1"
    connected = owner.post(
        f"{API}/workspaces/{workspace_id}/social-accounts/meta/connect",
        json={"platform": "facebook_page", "platform_account_id": "page-1", "brand_id": brand_id},
        headers=CSRF,
    )
    assert connected.status_code == 201 and "page-access-secret" not in connected.text
    account_id = connected.json()["id"]

    # 7. User conducts research ---------------------------------------------------------
    research = owner.post(
        f"{API}/research",
        json={"workspace_id": workspace_id, "brand_id": brand_id, "title": "Home coffee habits", "research_question": "What do home brewers struggle with?"},
        headers=CSRF,
    )
    assert research.status_code == 201
    run_research = owner.post(f"{API}/research/{research.json()['id']}/run", headers=CSRF)
    # No search provider is configured in tests, so the run is refused with an
    # explicit "unavailable" answer and the project is marked failed - a handled
    # outcome, not a crash. (Live research is not verified by this test.)
    assert run_research.status_code in {200, 503}
    if run_research.status_code == 503:
        assert isinstance(run_research.json()["detail"], str) and "request_id" not in run_research.json()
    research_status = owner.get(f"{API}/research/{research.json()['id']}/status")
    assert research_status.status_code == 200

    # 8. User creates content -----------------------------------------------------------
    project = owner.post(
        f"{API}/content/projects",
        json={"workspace_id": workspace_id, "brand_id": brand_id, "title": "Three brewing mistakes", "topic": "Home brewing", "selected_platforms": ["facebook"]},
        headers=CSRF,
    )
    assert project.status_code == 201
    project_id = project.json()["id"]
    draft = owner.post(
        f"{API}/content/projects/{project_id}/drafts",
        json={"platform": "facebook", "title": "Brewing", "hook": "Three mistakes.", "body": "Grind fresh, weigh your coffee, mind the water.", "cta": "Read the guide.", "hashtags": ["#coffee"]},
        headers=CSRF,
    )
    assert draft.status_code == 201
    draft_id = draft.json()["id"]

    # 9. User uses AI content intelligence ----------------------------------------------
    ideas = owner.post(f"{API}/content/intelligence/ideas", json={"topic": "Home brewing", "workspace_id": workspace_id}, headers=CSRF)
    assert ideas.status_code == 200
    validated = owner.post(f"{API}/content/projects/{project_id}/drafts/{draft_id}/validate", json={}, headers=CSRF)
    assert validated.status_code == 200

    # 10. User uploads media and attaches it --------------------------------------------
    image = upload(owner, workspace_id, jpeg_bytes(1080, 1080, with_exif=True), "brew.jpg", title="Brew guide")
    assert image.status_code == 201 and image.json()["metadata_stripped"] is True
    attached = owner.put(f"{API}/content/drafts/{draft_id}/media", json={"media_asset_ids": [image.json()["id"]]}, headers=CSRF)
    assert attached.status_code == 200

    # 11. User previews the content -----------------------------------------------------
    preview = owner.get(f"{API}/content/drafts/{draft_id}/media-preview", params={"social_account_id": account_id})
    assert preview.status_code == 200

    # 12. User submits the content for approval -----------------------------------------
    not_yet = owner.post(f"{API}/content/drafts/{draft_id}/publish", json={"social_account_id": account_id, "confirm": True}, headers=CSRF)
    assert not_yet.status_code in {400, 409, 422}  # unapproved content cannot be published
    submitted = owner.post(f"{API}/content/projects/{project_id}/submit-for-approval", json={}, headers=CSRF)
    assert submitted.status_code == 200

    # 13. An authorized reviewer approves it --------------------------------------------
    decision = reviewer.post(
        f"{API}/content/projects/{project_id}/approvals/{submitted.json()['id']}/decision", json={"status": "approved"}, headers=CSRF
    )
    assert decision.status_code == 200
    assert owner.get(f"{API}/content/projects/{project_id}").json()["status"] == "approved"

    # 14. User schedules the post -------------------------------------------------------
    local = (datetime.now(UTC) + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
    scheduled = owner.post(
        f"{API}/workspaces/{workspace_id}/scheduled-posts",
        json={"draft_id": draft_id, "social_account_id": account_id, "scheduled_local": local, "timezone": "UTC", "confirm": True},
        headers=CSRF,
    )
    assert scheduled.status_code == 201, scheduled.text
    schedule_id = scheduled.json()["id"]
    calendar = owner.get(f"{API}/workspaces/{workspace_id}/calendar", params={"view": "list"})
    assert calendar.status_code == 200 and any(item["scheduled_post_id"] == schedule_id for item in calendar.json()["items"])

    # 15. The background worker publishes it when due -----------------------------------
    with db_factory() as db:
        db.get(ScheduledPost, UUID(schedule_id)).scheduled_at = datetime.now(UTC) - timedelta(seconds=30)
        db.commit()
    meta = FakeMeta(
        {
            ("POST", "/page-1/photos"): {"id": "photo-1", "post_id": "page-1_post1"},
            ("GET", "/page-1_post1"): {"permalink_url": "https://facebook.com/page-1/posts/1"},
        }
    )
    monkeypatch.setattr(publishing_service, "MetaPublisher", lambda: meta.publisher())
    tasks: list = []
    scheduling_tasks.register(tasks)
    assert run_once(db_factory, worker_id="e2e-worker", tasks=tasks) >= 1
    post = owner.get(f"{API}/scheduled-posts/{schedule_id}").json()
    assert post["status"] == "published" and post["permalink"] == "https://facebook.com/page-1/posts/1"
    assert len(meta.calls_to("POST", "/page-1/photos")) == 1
    # A second worker pass must not publish again.
    assert run_once(db_factory, worker_id="e2e-worker", tasks=tasks) == 0
    assert len(meta.calls_to("POST", "/page-1/photos")) == 1
    with db_factory() as db:
        assert db.query(ContentPublication).filter(ContentPublication.status == "published").count() == 1

    # 16. Analytics synchronization retrieves the available metrics (mocked insights) ----
    sync_job = run_sync(db_factory, account_id, fake_facebook())
    assert sync_job.status in {"succeeded", "partial"} and sync_job.records_processed > 0

    # 17. User reviews analytics ---------------------------------------------------------
    overview = owner.get(f"{API}/workspaces/{workspace_id}/analytics/overview")
    assert overview.status_code == 200
    posts = owner.get(f"{API}/workspaces/{workspace_id}/analytics/posts").json()
    assert posts["total"] >= 1
    linked = [item for item in posts["items"] if item.get("external_post_id") == "page-1_post1"]
    assert linked, "the published post is matched to its insights"
    export = owner.get(f"{API}/workspaces/{workspace_id}/analytics/reports/export", params={"format": "csv"})
    assert export.status_code == 200 and "Autowok analytics report" in export.text

    # 18. User creates a controlled automation and sees it run ---------------------------
    automation = create_automation(owner, workspace_id)
    enable(owner, workspace_id, automation["id"])
    second = owner.post(
        f"{API}/content/projects", json={"workspace_id": workspace_id, "title": "Follow-up post", "selected_platforms": ["facebook"]}, headers=CSRF
    ).json()
    owner.post(
        f"{API}/content/projects/{second['id']}/drafts", json={"platform": "facebook", "title": "Follow-up", "body": "More tips."}, headers=CSRF
    )
    assert owner.post(f"{API}/content/projects/{second['id']}/submit-for-approval", json={}, headers=CSRF).status_code == 200
    dispatched, executed = process_all(db_factory)
    assert dispatched >= 1 and executed >= 1
    notifications = reviewer.get(f"{API}/workspaces/{workspace_id}/notifications").json()
    assert notifications["unread_count"] >= 1
    # The automation notified and labelled; it did not approve or publish anything.
    assert owner.get(f"{API}/content/projects/{second['id']}").json()["status"] != "approved"

    # 19. User runs an AI agent workflow (scripted Groq) ---------------------------------
    seeded = add_research(db_factory, workspace_id)  # a completed research report with one source
    workflow = start(owner, workspace_id, "social_content", brand_id=brand_id, research_ids=[seeded["research_id"]])
    groq = FakeGroq()
    assert run(db_factory, workflow["id"], groq) == "succeeded"
    assert groq.calls, "the agents called the model"

    # 20. User reviews the generated deliverable ----------------------------------------
    result = detail(owner, workspace_id, workflow["id"])
    assert result["status"] == "succeeded" and result["final_output"] is not None and result["can_accept"] is True
    accepted = owner.post(f"{API}/workspaces/{workspace_id}/agent-workflows/{workflow['id']}/accept", json={}, headers=CSRF)
    assert accepted.status_code == 200, accepted.text
    ai_project = owner.get(f"{API}/content/projects/{accepted.json()['project_id']}").json()
    # AI output enters the studio as a draft: it is never approved or published automatically.
    assert ai_project["status"] == "draft"
    with db_factory() as db:
        assert db.query(ContentPublication).count() == 1

    # Audit trail and secrets ------------------------------------------------------------
    with db_factory() as db:
        actions = {row.action for row in db.query(AuditLog).all()}
        blob = " ".join(str(row.details) for row in db.query(AuditLog).all())
    assert {"user.registered", "auth.login", "workspace.created", "publishing.published"} <= actions
    for secret in (PASSWORD, "page-access-secret", "user-access-secret", "gsk_e2e_test_key_value_0001"):
        assert secret not in blob


TEXT = "Grind fresh. Weigh your coffee. Mind the water temperature."
INTELLIGENCE_REQUESTS = {
    "ideas": {"topic": "Home {brewing} tips", "platform": "instagram"},
    "writing": {"text": TEXT, "action": "improve writing"},
    "critique": {"text": TEXT},
    "fact-check": {"claims": ["Fresh coffee tastes better."]},
    "hooks": {"topic": "Home brewing"},
    "hashtags": {"topic": "Home brewing", "platform": "instagram"},
    "repurpose": {"text": TEXT, "platform": "facebook"},
    "brand-consistency": {"text": TEXT},
    "score": {"text": TEXT},
    "rewrite": {"text": TEXT, "tone": "playful"},
}


def test_every_content_intelligence_endpoint_answers(client_factory):
    """Regression: the ideas, writing, critique and fact-check endpoints used to
    fail with HTTP 500 on every call (prompt templates with literal braces)."""
    from tests.publishing_helpers import create_workspace, register

    client = client_factory()
    register(client, "intelligence@example.com")
    workspace_id = create_workspace(client)
    for name, body in INTELLIGENCE_REQUESTS.items():
        response = client.post(
            f"/api/v1/content/intelligence/{name}", json={"workspace_id": workspace_id, **body}, headers=CSRF
        )
        assert response.status_code == 200, (name, response.status_code, response.text[:200])
        assert response.json(), name
    ideas = client.post(
        "/api/v1/content/intelligence/ideas", json={"workspace_id": workspace_id, "topic": "Home brewing"}, headers=CSRF
    ).json()
    assert ideas["count"] >= 1 and ideas["ideas"][0]["title"]
