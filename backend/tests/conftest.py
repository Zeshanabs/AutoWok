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

    def incr(self, key: str) -> int:
        self.counts[key] += 1
        return self.counts[key]

    def expire(self, key: str, seconds: int) -> bool:
        return True

    def eval(self, script: str, key_count: int, key: str, seconds: int) -> int:
        return self.incr(key)


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
