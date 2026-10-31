"""Day-of-month timestamp resolution."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from wxbrief.decode.times import WARN_INVALID_DAY, WARN_INVALID_TIME, resolve_day_time


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def test_same_month() -> None:
    assert resolve_day_time(13, 14, 53, utc(2026, 10, 13, 15, 0)) == (utc(2026, 10, 13, 14, 53), None)


def test_report_from_the_previous_month() -> None:
    # Reference is early on 1 Nov; a report for the 31st is from October.
    assert resolve_day_time(31, 23, 50, utc(2026, 11, 1, 0, 10))[0] == utc(2026, 10, 31, 23, 50)


def test_report_for_the_next_month() -> None:
    # Reference is late on 31 Oct; a report for the 1st is from November.
    assert resolve_day_time(1, 0, 20, utc(2026, 10, 31, 23, 50))[0] == utc(2026, 11, 1, 0, 20)


def test_year_boundaries() -> None:
    assert resolve_day_time(31, 23, 50, utc(2027, 1, 1, 0, 5))[0] == utc(2026, 12, 31, 23, 50)
    assert resolve_day_time(1, 0, 5, utc(2026, 12, 31, 23, 55))[0] == utc(2027, 1, 1, 0, 5)


def test_hour_24_rolls_over_to_the_next_day() -> None:
    assert resolve_day_time(31, 24, 0, utc(2026, 10, 31, 23, 59))[0] == utc(2026, 11, 1, 0, 0)


def test_months_without_the_day_are_skipped() -> None:
    # November has no 31st, so a "31" next to 20 Nov can only be 31 Oct (or 31 Dec, which is further away).
    assert resolve_day_time(31, 12, 0, utc(2026, 11, 20, 0, 0))[0] == utc(2026, 10, 31, 12, 0)
    assert resolve_day_time(31, 12, 0, utc(2026, 12, 2, 0, 0))[0] == utc(2026, 12, 31, 12, 0)


def test_leap_day() -> None:
    assert resolve_day_time(29, 6, 0, utc(2028, 2, 29, 12, 0))[0] == utc(2028, 2, 29, 6, 0)
    # 29 Feb 2027 does not exist: the nearest 29th is in January or March.
    result = resolve_day_time(29, 6, 0, utc(2027, 2, 20, 0, 0))[0]
    assert result in (utc(2027, 1, 29, 6, 0), utc(2027, 3, 29, 6, 0))


def test_ties_go_to_the_earlier_candidate() -> None:
    earlier = utc(2026, 9, 15, 12, 0)
    later = utc(2026, 10, 15, 12, 0)
    midpoint = earlier + (later - earlier) / 2
    assert resolve_day_time(15, 12, 0, midpoint)[0] == earlier


@pytest.mark.parametrize("day", [0, 32, 99])
def test_invalid_day(day: int) -> None:
    assert resolve_day_time(day, 12, 0, utc(2026, 10, 13)) == (None, WARN_INVALID_DAY)


@pytest.mark.parametrize(("hour", "minute"), [(25, 0), (12, 60), (24, 30), (-1, 0)])
def test_invalid_time(hour: int, minute: int) -> None:
    assert resolve_day_time(13, hour, minute, utc(2026, 10, 13)) == (None, WARN_INVALID_TIME)


def test_naive_reference_is_taken_as_utc() -> None:
    assert resolve_day_time(13, 14, 53, datetime(2026, 10, 13, 15, 0))[0] == utc(2026, 10, 13, 14, 53)
