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


def enqueue_publication(publication_id: UUID) -> bool:
    try:
        redis_module.redis_client.lpush(READY_QUEUE_KEY, str(publication_id))
        return True
    except (redis.RedisError, OSError):
        logger.warning("Redis unavailable; job %s will be picked up by the database poller.", publication_id)
        return False


def wait_for_publication(timeout_seconds: float) -> str | None:
    try:
        item = redis_module.redis_client.brpop([READY_QUEUE_KEY], timeout=max(1, int(timeout_seconds)))
    except (redis.RedisError, OSError):
        logger.warning("Redis unavailable; falling back to database polling.")
        # Keep the poll cadence so a Redis outage does not cause a busy loop.
        time.sleep(timeout_seconds)
        return None
    if not item:
        return None
    _key, value = item
    return value
