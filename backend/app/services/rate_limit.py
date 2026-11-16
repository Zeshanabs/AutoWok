"""Fixed-window rate limits backed by Redis.

Two kinds of key are used:

* address-scoped (``enforce_rate_limit`` with ``per_address=True``): the caller's
  network address is part of the key. Used before authentication, where the
  address is the only identity available.
* identity-scoped (``enforce_user_rate_limit`` or ``per_address=False``): keyed
  by user or account only, so changing address does not reset the limit.

The address is the direct peer. Behind a reverse proxy run uvicorn with
``--proxy-headers --forwarded-allow-ips=<proxy address>`` so that
``request.client.host`` is the real client; arbitrary forwarded headers are
never trusted here.

All limits fail closed: if Redis is unavailable the request is rejected with
503 rather than allowed without a limit.
"""

from __future__ import annotations

import hashlib
from uuid import UUID

import redis
from fastapi import HTTPException, Request, status

from app.core import metrics
from app.services.redis_client import redis_client

_INCREMENT_WITH_EXPIRY = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return count
"""


def _check(key_material: str, *, action: str, limit: int, window_seconds: int, category: str) -> None:
    digest = hashlib.sha256(key_material.encode("utf-8")).hexdigest()
    key = f"auth-rate:{digest}"
    try:
        count = redis_client.eval(_INCREMENT_WITH_EXPIRY, 1, key, window_seconds)
    except redis.RedisError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{category} is temporarily unavailable.",
        ) from exc

    if count > limit:
        metrics.RATE_LIMITED.labels(action=action).inc()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many {category.lower()} requests. Please try again later.",
            headers={"Retry-After": str(window_seconds)},
        )


def enforce_rate_limit(
    request: Request,
    *,
    action: str,
    identity: str,
    limit: int,
    window_seconds: int,
    category: str = "Authentication",
    per_address: bool = True,
) -> None:
    address = (request.client.host if request.client else "unknown") if per_address else "*"
    _check(
        f"{action}:{identity.casefold()}:{address}",
        action=action,
        limit=limit,
        window_seconds=window_seconds,
        category=category,
    )


def enforce_user_rate_limit(
    user_id: UUID | str,
    *,
    action: str,
    limit: int,
    window_seconds: int = 3600,
    category: str,
) -> None:
    """Limit an authenticated user's use of an expensive feature, regardless of address."""
    _check(
        f"user:{action}:{user_id}",
        action=action,
        limit=limit,
        window_seconds=window_seconds,
        category=category,
    )
