from __future__ import annotations

import random
from datetime import datetime, timedelta

from app.core.config import get_settings
from app.services.publishing.errors import RATE_LIMITED


def backoff_delay_seconds(attempt_number: int, category: str, rng: random.Random | None = None) -> float:
    """Bounded exponential backoff with "equal jitter"."""
    settings = get_settings()
    rng = rng or random.Random()
    base = settings.publishing_backoff_base_seconds
    cap = settings.publishing_backoff_max_seconds
    if category == RATE_LIMITED:
        base = max(base, 300)
    exponential = min(cap, base * (2 ** max(0, attempt_number - 1)))
    return exponential / 2 + rng.uniform(0, exponential / 2)


def next_attempt_time(now: datetime, attempt_number: int, category: str, rng: random.Random | None = None) -> datetime:
    return now + timedelta(seconds=backoff_delay_seconds(attempt_number, category, rng))
