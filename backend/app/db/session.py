from __future__ import annotations

from typing import Any, Iterable

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import get_settings

settings = get_settings()


def _engine_options() -> dict[str, Any]:
    """Pool and timeout settings. PostgreSQL only; SQLite (tests) uses defaults."""
    options: dict[str, Any] = {"pool_pre_ping": True}
    if make_url(settings.database_url).get_backend_name() != "postgresql":
        return options
    server_options = []
    if settings.db_statement_timeout_ms:
        server_options.append(f"-c statement_timeout={settings.db_statement_timeout_ms}")
    connect_args: dict[str, Any] = {
        "connect_timeout": settings.db_connect_timeout_seconds,
        "application_name": settings.service_name[:60],
    }
    if server_options:
        connect_args["options"] = " ".join(server_options)
    options.update(
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_seconds,
        pool_recycle=settings.db_pool_recycle_seconds,
        connect_args=connect_args,
    )
    return options


engine = create_engine(settings.database_url, **_engine_options())
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def preload(db: DBSession, model: Any, ids: Iterable[Any]) -> list[Any]:
    """Load rows by primary key in one query so later ``db.get`` calls are served
    from the session without SQL. Keep the returned list alive while the rows
    are in use (the session only holds weak references).
    """
    wanted = {value for value in ids if value is not None}
    if not wanted:
        return []
    return db.query(model).filter(model.id.in_(wanted)).all()
