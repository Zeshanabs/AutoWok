from __future__ import annotations

import io
import time
from uuid import UUID

from PIL import Image

from app.core.config import get_settings
from app.models import MediaAsset
from app.services import storage as storage_module
from app.services.media_urls import sign_media_path
from app.services.storage import StorageError
from publishing_helpers import (
    CSRF,
    add_member,
    approve_project,
    connect_account,
    create_approved_content,
    create_workspace,
    jpeg_bytes,
    mp4_bytes,
    png_bytes,
    register,
    upload,
)


def test_image_upload_extracts_metadata_strips_exif_and_deduplicates(client, db_factory):
    register(client, "media-owner@example.com")
    workspace_id = create_workspace(client)
    original = jpeg_bytes(1200, 900, with_exif=True)
    assert b"SecretCameraMaker" in original

    response = upload(client, workspace_id, original, "../../etc/My Photo.JPG", title="Launch hero")
    assert response.status_code == 201, response.text
    asset = response.json()
    assert asset["mime_type"] == "image/jpeg"
    assert asset["media_type"] == "image"
    assert (asset["width"], asset["height"]) == (1200, 900)
    assert asset["metadata_stripped"] is True
    assert asset["has_thumbnail"] is True
    assert asset["original_filename"] == "My Photo.JPG"
    assert "storage_key" not in asset
    assert asset["title"] == "Launch hero"

    content = client.get(asset["content_url"])
    assert content.status_code == 200
    assert content.headers["content-type"] == "image/jpeg"
    assert b"SecretCameraMaker" not in content.content
    thumb = client.get(asset["thumbnail_url"])
    assert thumb.status_code == 200
    assert max(Image.open(io.BytesIO(thumb.content)).size) <= 480

    with db_factory() as db:
        stored = db.get(MediaAsset, UUID(asset["id"]))
        assert stored.storage_key.startswith(f"workspaces/{workspace_id}/media/")
        assert ".." not in stored.storage_key

    duplicate = upload(client, workspace_id, original, "copy.jpg")
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == asset["id"]
    assert duplicate.json()["duplicate"] is True


def test_video_upload_reads_duration_and_dimensions(client):
    register(client, "video-owner@example.com")
    workspace_id = create_workspace(client)
    response = upload(client, workspace_id, mp4_bytes(duration_seconds=12, width=1080, height=1920), "clip.mp4")
    assert response.status_code == 201, response.text
    asset = response.json()
    assert asset["mime_type"] == "video/mp4"
    assert asset["duration_seconds"] == 12
    assert (asset["width"], asset["height"]) == (1080, 1920)
    assert asset["has_thumbnail"] is False


def test_upload_rejects_bad_types_contents_and_sizes(client, monkeypatch):
    register(client, "bad-media@example.com")
    workspace_id = create_workspace(client)

    fake_image = upload(client, workspace_id, b"<?php system($_GET['x']); ?>", "shell.jpg")
    assert fake_image.status_code == 415
    executable = upload(client, workspace_id, jpeg_bytes(10, 10), "tool.exe")
    assert executable.status_code == 415
    mismatch = upload(client, workspace_id, jpeg_bytes(10, 10), "clip.mp4")
    assert mismatch.status_code == 415
    corrupt = upload(client, workspace_id, b"\xff\xd8\xff\xe0" + b"garbage" * 50, "broken.jpg")
    assert corrupt.status_code == 400
    broken_video = upload(client, workspace_id, b"\x00\x00\x00\x18ftypisom" + b"\x00" * 40, "broken.mp4")
    assert broken_video.status_code == 400
    empty = upload(client, workspace_id, b"", "empty.jpg")
    assert empty.status_code in {400, 422}

    monkeypatch.setattr(get_settings(), "media_max_image_bytes", 1024)
    oversized = upload(client, workspace_id, jpeg_bytes(800, 800, color=(1, 2, 3)) + b"\x00" * 2048, "big.jpg")
    assert oversized.status_code == 413
    assert client.get(f"/api/v1/media-assets?workspace_id={workspace_id}").json() == []


def test_storage_failure_returns_error_and_creates_no_record(client, monkeypatch):
    register(client, "storage-fail@example.com")
    workspace_id = create_workspace(client)

    def fail(_key, _data):
        raise StorageError("disk full")

    monkeypatch.setattr(storage_module.storage_service, "save_file", fail)
    response = upload(client, workspace_id, jpeg_bytes(50, 50), "photo.jpg")
    assert response.status_code == 503
    monkeypatch.undo()
    assert client.get(f"/api/v1/media-assets?workspace_id={workspace_id}").json() == []


def test_media_library_filters_search_update_and_archive(client):
    register(client, "library@example.com")
    workspace_id = create_workspace(client)
    brand = client.post(f"/api/v1/workspaces/{workspace_id}/brands", json={"name": "Brand A"}, headers=CSRF)
    assert brand.status_code == 201
    image = upload(client, workspace_id, jpeg_bytes(100, 100), "sunset.jpg", brand_id=brand.json()["id"]).json()
    video = upload(client, workspace_id, mp4_bytes(), "teaser.mp4").json()

    def names(query: str) -> list[str]:
        response = client.get(f"/api/v1/media-assets?workspace_id={workspace_id}{query}")
        assert response.status_code == 200
        return [item["id"] for item in response.json()]

    assert set(names("")) == {image["id"], video["id"]}
    assert names("&media_type=video") == [video["id"]]
    assert names(f"&brand_id={brand.json()['id']}") == [image["id"]]
    assert names("&search=SUN") == [image["id"]]

    updated = client.patch(f"/api/v1/media-assets/{video['id']}", json={"title": "Teaser cut"}, headers=CSRF)
    assert updated.status_code == 200 and updated.json()["title"] == "Teaser cut"
    assert names("&search=cut") == [video["id"]]

    archived = client.delete(f"/api/v1/media-assets/{image['id']}", headers=CSRF)
    assert archived.status_code == 200
    assert names("") == [video["id"]]
    assert client.get(f"/api/v1/media-assets/{image['id']}/content").status_code == 404


def test_cross_workspace_media_access_is_blocked(client, client_factory):
    register(client, "owner-a@example.com")
    workspace_id = create_workspace(client)
    asset = upload(client, workspace_id, jpeg_bytes(64, 64), "private.jpg").json()

    with client_factory() as other:
        register(other, "intruder@example.com")
        other_workspace = create_workspace(other, "Other")
        for path in ("", "/content", "/download", "/thumbnail"):
            assert other.get(f"/api/v1/media-assets/{asset['id']}{path}").status_code == 404
        assert other.patch(f"/api/v1/media-assets/{asset['id']}", json={"title": "x"}, headers=CSRF).status_code == 404
        assert other.delete(f"/api/v1/media-assets/{asset['id']}", headers=CSRF).status_code == 404
        assert other.get(f"/api/v1/media-assets?workspace_id={workspace_id}").status_code == 404
        assert upload(other, workspace_id, jpeg_bytes(8, 8), "x.jpg").status_code == 404

        project = create_approved_content(other, other_workspace, platforms=("facebook",), approve=False)
        attach = other.put(
            f"/api/v1/content/drafts/{project['drafts']['facebook']}/media",
            json={"media_asset_ids": [asset["id"]]},
            headers=CSRF,
        )
        assert attach.status_code == 404

    with client_factory() as anonymous:
        assert anonymous.get(f"/api/v1/media-assets/{asset['id']}/content").status_code == 401


def test_member_cannot_archive_someone_elses_media(client, client_factory):
    register(client, "archive-owner@example.com")
    workspace_id = create_workspace(client)
    asset = upload(client, workspace_id, jpeg_bytes(30, 30), "owner.jpg").json()
    with client_factory() as member:
        register(member, "archive-member@example.com")
        add_member(client, workspace_id, "archive-member@example.com")
        assert member.get(f"/api/v1/media-assets/{asset['id']}").status_code == 200
        assert member.delete(f"/api/v1/media-assets/{asset['id']}", headers=CSRF).status_code == 403


def test_signed_public_media_urls_expire_and_reject_tampering(client):
    register(client, "signed@example.com")
    workspace_id = create_workspace(client)
    asset = upload(client, workspace_id, jpeg_bytes(40, 40), "signed.jpg").json()

    path = sign_media_path(UUID(asset["id"]), ttl_seconds=120)
    with_anonymous = client.get(path, cookies={})
    assert with_anonymous.status_code == 200
    assert with_anonymous.headers["content-type"] == "image/jpeg"

    tampered = path[:-1] + ("0" if path[-1] != "0" else "1")
    assert client.get(tampered).status_code == 403
    other_asset = upload(client, workspace_id, jpeg_bytes(41, 41), "other.jpg").json()
    assert client.get(path.replace(asset["id"], other_asset["id"])).status_code == 403
    expired = path.replace(f"expires={int(time.time()) + 120}", f"expires={int(time.time()) - 5}")
    assert client.get(expired).status_code == 403

    access = client.post(f"/api/v1/media-assets/{asset['id']}/access-url", headers=CSRF)
    assert access.status_code == 200 and access.json()["expires_in_seconds"] <= 900
    client.delete(f"/api/v1/media-assets/{asset['id']}", headers=CSRF)
    assert client.get(path).status_code == 404


def test_attach_reorder_remove_media_versions_and_invalidates_approval(client):
    register(client, "attach@example.com")
    workspace_id = create_workspace(client)
    first = upload(client, workspace_id, jpeg_bytes(100, 100, color=(1, 1, 1)), "one.jpg").json()
    second = upload(client, workspace_id, jpeg_bytes(100, 100, color=(2, 2, 2)), "two.jpg").json()
    content = create_approved_content(client, workspace_id, platforms=("instagram",), media={"instagram": [first["id"], second["id"]]})
    draft_id = content["drafts"]["instagram"]
    project_id = content["project_id"]
    assert client.get(f"/api/v1/content/projects/{project_id}").json()["status"] == "approved"

    reordered = client.put(
        f"/api/v1/content/drafts/{draft_id}/media",
        json={"media_asset_ids": [second["id"], first["id"]]},
        headers=CSRF,
    )
    assert reordered.status_code == 200
    assert reordered.json()["media_asset_ids"] == [second["id"], first["id"]]
    # A material media change revokes the approval and creates a new version.
    assert client.get(f"/api/v1/content/projects/{project_id}").json()["status"] == "draft"
    drafts = client.get(f"/api/v1/content/projects/{project_id}/drafts").json()
    assert drafts[0]["media_asset_ids"] == [second["id"], first["id"]]
    assert drafts[0]["versions"][-1]["change_reason"] == "Media attachments updated"

    removed = client.delete(f"/api/v1/content/drafts/{draft_id}/media/{first['id']}", headers=CSRF)
    assert removed.status_code == 200 and removed.json()["media_asset_ids"] == [second["id"]]
    assert client.delete(f"/api/v1/content/drafts/{draft_id}/media/{first['id']}", headers=CSRF).status_code == 404

    approve_project(client, project_id)
    submitted = client.post(f"/api/v1/content/projects/{project_id}/submit-for-approval", json={}, headers=CSRF)
    assert submitted.status_code == 409  # already approved; edit first
    client.put(f"/api/v1/content/drafts/{draft_id}/media", json={"media_asset_ids": [first["id"]]}, headers=CSRF)
    client.post(f"/api/v1/content/projects/{project_id}/submit-for-approval", json={}, headers=CSRF)
    locked = client.put(f"/api/v1/content/drafts/{draft_id}/media", json={"media_asset_ids": []}, headers=CSRF)
    assert locked.status_code == 409  # cannot change media while in review


def test_platform_previews_validate_media_requirements(client, db_factory, token_key):
    register(client, "preview@example.com")
    workspace_id = create_workspace(client)
    jpeg = upload(client, workspace_id, jpeg_bytes(1080, 1350), "portrait.jpg").json()
    png = upload(client, workspace_id, png_bytes(), "graphic.png").json()
    video = upload(client, workspace_id, mp4_bytes(), "clip.mp4").json()
    content = create_approved_content(
        client,
        workspace_id,
        media={"facebook": [jpeg["id"]], "instagram": [png["id"]]},
    )
    fb_account = connect_account(db_factory, workspace_id)
    ig_account = connect_account(db_factory, workspace_id, platform="instagram")

    fb = client.get(f"/api/v1/content/drafts/{content['drafts']['facebook']}/media-preview?social_account_id={fb_account}").json()
    assert fb["approximate"] is True and "approximation" in fb["disclaimer"]
    assert fb["preview_type"] == "photo"
    assert fb["errors"] == []
    assert fb["account_name"] == "Autowok Page"
    assert fb["caption"].startswith("Big news.")
    assert "#launch" in fb["caption"]

    ig = client.get(f"/api/v1/content/drafts/{content['drafts']['instagram']}/media-preview?social_account_id={ig_account}").json()
    assert any("JPEG" in error for error in ig["errors"])

    wrong_account = client.get(f"/api/v1/content/drafts/{content['drafts']['instagram']}/media-preview?social_account_id={fb_account}").json()
    assert any("Instagram Professional account" in error for error in wrong_account["errors"])

    client.delete(f"/api/v1/content/drafts/{content['drafts']['instagram']}/media/{png['id']}", headers=CSRF)
    missing = client.get(f"/api/v1/content/drafts/{content['drafts']['instagram']}/media-preview").json()
    assert any("at least one image or video" in error for error in missing["errors"])

    client.put(f"/api/v1/content/drafts/{content['drafts']['facebook']}/media", json={"media_asset_ids": [jpeg["id"], video["id"]]}, headers=CSRF)
    mixed = client.get(f"/api/v1/content/drafts/{content['drafts']['facebook']}/media-preview").json()
    assert any("cannot mix a video" in error for error in mixed["errors"])

    client.put(f"/api/v1/content/drafts/{content['drafts']['instagram']}/media", json={"media_asset_ids": [jpeg["id"], video["id"]]}, headers=CSRF)
    carousel = client.get(f"/api/v1/content/drafts/{content['drafts']['instagram']}/media-preview").json()
    assert carousel["preview_type"] == "carousel" and carousel["media_count"] == 2
    assert any("approved" in error for error in carousel["errors"])  # media edit revoked approval

    other_workspace = create_workspace(client, "Second")
    other_account = connect_account(db_factory, other_workspace, platform_account_id="page-2")
    assert client.get(f"/api/v1/content/drafts/{content['drafts']['facebook']}/media-preview?social_account_id={other_account}").status_code == 404
