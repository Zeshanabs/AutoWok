"""Redis wake-up queue for the publishing worker.

Redis is only a low-latency notification channel. The database is the source
of truth: the worker also polls for due jobs, so a Redis restart or a lost
message delays work by at most one poll interval and never loses a job.
"""

from __future__ import annotations

import logging
import time
from uuid import UUID

import redis

from app.services import redis_client as redis_module

logger = logging.getLogger("autowok.publishing")

READY_QUEUE_KEY = "autowok:publishing:ready"


MAX_READY_HINTS = 10_000


def enqueue_publication(publication_id: UUID) -> bool:
    try:
        redis_module.redis_client.lpush(READY_QUEUE_KEY, str(publication_id))
    except (redis.RedisError, OSError):
        logger.warning("Redis unavailable; job %s will be picked up by the database poller.", publication_id)
        return False
    try:
        # Hints are only wake-ups; cap the list so it cannot grow while no worker runs.
        redis_module.redis_client.ltrim(READY_QUEUE_KEY, 0, MAX_READY_HINTS - 1)
    except Exception:  # noqa: BLE001 - trimming is housekeeping
        pass
    return True


def _slice_seconds() -> int:
    """Longest blocking pop that stays below the client's socket timeout."""
    from app.core.config import get_settings

    return max(1, int(get_settings().redis_socket_timeout_seconds) - 1)


def wait_for_publication(timeout_seconds: float, should_stop=None) -> str | None:
    """Wait up to ``timeout_seconds`` for a wake-up. Returns early when
    ``should_stop()`` becomes true so a shutdown signal is honoured quickly."""
    deadline = time.monotonic() + timeout_seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or (should_stop is not None and should_stop()):
            return None
        started = time.monotonic()
        try:
            item = redis_module.redis_client.brpop(
                [READY_QUEUE_KEY], timeout=max(1, min(int(remaining) or 1, _slice_seconds()))
            )
        except (redis.RedisError, OSError):
            logger.warning("Redis unavailable; falling back to database polling.")
            # Keep the poll cadence so a Redis outage does not cause a busy loop.
            if should_stop is None:
                time.sleep(timeout_seconds)
            else:
                for _ in range(max(1, int(remaining))):
                    if should_stop():
                        break
                    time.sleep(1)
            return None
        if item:
            _key, value = item
            return value
        if time.monotonic() - started < 0.5:
            # The pop did not block (for example a stub client); do not spin.
            return None
