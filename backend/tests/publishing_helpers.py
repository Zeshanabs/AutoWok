"""Shared helpers for Phase 7/8 media, publishing, and scheduling tests."""

from __future__ import annotations

import io
import json
import struct
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import parse_qs
from uuid import UUID

import httpx
from PIL import Image

from app.models import SocialAccount, SocialAccountCredential, User
from app.services.meta_graph import MetaGraphClient
from app.services.publishing.meta_publisher import MetaPublisher
from app.services.token_encryption import encrypt_token

CSRF = {"Origin": "http://localhost:3000", "X-CSRF-Protection": "1"}
PASSWORD = "StrongPassword#1234"
FB_SCOPES = ["pages_show_list", "pages_read_engagement", "instagram_basic", "pages_manage_posts", "publish_video"]
IG_SCOPES = ["pages_show_list", "pages_read_engagement", "instagram_basic", "instagram_content_publish"]


def register(client, email: str) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"full_name": email.split("@")[0].title(), "email": email, "password": PASSWORD},
        headers=CSRF,
    )
    assert response.status_code == 201, response.text


def create_workspace(client, name: str = "Publishing workspace") -> str:
    response = client.post("/api/v1/workspaces", json={"name": name}, headers=CSRF)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def add_member(owner_client, workspace_id: str, email: str) -> None:
    response = owner_client.post(
        f"/api/v1/workspaces/{workspace_id}/members", json={"email": email}, headers=CSRF
    )
    assert response.status_code == 201, response.text


def jpeg_bytes(width: int = 1080, height: int = 1080, *, with_exif: bool = False, color=(200, 40, 40)) -> bytes:
    image = Image.new("RGB", (width, height), color)
    buffer = io.BytesIO()
    if with_exif:
        exif = Image.Exif()
        exif[0x010F] = "SecretCameraMaker"  # Make
        exif[0x0110] = "SecretModel"
        image.save(buffer, format="JPEG", exif=exif.tobytes())
    else:
        image.save(buffer, format="JPEG")
    return buffer.getvalue()


def png_bytes(width: int = 800, height: int = 800) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (width, height), (10, 120, 200, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


def _box(box_type: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(payload), box_type) + payload


def mp4_bytes(*, duration_seconds: int = 12, width: int = 1080, height: int = 1920) -> bytes:
    """A structurally valid (not playable) MP4 with mvhd and tkhd boxes."""
    timescale = 1000
    mvhd = _box(b"mvhd", bytes(4) + struct.pack(">IIII", 0, 0, timescale, duration_seconds * timescale) + bytes(80))
    tkhd_payload = bytes(4) + struct.pack(">IIIII", 0, 0, 1, 0, duration_seconds * timescale) + bytes(8)
    tkhd_payload += bytes(8) + bytes(36) + struct.pack(">II", width << 16, height << 16)
    trak = _box(b"trak", _box(b"tkhd", tkhd_payload))
    ftyp = _box(b"ftyp", b"isom" + struct.pack(">I", 512) + b"isomiso2mp41")
    return ftyp + _box(b"moov", mvhd + trak) + _box(b"mdat", b"\x00" * 64)


def upload(client, workspace_id: str, content: bytes, filename: str, **form: str):
    return client.post(
        "/api/v1/media-assets/upload",
        data={"workspace_id": workspace_id, **form},
        files={"file": (filename, content, "application/octet-stream")},
        headers=CSRF,
    )


def create_approved_content(
    client,
    workspace_id: str,
    *,
    platforms: tuple[str, ...] = ("facebook", "instagram"),
    media: dict[str, list[str]] | None = None,
    approve: bool = True,
) -> dict[str, Any]:
    project = client.post(
        "/api/v1/content/projects",
        json={"workspace_id": workspace_id, "title": "Launch post", "topic": "Launch", "selected_platforms": list(platforms)},
        headers=CSRF,
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    drafts: dict[str, str] = {}
    for platform in platforms:
        draft = client.post(
            f"/api/v1/content/projects/{project_id}/drafts",
            json={"platform": platform, "title": "Launch", "hook": "Big news.", "body": "We launched.", "cta": "Learn more.", "hashtags": ["#launch"]},
            headers=CSRF,
        )
        assert draft.status_code == 201, draft.text
        drafts[platform] = draft.json()["id"]
        if media and media.get(platform):
            attached = client.put(
                f"/api/v1/content/drafts/{drafts[platform]}/media",
                json={"media_asset_ids": media[platform]},
                headers=CSRF,
            )
            assert attached.status_code == 200, attached.text
    if approve:
        approve_project(client, project_id)
    return {"project_id": project_id, "drafts": drafts}


def approve_project(client, project_id: str) -> None:
    submitted = client.post(f"/api/v1/content/projects/{project_id}/submit-for-approval", json={}, headers=CSRF)
    assert submitted.status_code == 200, submitted.text
    decided = client.post(
        f"/api/v1/content/projects/{project_id}/approvals/{submitted.json()['id']}/decision",
        json={"status": "approved"},
        headers=CSRF,
    )
    assert decided.status_code == 200, decided.text


def connect_account(
    db_factory,
    workspace_id: str,
    *,
    platform: str = "facebook_page",
    platform_account_id: str | None = None,
    scopes: list[str] | None = None,
    account_type: str | None = None,
    status: str = "connected",
    token: str = "page-access-secret",
) -> str:
    with db_factory() as db:
        user = db.query(User).first()
        account = SocialAccount(
            workspace_id=UUID(workspace_id),
            platform=platform,
            platform_account_id=platform_account_id or ("page-1" if platform == "facebook_page" else "ig-1"),
            username="autowok",
            display_name="Autowok Page" if platform == "facebook_page" else "autowok",
            account_type=account_type or ("PAGE" if platform == "facebook_page" else "BUSINESS"),
            connection_status=status,
            granted_scopes=scopes if scopes is not None else (FB_SCOPES if platform == "facebook_page" else IG_SCOPES),
            connected_by=user.id,
        )
        db.add(account)
        db.flush()
        db.add(SocialAccountCredential(social_account_id=account.id, encrypted_access_token=encrypt_token(token)))
        db.commit()
        return str(account.id)


@dataclass
class FakeMeta:
    """Scriptable Graph API. ``responses`` maps (METHOD, path suffix) to a
    callable or a list of results; a result may be a dict (200 JSON), an
    ``httpx.Response``, or an exception to raise."""

    responses: dict[tuple[str, str], Any] = field(default_factory=dict)
    calls: list[dict[str, Any]] = field(default_factory=list)

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.split("/", 2)[-1]  # strip "/v26.0"
        body = parse_qs(request.content.decode()) if request.content else {}
        flat = {key: value[0] for key, value in body.items()}
        self.calls.append({"method": request.method, "path": "/" + path, "data": flat, "params": dict(request.url.params), "auth": request.headers.get("authorization")})
        key = (request.method, "/" + path)
        entry = self.responses.get(key)
        if entry is None:
            return httpx.Response(404, json={"error": {"code": 803, "message": f"No fake for {key}"}})
        if isinstance(entry, list):
            result = entry.pop(0) if len(entry) > 1 else entry[0]
        else:
            result = entry
        if callable(result) and not isinstance(result, httpx.Response):
            result = result(request, flat)
        if isinstance(result, Exception):
            raise result
        if isinstance(result, httpx.Response):
            return result
        return httpx.Response(200, json=result)

    def publisher(self) -> MetaPublisher:
        return MetaPublisher(graph_factory=lambda: MetaGraphClient(transport=httpx.MockTransport(self.handler)))

    def calls_to(self, method: str, path: str) -> list[dict[str, Any]]:
        return [call for call in self.calls if call["method"] == method and call["path"] == path]


def meta_error(status: int, code: int, message: str = "Error", subcode: int | None = None) -> httpx.Response:
    error: dict[str, Any] = {"code": code, "message": message}
    if subcode:
        error["error_subcode"] = subcode
    return httpx.Response(status, json={"error": error})


def no_sleep(_seconds: float) -> None:
    return None


def run_job(db_factory, job_id: str, fake: FakeMeta, **kwargs) -> str | None:
    from app.services.publishing.service import process_publication

    with db_factory() as db:
        return process_publication(
            db,
            UUID(job_id),
            worker_id=kwargs.pop("worker_id", "test-worker"),
            publisher=fake.publisher(),
            sleep=no_sleep,
            poll_interval_seconds=0,
            max_polls=kwargs.pop("max_polls", 3),
            **kwargs,
        )


__all__ = [name for name in dir() if not name.startswith("_")] + ["json", "Callable"]
