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


def resolve_day_time_after(
    day: int, hour: int, minute: int, after: datetime, *, horizon_days: int = 7
) -> tuple[datetime | None, str | None]:
    """The first moment strictly later than ``after`` that has the given day of month, hour and minute.

    This is how the end of a forecast period is read: ``3112/0112`` ends on the next ``01`` after the start, whatever
    the month. Months without the day are skipped. If the first match is more than ``horizon_days`` away the group
    is not a plausible period end and the result is ``(None, WARN_INVALID_TIME)``. Hour 24 rolls over to 00 of the
    next day; impossible days or times give the same warning codes as ``resolve_day_time``.
    """
    if not 1 <= day <= 31:
        return None, WARN_INVALID_DAY
    if not (0 <= hour <= 24 and 0 <= minute <= 59) or (hour == 24 and minute != 0):
        return None, WARN_INVALID_TIME
    if after.tzinfo is None:
        after = after.replace(tzinfo=UTC)
    after = after.astimezone(UTC)
    found: datetime | None = None
    for offset in (-1, 0, 1, 2, 3):
        year, month = _month_start(after.year, after.month, offset)
        try:
            base = datetime(year, month, day, tzinfo=UTC)
        except ValueError:
            continue  # that month has no such day
        candidate = base + timedelta(hours=hour, minutes=minute)
        if candidate > after and (found is None or candidate < found):
            found = candidate
    if found is None or found - after > timedelta(days=horizon_days):
        return None, WARN_INVALID_TIME
    return found, None


def next_clock_time(hour: int, minute: int, not_before: datetime) -> datetime | None:
    """The first moment at or after ``not_before`` whose time of day is ``hour:minute`` (hour 24 means midnight).

    Old-style forecast groups give no day (``FM1800``, ``BECMG 1315``); the day is the first one that keeps them in
    order. ``None`` for an impossible time.
    """
    if not (0 <= hour <= 24 and 0 <= minute <= 59) or (hour == 24 and minute != 0):
        return None
    if not_before.tzinfo is None:
        not_before = not_before.replace(tzinfo=UTC)
    not_before = not_before.astimezone(UTC)
    midnight = not_before.replace(hour=0, minute=0, second=0, microsecond=0)
    for days in (0, 1):
        candidate = midnight + timedelta(days=days, hours=hour, minutes=minute)
        if candidate >= not_before:
            return candidate
    return None
