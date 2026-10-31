"""Day-of-month timestamp resolution."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from wxbrief.decode.times import WARN_INVALID_DAY, WARN_INVALID_TIME, resolve_day_time, resolve_report_time


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def test_same_month() -> None:
    assert resolve_report_time(13, 14, 53, utc(2026, 10, 13, 15, 0)) == (utc(2026, 10, 13, 14, 53), None)


def test_report_older_than_half_a_month_stays_in_the_past() -> None:
    # The nearest-month rule put this on 2026-11-14.
    assert resolve_report_time(14, 11, 53, utc(2026, 10, 31, 12, 0))[0] == utc(2026, 10, 14, 11, 53)


def test_report_from_the_previous_month() -> None:
    assert resolve_report_time(31, 23, 50, utc(2026, 11, 1, 0, 10))[0] == utc(2026, 10, 31, 23, 50)
    assert resolve_report_time(20, 12, 0, utc(2026, 11, 5, 0, 0))[0] == utc(2026, 10, 20, 12, 0)


def test_report_a_few_minutes_ahead_of_the_clock_is_tolerated() -> None:
    assert resolve_report_time(1, 0, 20, utc(2026, 10, 31, 23, 50))[0] == utc(2026, 11, 1, 0, 20)


def test_report_many_hours_ahead_is_a_month_old() -> None:
    assert resolve_report_time(1, 12, 0, utc(2026, 10, 31, 23, 50))[0] == utc(2026, 10, 1, 12, 0)


def test_year_boundaries() -> None:
    assert resolve_report_time(31, 23, 50, utc(2027, 1, 1, 0, 5))[0] == utc(2026, 12, 31, 23, 50)
    assert resolve_report_time(1, 0, 5, utc(2026, 12, 31, 23, 55))[0] == utc(2027, 1, 1, 0, 5)
    assert resolve_report_time(20, 12, 0, utc(2027, 1, 5, 0, 0))[0] == utc(2026, 12, 20, 12, 0)


def test_hour_24_rolls_over_to_the_next_day() -> None:
    assert resolve_report_time(31, 24, 0, utc(2026, 10, 31, 23, 59))[0] == utc(2026, 11, 1, 0, 0)


def test_months_without_the_day_are_skipped() -> None:
    assert resolve_report_time(31, 12, 0, utc(2026, 11, 20, 0, 0))[0] == utc(2026, 10, 31, 12, 0)
    assert resolve_report_time(31, 12, 0, utc(2026, 12, 2, 0, 0))[0] == utc(2026, 10, 31, 12, 0)


def test_leap_day() -> None:
    assert resolve_report_time(29, 6, 0, utc(2028, 2, 29, 12, 0))[0] == utc(2028, 2, 29, 6, 0)
    assert resolve_report_time(29, 6, 0, utc(2027, 2, 20, 0, 0))[0] == utc(2027, 1, 29, 6, 0)


def test_forecast_groups_use_the_nearest_candidate() -> None:
    assert resolve_day_time(1, 0, 20, utc(2026, 10, 31, 23, 50))[0] == utc(2026, 11, 1, 0, 20)
    assert resolve_day_time(31, 23, 50, utc(2026, 11, 1, 0, 10))[0] == utc(2026, 10, 31, 23, 50)
    earlier = utc(2026, 9, 15, 12, 0)
    midpoint = earlier + (utc(2026, 10, 15, 12, 0) - earlier) / 2
    assert resolve_day_time(15, 12, 0, midpoint)[0] == earlier


@pytest.mark.parametrize("day", [0, 32, 99])
def test_invalid_day(day: int) -> None:
    assert resolve_day_time(day, 12, 0, utc(2026, 10, 13)) == (None, WARN_INVALID_DAY)
    assert resolve_report_time(day, 12, 0, utc(2026, 10, 13)) == (None, WARN_INVALID_DAY)


@pytest.mark.parametrize(("hour", "minute"), [(25, 0), (12, 60), (24, 30), (-1, 0)])
def test_invalid_time(hour: int, minute: int) -> None:
    assert resolve_day_time(13, hour, minute, utc(2026, 10, 13)) == (None, WARN_INVALID_TIME)
    assert resolve_report_time(13, hour, minute, utc(2026, 10, 13)) == (None, WARN_INVALID_TIME)


def test_naive_reference_is_taken_as_utc() -> None:
    assert resolve_report_time(13, 14, 53, datetime(2026, 10, 13, 15, 0))[0] == utc(2026, 10, 13, 14, 53)
