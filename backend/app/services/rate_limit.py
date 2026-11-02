from __future__ import annotations

import hashlib

import redis
from fastapi import HTTPException, Request, status

from app.services.redis_client import redis_client

_INCREMENT_WITH_EXPIRY = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return count
"""


def enforce_rate_limit(
    request: Request,
    *,
    action: str,
    identity: str,
    limit: int,
    window_seconds: int,
) -> None:
    address = request.client.host if request.client else "unknown"
    key_material = f"{action}:{identity.casefold()}:{address}"
    digest = hashlib.sha256(key_material.encode("utf-8")).hexdigest()
    key = f"auth-rate:{digest}"
    try:
        count = redis_client.eval(_INCREMENT_WITH_EXPIRY, 1, key, window_seconds)
    except redis.RedisError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is temporarily unavailable.",
        ) from exc

    if count > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many authentication attempts. Please try again later.",
            headers={"Retry-After": str(window_seconds)},
        )
