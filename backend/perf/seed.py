"""Seed a NON-PRODUCTION database with realistic volumes for performance tests.

Usage (from ``backend/``)::

    DATABASE_URL=postgresql+psycopg://.../autowok_perf PERF_ALLOW_SEED=1 \
        python -m perf.seed

The script refuses to run unless ``PERF_ALLOW_SEED=1`` is set and the database
name contains ``perf``, ``test`` or ``p12``; it also refuses a database that
already holds users. It never deletes anything.

It prints the credentials and workspace id used by ``perf.bench``.
"""

from __future__ import annotations

import json
import os
import random
import sys
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from sqlalchemy import insert
from sqlalchemy.engine import make_url

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import (
    AnalyticsSnapshot,
    Brand,
    BrandVoice,
    ContentDraft,
    ContentProject,
    ContentPublication,
    ContentVersion,
    MediaAsset,
    Notification,
    PostAnalytics,
    ScheduledPost,
    SocialAccount,
    User,
    Workspace,
    WorkspaceMembership,
)
from app.services.passwords import hash_password

PERF_EMAIL = "perf-owner@example.com"
PERF_PASSWORD = "PerfPassword#12345"

MAIN = {"brands": 5, "projects": 2000, "media": 1500, "scheduled": 1200, "publications": 1000, "posts": 1500, "notifications": 2000}
NOISE_WORKSPACES = 30
NOISE = {"projects": 300, "media": 200, "scheduled": 150, "posts": 200}
SNAPSHOT_DAYS = 90
METRICS = ["reach", "views", "engagements", "followers", "follows", "likes", "comments", "shares", "saves", "clicks"]


def _guard() -> None:
    name = make_url(get_settings().database_url).database or ""
    if os.environ.get("PERF_ALLOW_SEED") != "1" or not any(tag in name for tag in ("perf", "test", "p12")):
        sys.exit("Refusing to seed: set PERF_ALLOW_SEED=1 and use a database whose name contains perf, test or p12.")


def _bulk(db, model, rows: list[dict], chunk: int = 2000) -> None:
    for start in range(0, len(rows), chunk):
        db.execute(insert(model), rows[start : start + chunk])


def _workspace(db, rng: random.Random, owner: User, name: str, sizes: dict, *, brands: int) -> dict:
    now = datetime.now(UTC)
    workspace = Workspace(id=uuid4(), name=name, slug=f"{name.lower().replace(' ', '-')}-{uuid4().hex[:8]}", owner_id=owner.id)
    db.add(workspace)
    db.add(WorkspaceMembership(workspace=workspace, user=owner, role="OWNER"))
    db.flush()
    brand_ids = []
    for index in range(brands):
        brand = Brand(workspace_id=workspace.id, name=f"Brand {index}", slug=f"brand-{index}", industry="Retail", created_by=owner.id)
        db.add(brand)
        db.flush()
        db.add(BrandVoice(brand_id=brand.id, tone="Warm"))
        brand_ids.append(brand.id)
    accounts = []
    for platform in ("facebook_page", "instagram"):
        account = SocialAccount(
            workspace_id=workspace.id,
            brand_id=brand_ids[0],
            platform=platform,
            platform_account_id=f"{platform}-{uuid4().hex[:10]}",
            username="perf",
            display_name=f"Perf {platform}",
            account_type="PAGE" if platform == "facebook_page" else "BUSINESS",
            connection_status="connected",
            granted_scopes=[],
            connected_by=owner.id,
        )
        db.add(account)
        accounts.append(account)
    db.flush()

    projects, drafts, versions = [], [], []
    draft_index: list[tuple] = []
    for index in range(sizes["projects"]):
        project_id = uuid4()
        created = now - timedelta(minutes=rng.randint(0, 120 * 24 * 60))
        status = rng.choice(["draft", "draft", "in_review", "approved", "approved"])
        projects.append(
            {
                "id": project_id,
                "workspace_id": workspace.id,
                "brand_id": rng.choice(brand_ids),
                "created_by": owner.id,
                "title": f"Campaign post {index}",
                "topic": "Seasonal launch",
                "selected_platforms": ["facebook", "instagram"],
                "status": status,
                "created_at": created,
                "updated_at": created,
            }
        )
        for platform in ("facebook", "instagram"):
            draft_id = uuid4()
            drafts.append(
                {
                    "id": draft_id,
                    "project_id": project_id,
                    "platform": platform,
                    "title": f"Draft {index}",
                    "hook": "Big news for the season.",
                    "body": "We are launching a new range. " * 12,
                    "cta": "Learn more on our site.",
                    "hashtags": ["#launch", "#new"],
                    "status": status,
                    "version_count": 3,
                    "created_at": created,
                    "updated_at": created,
                }
            )
            draft_index.append((project_id, draft_id, platform))
            for number in (1, 2, 3):
                versions.append(
                    {
                        "id": uuid4(),
                        "draft_id": draft_id,
                        "version_number": number,
                        "platform": platform,
                        "title": f"Draft {index}",
                        "hook": "Big news for the season.",
                        "body": "We are launching a new range. " * 12,
                        "cta": "Learn more on our site.",
                        "hashtags": ["#launch", "#new"],
                        "created_by": owner.id,
                        "created_at": created,
                    }
                )
    _bulk(db, ContentProject, projects)
    _bulk(db, ContentDraft, drafts)
    _bulk(db, ContentVersion, versions)

    media = []
    for index in range(sizes["media"]):
        created = now - timedelta(minutes=rng.randint(0, 120 * 24 * 60))
        key = f"workspaces/{workspace.id}/{uuid4().hex}.jpg"
        media.append(
            {
                "id": uuid4(),
                "workspace_id": workspace.id,
                "brand_id": rng.choice(brand_ids),
                "original_filename": f"photo-{index}.jpg",
                "title": f"Photo {index}",
                "storage_key": key,
                "mime_type": "image/jpeg",
                "file_extension": "jpg",
                "file_size": 250_000,
                "width": 1080,
                "height": 1080,
                "checksum": uuid4().hex + uuid4().hex,
                "processing_status": "ready",
                "uploaded_by": owner.id,
                "created_at": created,
                "updated_at": created,
            }
        )
    _bulk(db, MediaAsset, media)

    publications, scheduled = [], []
    for index in range(sizes.get("publications", 0)):
        project_id, draft_id, platform = rng.choice(draft_index)
        account = accounts[0] if platform == "facebook" else accounts[1]
        at = now - timedelta(minutes=rng.randint(0, 60 * 24 * 60))
        publications.append(
            {
                "id": uuid4(),
                "workspace_id": workspace.id,
                "requested_by": owner.id,
                "source": "manual",
                "idempotency_key": f"perf-{uuid4().hex}",
                "project_id": project_id,
                "draft_id": draft_id,
                "social_account_id": account.id,
                "platform": platform,
                "status": rng.choice(["published"] * 9 + ["failed"]),
                "caption": "We are launching a new range.",
                "content_version_number": 3,
                "external_post_id": f"ext-{index}",
                "published_at": at,
                "created_at": at,
                "updated_at": at,
            }
        )
    _bulk(db, ContentPublication, publications)
    for index in range(sizes["scheduled"]):
        project_id, draft_id, platform = rng.choice(draft_index)
        account = accounts[0] if platform == "facebook" else accounts[1]
        at = now + timedelta(minutes=rng.randint(-45 * 24 * 60, 45 * 24 * 60))
        future = at > now
        post_id = uuid4()
        scheduled.append(
            {
                "id": post_id,
                "workspace_id": workspace.id,
                "project_id": project_id,
                "draft_id": draft_id,
                "social_account_id": account.id,
                "brand_id": brand_ids[0],
                "platform": platform,
                "scheduled_at": at,
                "scheduled_local": at.strftime("%Y-%m-%dT%H:%M:%S"),
                "timezone": "UTC",
                "status": "scheduled" if future else rng.choice(["published", "published", "cancelled", "failed"]),
                "content_version_number": 3,
                "active_guard": f"perf:{post_id}" if future else None,
                "created_by": owner.id,
                "created_at": now,
                "updated_at": now,
            }
        )
    _bulk(db, ScheduledPost, scheduled)

    snapshots = []
    today = date.today()
    for account in accounts:
        for offset in range(SNAPSHOT_DAYS):
            for metric in METRICS:
                snapshots.append(
                    {
                        "id": uuid4(),
                        "workspace_id": workspace.id,
                        "brand_id": brand_ids[0],
                        "social_account_id": account.id,
                        "platform": account.platform,
                        "metric_key": metric,
                        "source_metric": metric,
                        "period": "day",
                        "snapshot_date": today - timedelta(days=offset),
                        "metric_value": float(rng.randint(10, 5000)),
                        "api_version": "v26.0",
                    }
                )
    _bulk(db, AnalyticsSnapshot, snapshots)

    posts = []
    for index in range(sizes["posts"]):
        account = rng.choice(accounts)
        reach = rng.randint(100, 20000)
        posts.append(
            {
                "id": uuid4(),
                "workspace_id": workspace.id,
                "brand_id": brand_ids[0],
                "social_account_id": account.id,
                "platform": account.platform,
                "external_post_id": f"post-{index}",
                "published_at": now - timedelta(minutes=rng.randint(0, 90 * 24 * 60)),
                "content_format": rng.choice(["image", "video", "reel", "carousel", "text"]),
                "caption_preview": f"Post {index} about the seasonal launch",
                "reach": reach,
                "views": reach * 2,
                "engagements": reach // 12,
                "likes": reach // 20,
                "comments": reach // 200,
                "shares": reach // 300,
            }
        )
    _bulk(db, PostAnalytics, posts)

    notifications = [
        {
            "id": uuid4(),
            "workspace_id": workspace.id,
            "user_id": owner.id,
            "category": "automation",
            "title": f"Notification {index}",
            "message": "A post is waiting for review.",
            "created_at": now - timedelta(minutes=index),
        }
        for index in range(sizes.get("notifications", 0))
    ]
    _bulk(db, Notification, notifications)
    return {"workspace_id": str(workspace.id), "brand_id": str(brand_ids[0])}


def main() -> None:
    _guard()
    rng = random.Random(12)
    with SessionLocal() as db:
        if db.query(User.id).first() is not None:
            sys.exit("Refusing to seed: the database already contains users.")
        owner = User(full_name="Perf Owner", email=PERF_EMAIL, password_hash=hash_password(PERF_PASSWORD), is_active=True, is_verified=True)
        other = User(full_name="Noise Owner", email="perf-noise@example.com", password_hash=hash_password(PERF_PASSWORD), is_active=True)
        db.add_all([owner, other])
        db.flush()
        main_ws = _workspace(db, rng, owner, "Perf main", MAIN, brands=MAIN["brands"])
        for index in range(NOISE_WORKSPACES):
            _workspace(db, rng, other, f"Noise {index}", NOISE, brands=2)
        db.commit()
    print(json.dumps({"email": PERF_EMAIL, "password": PERF_PASSWORD, **main_ws, "main": MAIN, "noise_workspaces": NOISE_WORKSPACES, "noise": NOISE}))


if __name__ == "__main__":
    main()
