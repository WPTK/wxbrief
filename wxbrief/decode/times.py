"""Resolving the day-of-month timestamps used in reports (``DDHHMMZ``) to real datetimes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

WARN_INVALID_DAY = "invalid_day"
WARN_INVALID_TIME = "invalid_time"

# How far after the reference a report time may lie and still be taken as a report of the past.
FUTURE_TOLERANCE = timedelta(hours=3)


def _month_start(year: int, month: int, offset: int) -> tuple[int, int]:
    """Return the (year, month) that is ``offset`` months away from the given one."""
    index = year * 12 + (month - 1) + offset
    return index // 12, index % 12 + 1


def _check_time(day: int, hour: int, minute: int) -> str | None:
    if not 1 <= day <= 31:
        return WARN_INVALID_DAY
    if not (0 <= hour <= 24 and 0 <= minute <= 59) or (hour == 24 and minute != 0):
        return WARN_INVALID_TIME
    return None


def _as_utc(moment: datetime) -> datetime:
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def _candidates(day: int, hour: int, minute: int, reference: datetime, offsets: range) -> list[datetime]:
    """The moments with this day of month, hour and minute in the months ``offsets`` away from the reference's."""
    found: list[datetime] = []
    for offset in offsets:
        year, month = _month_start(reference.year, reference.month, offset)
        try:
            base = datetime(year, month, day, tzinfo=UTC)
        except ValueError:
            continue  # that month has no such day
        found.append(base + timedelta(hours=hour, minutes=minute))
    return found


def resolve_report_time(day: int, hour: int, minute: int, reference: datetime) -> tuple[datetime | None, str | None]:
    """Resolve the ``DDHHMMZ`` issue time of a report against the moment it is being read.

    A report describes the past, so its time is the latest moment with that day, hour and minute that is not more than
    ``FUTURE_TOLERANCE`` after ``reference`` (the slack covers clock skew and a pasted report from a station whose
    clock runs ahead). Picking the nearest month instead put anything older than about 15 days in next month. An
    hour of 24 rolls over to 00 of the next day. Returns ``(datetime, None)`` in UTC, or ``(None, warning_code)`` when
    the day or time cannot exist (the caller turns the code into a ``ParseWarning``).
    """
    warning = _check_time(day, hour, minute)
    if warning is not None:
        return None, warning
    reference = _as_utc(reference)
    limit = reference + FUTURE_TOLERANCE
    # Three months back is enough: no run of months lacks a given day for longer than that.
    past = [moment for moment in _candidates(day, hour, minute, reference, range(-3, 2)) if moment <= limit]
    if not past:
        return None, WARN_INVALID_DAY
    return max(past), None


def resolve_day_time(day: int, hour: int, minute: int, reference: datetime) -> tuple[datetime | None, str | None]:
    """Resolve a day/hour/minute group of a forecast against a nearby reference moment (its issue time or period).

    Forecast groups lie on either side of the reference, so the real date is the candidate (previous, current or next
    month) nearest to it; ties go to the earlier one. For the issue time of a report use ``resolve_report_time``.
    An hour of 24 rolls over to 00 of the next day. Returns ``(datetime, None)`` in UTC on success, or
    ``(None, warning_code)`` when the day or time cannot exist.
    """
    warning = _check_time(day, hour, minute)
    if warning is not None:
        return None, warning
    reference = _as_utc(reference)
    candidates = _candidates(day, hour, minute, reference, range(-1, 2))
    if not candidates:
        return None, WARN_INVALID_DAY
    return min(candidates, key=lambda moment: (abs(moment - reference), moment)), None


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
