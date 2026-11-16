"""Per-request (or per-job) context shared by logging, metrics and error reports.

The context is a mutable dictionary held in a ``ContextVar``. Code running in
the same request or worker job can add fields (for example the workspace once
it has been authorized) and every later log line carries them.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator
from uuid import uuid4

_context: ContextVar[dict[str, Any] | None] = ContextVar("autowok_context", default=None)
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


def new_id() -> str:
    return uuid4().hex


def safe_inbound_id(value: str | None) -> str | None:
    """Accept a caller-supplied request/correlation id only if it is a plain token."""
    return value if value and _SAFE_ID.fullmatch(value) else None


def current() -> dict[str, Any]:
    return _context.get() or {}


def bind(**fields: Any) -> None:
    """Add fields to the active context (no-op outside a request or job)."""
    active = _context.get()
    if active is not None:
        active.update({key: value for key, value in fields.items() if value is not None})


@contextmanager
def scope(**fields: Any) -> Iterator[dict[str, Any]]:
    """Start a fresh context, for example for one request or one background job."""
    values = {key: value for key, value in fields.items() if value is not None}
    token = _context.set(values)
    try:
        yield values
    finally:
        _context.reset(token)
