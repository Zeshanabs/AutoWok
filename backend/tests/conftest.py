from __future__ import annotations

from collections import defaultdict
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base, get_db
from app.main import app
from app.models import AuditLog, Session, User, Workspace, WorkspaceMembership  # noqa: F401


class FakeRedis:
    def __init__(self) -> None:
        self.counts: defaultdict[str, int] = defaultdict(int)
        self.lists: dict[str, list[str]] = {}

    def incr(self, key: str) -> int:
        self.counts[key] += 1
        return self.counts[key]

    def expire(self, key: str, seconds: int) -> bool:
        return True

    def eval(self, script: str, key_count: int, key: str, seconds: int) -> int:
        return self.incr(key)

    def ping(self) -> bool:
        return True

    def lpush(self, key: str, *values: str) -> int:
        queue = self.lists.setdefault(key, [])
        for value in values:
            queue.insert(0, value)
        return len(queue)

    def brpop(self, keys, timeout: int = 0):
        for key in keys:
            queue = self.lists.get(key)
            if queue:
                return key, queue.pop()
        return None


@pytest.fixture
def db_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def client_factory(db_factory, monkeypatch):
    def override_get_db():
        db = db_factory()
        try:
            yield db
        finally:
            db.close()

    from app.services import rate_limit
    from app.api.v1.routes import health

    monkeypatch.setattr(rate_limit, "redis_client", FakeRedis())
    monkeypatch.setattr(health, "ping_redis", lambda: True)
    app.dependency_overrides[get_db] = override_get_db

    def create_client() -> TestClient:
        return TestClient(app)

    yield create_client
    app.dependency_overrides.clear()


@pytest.fixture
def client(client_factory) -> Generator[TestClient, None, None]:
    with client_factory() as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def isolated_media_environment(tmp_path, monkeypatch):
    """Keep uploaded files, Redis messages, and media/token secrets test-local."""
    from app.core.config import get_settings
    from app.services import redis_client as redis_module
    from app.services.storage import storage_service

    media_root = (tmp_path / "media").resolve()
    media_root.mkdir()
    monkeypatch.setattr(storage_service, "base_path", media_root)
    fake_redis = FakeRedis()
    monkeypatch.setattr(redis_module, "redis_client", fake_redis)
    settings = get_settings()
    monkeypatch.setattr(settings, "media_url_signing_secret", "test-media-signing-secret-0123456789abcdef")
    monkeypatch.setattr(settings, "public_media_base_url", "https://media.autowok.test")
    monkeypatch.setattr(settings, "publishing_backoff_base_seconds", 30.0)
    monkeypatch.setattr(settings, "publishing_max_attempts", 3)
    yield fake_redis


@pytest.fixture
def token_key(monkeypatch):
    from cryptography.fernet import Fernet

    from app.core.config import get_settings

    settings = get_settings()
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setattr(settings, "meta_token_encryption_key", key)
    monkeypatch.setattr(settings, "meta_token_encryption_key_previous", "")
    return key
