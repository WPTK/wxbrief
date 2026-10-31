"""Resolving the day-of-month timestamps used in reports (``DDHHMMZ``) to real datetimes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

WARN_INVALID_DAY = "invalid_day"
WARN_INVALID_TIME = "invalid_time"


def _month_start(year: int, month: int, offset: int) -> tuple[int, int]:
    """Return the (year, month) that is ``offset`` months away from the given one."""
    index = year * 12 + (month - 1) + offset
    return index // 12, index % 12 + 1


def resolve_day_time(day: int, hour: int, minute: int, reference: datetime) -> tuple[datetime | None, str | None]:
    """Resolve a day/hour/minute group against a reference moment.

    Reports carry only the day of the month, so the real date is the candidate (previous, current or next month)
    nearest to ``reference``; ties go to the earlier one because reports describe the past. An hour of 24 rolls
    over to 00 of the next day. Returns ``(datetime, None)`` in UTC on success, or ``(None, warning_code)`` when the
    day or time cannot exist (the caller turns the code into a ``ParseWarning``).
    """
    if not 1 <= day <= 31:
        return None, WARN_INVALID_DAY
    if not (0 <= hour <= 24 and 0 <= minute <= 59):
        return None, WARN_INVALID_TIME
    if hour == 24 and minute != 0:
        return None, WARN_INVALID_TIME
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    reference = reference.astimezone(UTC)

    candidates: list[datetime] = []
    for offset in (-1, 0, 1):
        year, month = _month_start(reference.year, reference.month, offset)
        try:
            base = datetime(year, month, day, tzinfo=UTC)
        except ValueError:
            continue  # that month has no such day
        candidates.append(base + timedelta(hours=hour, minutes=minute))
    if not candidates:
        return None, WARN_INVALID_DAY
    best = min(candidates, key=lambda moment: (abs(moment - reference), moment))
    return best, None


def resolve_clock_time(hour: int, minute: int, reference: datetime | None) -> datetime | None:
    """Resolve an ``HHMM`` time of day (``FM1130``) to the occurrence nearest to ``reference``.

    Trends and forecast periods give no date, so the day is the one (yesterday, today or tomorrow) that puts the time
    closest to the observation; ties go to the earlier one. Hour 24 rolls over. ``None`` without a reference or for
    an impossible time.
    """
    if reference is None:
        return None
    if not (0 <= hour <= 24 and 0 <= minute <= 59) or (hour == 24 and minute != 0):
        return None
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    reference = reference.astimezone(UTC)
    midnight = reference.replace(hour=0, minute=0, second=0, microsecond=0)
    candidates = [midnight + timedelta(days=days, hours=hour, minutes=minute) for days in (-1, 0, 1)]
    return min(candidates, key=lambda moment: (abs(moment - reference), moment))
