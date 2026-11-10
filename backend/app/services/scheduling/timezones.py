"""Timezone handling for scheduling and the calendar.

Rules:
* Instants are stored in UTC. The user's wall-clock choice is kept as
  ``YYYY-MM-DDTHH:MM`` plus an IANA timezone name.
* Wall-clock times that do not exist (DST "spring forward" gaps) are rejected.
* Times that occur twice (DST "fall back") are rejected unless the caller
  explicitly picks the earlier or later occurrence.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

UTC = timezone.utc
LOCAL_FORMAT = "%Y-%m-%dT%H:%M"


class TimezoneError(ValueError):
    pass


def get_zone(name: str) -> ZoneInfo:
    if not name or len(name) > 64 or name.startswith("/") or ".." in name:
        raise TimezoneError("Choose a valid IANA timezone, for example UTC or Asia/Karachi.")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise TimezoneError(f"Unknown timezone '{name}'. Use an IANA name such as Europe/London.") from exc


def is_valid_timezone(name: str) -> bool:
    try:
        get_zone(name)
        return True
    except TimezoneError:
        return False


def ensure_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def parse_local(value: str) -> datetime:
    text = value.strip()
    for fmt in (LOCAL_FORMAT, "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.replace(second=0, microsecond=0)
        except ValueError:
            continue
    raise TimezoneError("Enter the date and time as YYYY-MM-DDTHH:MM.")


def local_to_utc(local_value: str, tz_name: str, *, ambiguous: str | None = None) -> tuple[datetime, str]:
    """Convert a wall-clock time in ``tz_name`` to UTC, rejecting DST edge cases."""
    zone = get_zone(tz_name)
    naive = parse_local(local_value)
    earlier = naive.replace(tzinfo=zone, fold=0)
    later = naive.replace(tzinfo=zone, fold=1)

    round_trip = earlier.astimezone(UTC).astimezone(zone).replace(tzinfo=None)
    if round_trip != naive:
        raise TimezoneError(
            f"{naive.strftime('%Y-%m-%d %H:%M')} does not exist in {tz_name} because of a daylight-saving "
            "change. Choose a different time."
        )
    if earlier.utcoffset() != later.utcoffset():
        if ambiguous not in {"earlier", "later"}:
            raise TimezoneError(
                f"{naive.strftime('%Y-%m-%d %H:%M')} happens twice in {tz_name} because clocks go back. "
                "Choose the earlier or later occurrence, or pick a different time."
            )
        chosen = earlier if ambiguous == "earlier" else later
    else:
        chosen = earlier
    return chosen.astimezone(UTC), naive.strftime(LOCAL_FORMAT)


def utc_to_local(value: datetime, tz_name: str) -> str:
    return ensure_utc(value).astimezone(get_zone(tz_name)).strftime(LOCAL_FORMAT)


def utc_offset_label(value: datetime, tz_name: str) -> str:
    local = ensure_utc(value).astimezone(get_zone(tz_name))
    offset = local.utcoffset() or timedelta(0)
    minutes = int(offset.total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    minutes = abs(minutes)
    return f"UTC{sign}{minutes // 60:02d}:{minutes % 60:02d}"


def _local_midnight_utc(day: date, zone: ZoneInfo) -> datetime:
    # Midnight can be skipped by DST in a few zones; use the first instant of the day.
    candidate = datetime.combine(day, time(0, 0)).replace(tzinfo=zone)
    if candidate.astimezone(UTC).astimezone(zone).date() != day:
        candidate = datetime.combine(day, time(1, 0)).replace(tzinfo=zone)
    return candidate.astimezone(UTC)


def calendar_range(view: str, anchor: date, tz_name: str, *, list_days: int = 30) -> tuple[datetime, datetime, list[date]]:
    """Return (start_utc, end_utc, local_days) for a calendar view.

    * day   – the anchor day
    * week  – Monday to Sunday containing the anchor
    * month – whole Monday-start weeks covering the anchor's month (the grid)
    * list  – ``list_days`` days starting at the anchor
    End is exclusive.
    """
    zone = get_zone(tz_name)
    if view == "day":
        first, last = anchor, anchor
    elif view == "week":
        first = anchor - timedelta(days=anchor.weekday())
        last = first + timedelta(days=6)
    elif view == "month":
        month_start = anchor.replace(day=1)
        next_month = (month_start + timedelta(days=32)).replace(day=1)
        month_end = next_month - timedelta(days=1)
        first = month_start - timedelta(days=month_start.weekday())
        last = month_end + timedelta(days=6 - month_end.weekday())
    elif view == "list":
        first, last = anchor, anchor + timedelta(days=list_days - 1)
    else:
        raise TimezoneError("view must be one of month, week, day, or list.")
    days = [first + timedelta(days=offset) for offset in range((last - first).days + 1)]
    return _local_midnight_utc(first, zone), _local_midnight_utc(last + timedelta(days=1), zone), days


def common_timezones() -> list[str]:
    return sorted(zone for zone in available_timezones() if "/" in zone or zone == "UTC")
