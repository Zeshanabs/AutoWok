from __future__ import annotations

from app.services.content_studio import ContentStudioService

CSRF = {"Origin": "http://localhost:3000", "X-CSRF-Protection": "1"}
PASSWORD = "StrongPassword#1234"


def register(client, email: str):
    return client.post(
        "/api/v1/auth/register",
        json={
            "full_name": email.split("@")[0].title(),
            "email": email,
            "password": PASSWORD,
        },
        headers=CSRF,
    )


def create_workspace(client, name: str = "Content workspace") -> str:
    response = client.post(
        "/api/v1/workspaces",
        json={"name": name},
        headers=CSRF,
    )
    assert response.status_code == 201
    return response.json()["id"]


def create_project(client, workspace_id: str) -> dict:
    response = client.post(
        "/api/v1/content/projects",
        json={
            "workspace_id": workspace_id,
            "title": "Product launch",
            "topic": "A new product",
            "selected_platforms": ["instagram"],
        },
        headers=CSRF,
    )
    assert response.status_code == 201
    return response.json()


def test_content_project_draft_versions_validation_and_approval(
    client, client_factory
):
    assert register(client, "content-owner@example.com").status_code == 201
    workspace_id = create_workspace(client)
    project = create_project(client, workspace_id)
    project_id = project["id"]

    assert client.get(f"/api/v1/content/projects/{project_id}").status_code == 200

    draft_response = client.post(
        f"/api/v1/content/projects/{project_id}/drafts",
        json={
            "platform": "instagram",
            "title": "Launch",
            "hook": "A better way to work.",
            "body": "Meet our new product.",
            "cta": "Learn more.",
            "hashtags": ["#launch"],
        },
        headers=CSRF,
    )
    assert draft_response.status_code == 201
    draft = draft_response.json()
    draft_id = draft["id"]
    assert draft["version_count"] == 1

    invalid = client.post(
        f"/api/v1/content/projects/{project_id}/drafts/{draft_id}/validate",
        headers=CSRF,
    )
    assert invalid.status_code == 200
    assert invalid.json()["valid"] is True
    assert invalid.json()["caption_length"] > 0

    changed = client.patch(
        f"/api/v1/content/projects/{project_id}/drafts/{draft_id}",
        json={"body": "Meet our updated product."},
        headers=CSRF,
    )
    assert changed.status_code == 200
    assert changed.json()["version_count"] == 2
    versions = client.get(
        f"/api/v1/content/projects/{project_id}/drafts/{draft_id}/versions"
    )
    assert [version["version_number"] for version in versions.json()] == [1, 2]

    restored = client.post(
        f"/api/v1/content/projects/{project_id}/drafts/{draft_id}/versions/"
        f"{versions.json()[0]['id']}/restore",
        headers=CSRF,
    )
    assert restored.status_code == 200
    assert restored.json()["body"] == "Meet our new product."
    assert restored.json()["version_count"] == 3

    with client_factory() as member_client:
        assert register(member_client, "content-member@example.com").status_code == 201
        member = client.post(
            f"/api/v1/workspaces/{workspace_id}/members",
            json={"email": "content-member@example.com"},
            headers=CSRF,
        )
        assert member.status_code == 201

        submitted = member_client.post(
            f"/api/v1/content/projects/{project_id}/submit-for-approval",
            json={"comments": "Please review."},
            headers=CSRF,
        )
        assert submitted.status_code == 200
        approval_id = submitted.json()["id"]
        assert submitted.json()["status"] == "pending"
        assert member_client.post(
            f"/api/v1/content/projects/{project_id}/approvals/{approval_id}/decision",
            json={"status": "approved"},
            headers=CSRF,
        ).status_code == 403

    approved = client.post(
        f"/api/v1/content/projects/{project_id}/approvals/{approval_id}/decision",
        json={"status": "approved", "comments": "Approved."},
        headers=CSRF,
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert client.get(f"/api/v1/content/projects/{project_id}").json()["status"] == "approved"
    edited = client.patch(
        f"/api/v1/content/projects/{project_id}/drafts/{draft_id}",
        json={"body": "An approved draft can be revised."},
        headers=CSRF,
    )
    assert edited.status_code == 200
    assert edited.json()["status"] == "draft"
    assert client.get(f"/api/v1/content/projects/{project_id}").json()["status"] == "draft"


def test_content_rejects_cross_workspace_brand_and_unselected_platform(client):
    assert register(client, "content-isolation@example.com").status_code == 201
    first_workspace = create_workspace(client, "First workspace")
    second_workspace = create_workspace(client, "Second workspace")
    brand = client.post(
        f"/api/v1/workspaces/{second_workspace}/brands",
        json={"name": "Private brand"},
        headers=CSRF,
    )
    assert brand.status_code == 201

    cross_workspace = client.post(
        "/api/v1/content/projects",
        json={
            "workspace_id": first_workspace,
            "title": "Invalid association",
            "brand_id": brand.json()["id"],
            "selected_platforms": ["instagram"],
        },
        headers=CSRF,
    )
    assert cross_workspace.status_code == 404

    project = create_project(client, first_workspace)
    unselected = client.post(
        f"/api/v1/content/projects/{project['id']}/drafts",
        json={"platform": "facebook", "body": "Not selected."},
        headers=CSRF,
    )
    assert unselected.status_code == 400


def test_content_approval_requires_valid_draft_and_is_single_use(client):
    assert register(client, "content-validation@example.com").status_code == 201
    workspace_id = create_workspace(client)
    project = create_project(client, workspace_id)
    project_id = project["id"]
    empty_draft = client.post(
        f"/api/v1/content/projects/{project_id}/drafts",
        json={"platform": "instagram"},
        headers=CSRF,
    )
    assert empty_draft.status_code == 201
    draft_id = empty_draft.json()["id"]

    invalid = client.post(
        f"/api/v1/content/projects/{project_id}/drafts/{draft_id}/validate",
        headers=CSRF,
    )
    assert invalid.json()["valid"] is False
    assert invalid.json()["errors"]
    assert client.post(
        f"/api/v1/content/projects/{project_id}/submit-for-approval",
        json={},
        headers=CSRF,
    ).status_code == 400

    client.patch(
        f"/api/v1/content/projects/{project_id}/drafts/{draft_id}",
        json={"body": "Ready for review.", "hashtags": ["#ready"]},
        headers=CSRF,
    )
    submitted = client.post(
        f"/api/v1/content/projects/{project_id}/submit-for-approval",
        json={},
        headers=CSRF,
    )
    assert submitted.status_code == 200
    approval_id = submitted.json()["id"]
    decided = client.post(
        f"/api/v1/content/projects/{project_id}/approvals/{approval_id}/decision",
        json={"status": "changes_requested"},
        headers=CSRF,
    )
    assert decided.status_code == 200
    assert client.get(f"/api/v1/content/projects/{project_id}").json()["status"] == "draft"

    resubmitted = client.post(
        f"/api/v1/content/projects/{project_id}/submit-for-approval",
        json={},
        headers=CSRF,
    )
    assert resubmitted.status_code == 200
    assert resubmitted.json()["id"] != approval_id
    assert client.post(
        f"/api/v1/content/projects/{project_id}/approvals/{approval_id}/decision",
        json={"status": "approved"},
        headers=CSRF,
    ).status_code == 409


def test_platform_validation_enforces_caption_and_instagram_hashtag_limits():
    service = ContentStudioService(None)
    exact_limit = service.platform_validation(
        "instagram",
        {"hook": "x" * 1100, "body": "x" * 1098, "hashtags": ["#tag"] * 30},
    )
    assert exact_limit["valid"] is True
    assert exact_limit["caption_length"] == 2200
    assert exact_limit["hashtag_count"] == 30

    over_caption_limit = service.platform_validation(
        "instagram",
        {"body": "x" * 2201, "hashtags": []},
    )
    assert over_caption_limit["valid"] is False
    assert any("2,200" in error for error in over_caption_limit["errors"])

    over_hashtag_limit = service.platform_validation(
        "instagram",
        {"body": "Caption", "hashtags": ["#tag"] * 31},
    )
    assert over_hashtag_limit["valid"] is False
    assert any("30 hashtags" in error for error in over_hashtag_limit["errors"])

    facebook = service.platform_validation(
        "facebook",
        {"body": "x" * 63206, "hashtags": ["#tag"] * 11},
    )
    assert facebook["valid"] is True
    assert facebook["caption_length"] == 63206
    assert facebook["warnings"]
    too_long_facebook = service.platform_validation(
        "facebook",
        {"body": "x" * 63207, "hashtags": []},
    )
    assert too_long_facebook["valid"] is False
    assert any("63,206" in error for error in too_long_facebook["errors"])
