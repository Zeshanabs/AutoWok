"""Documented metric calculations.

Every function here is deterministic and returns ``None`` whenever the input
does not support a meaningful result (missing values, zero denominators, too
few samples). Calculated values are always labelled as such by the callers;
raw platform metrics are never overwritten.

Definitions
-----------
* **Engagement rate by reach** = engagements / reach x 100.
  Facebook engagements = reactions + comments + shares + post clicks (Meta's
  ``page_post_engagements`` definition); reach = ``post_total_media_view_unique``
  (unique viewers). Instagram engagements = ``total_interactions``
  (likes + saves + comments + shares); reach = ``reach``. Because the two
  platforms count different interactions, rates are never averaged across
  platforms.
* **Percentage change** = (current - previous) / previous x 100, only when the
  previous value is present and non-zero.
* **Follower change** = last follower snapshot - first follower snapshot in the
  period, only when at least two snapshots exist.
* **Rankings** sort by the chosen metric descending with ``None`` values
  excluded, ties broken by publish time (newer first) and then by id so the
  order is stable.
"""

from __future__ import annotations

from datetime import date
from typing import Iterable, Sequence

PLATFORM_ENGAGEMENT_DEFINITION = {
    "facebook_page": "reactions + comments + shares + post clicks",
    "instagram": "total_interactions (likes + saves + comments + shares)",
}
PLATFORM_REACH_DEFINITION = {
    "facebook_page": "unique viewers (post_total_media_view_unique)",
    "instagram": "reach (unique accounts that saw the media)",
}


def engagement_rate(engagements: float | int | None, reach: float | int | None) -> float | None:
    """(engagements / reach) x 100, or None when reach is missing or zero."""
    if engagements is None or reach is None:
        return None
    if reach <= 0:
        return None
    return round(float(engagements) / float(reach) * 100.0, 2)


def percentage_change(current: float | int | None, previous: float | int | None) -> float | None:
    """(current - previous) / previous x 100, or None when previous is missing or zero."""
    if current is None or previous is None:
        return None
    if previous == 0:
        return None
    return round((float(current) - float(previous)) / abs(float(previous)) * 100.0, 2)


def sum_available(values: Iterable[float | int | None]) -> tuple[float | None, int, int]:
    """Sum the non-None values. Returns (sum or None, available count, total count)."""
    total = 0.0
    available = 0
    count = 0
    for value in values:
        count += 1
        if value is None:
            continue
        total += float(value)
        available += 1
    if available == 0:
        return None, 0, count
    return total, available, count


def follower_change(points: Sequence[tuple[date, float | None]]) -> float | None:
    """Difference between the last and the first available follower snapshot."""
    values = [(day, value) for day, value in points if value is not None]
    if len(values) < 2:
        return None
    values.sort(key=lambda item: item[0])
    return values[-1][1] - values[0][1]


def mean(values: Iterable[float | int | None]) -> float | None:
    total, available, _count = sum_available(values)
    if total is None or available == 0:
        return None
    return round(total / available, 2)


def rank(items: Sequence[dict], metric: str, *, descending: bool = True) -> list[dict]:
    """Stable deterministic ranking; items without the metric are excluded."""
    scored = [item for item in items if item.get(metric) is not None]

    def key(item: dict):
        published = item.get("published_at")
        stamp = published.timestamp() if hasattr(published, "timestamp") else 0.0
        return (float(item[metric]), stamp, str(item.get("id", "")))

    return sorted(scored, key=key, reverse=descending)


def consistency(published_days: Sequence[date], start: date, end: date) -> dict:
    """Posting consistency in a period: posts per week and the longest gap in days."""
    days = sorted(set(day for day in published_days if start <= day <= end))
    span_days = (end - start).days + 1
    weeks = max(1.0, span_days / 7.0)
    longest_gap = None
    if days:
        gaps = [(later - earlier).days for earlier, later in zip(days, days[1:])]
        gaps.append((days[0] - start).days)
        gaps.append((end - days[-1]).days)
        longest_gap = max(gaps)
    return {
        "posts": len(published_days),
        "active_days": len(days),
        "posts_per_week": round(len(published_days) / weeks, 2),
        "longest_gap_days": longest_gap,
    }
