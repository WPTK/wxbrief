"""Red-team tests for day-first DDHHMMZ resolution: month ends, year ends, leap days, DST, zone-aware references."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from wxbrief.decode.metar import parse_metar
from wxbrief.decode.taf import parse_taf
from wxbrief.decode.times import resolve_report_time

BODY = "00000KT 10SM CLR 10/05 A3000"


def observed(day_hhmm: str, ref: datetime) -> datetime | None:
    return parse_metar(f"KDEN {day_hhmm}Z {BODY}", ref).observed


@pytest.mark.parametrize(
    ("report", "ref", "expected"),
    [
        ("312355", datetime(2026, 11, 1, 0, 10, tzinfo=UTC), datetime(2026, 10, 31, 23, 55, tzinfo=UTC)),
        ("312355", datetime(2027, 1, 1, 0, 10, tzinfo=UTC), datetime(2026, 12, 31, 23, 55, tzinfo=UTC)),
        ("312355", datetime(2026, 1, 1, 0, 10, tzinfo=UTC), datetime(2025, 12, 31, 23, 55, tzinfo=UTC)),
        ("292355", datetime(2028, 3, 1, 0, 10, tzinfo=UTC), datetime(2028, 2, 29, 23, 55, tzinfo=UTC)),
        ("282355", datetime(2027, 3, 1, 0, 10, tzinfo=UTC), datetime(2027, 2, 28, 23, 55, tzinfo=UTC)),
        ("290000", datetime(2028, 2, 29, 0, 10, tzinfo=UTC), datetime(2028, 2, 29, 0, 0, tzinfo=UTC)),
        ("010005", datetime(2026, 10, 31, 23, 58, tzinfo=UTC), datetime(2026, 11, 1, 0, 5, tzinfo=UTC)),
        ("302355", datetime(2026, 5, 1, 0, 10, tzinfo=UTC), datetime(2026, 4, 30, 23, 55, tzinfo=UTC)),
        ("312355", datetime(2026, 5, 1, 0, 10, tzinfo=UTC), datetime(2026, 3, 31, 23, 55, tzinfo=UTC)),  # no 31 Apr
    ],
)
def test_day_first_timestamp_resolves_across_month_year_and_leap_boundaries(
    report: str, ref: datetime, expected: datetime
) -> None:
    assert observed(report, ref) == expected


def test_feb_29_in_a_common_year_is_reported_not_invented() -> None:
    m = parse_metar(f"KDEN 292355Z {BODY}", datetime(2027, 3, 1, 0, 10, tzinfo=UTC))
    assert m.observed is not None and m.observed.day == 29 and m.observed.month == 1  # no 29 Feb 2027: January it is


def test_hour_24_rolls_to_the_next_day() -> None:
    assert observed("312400", datetime(2026, 11, 1, 0, 10, tzinfo=UTC)) == datetime(2026, 11, 1, 0, 0, tzinfo=UTC)


@pytest.mark.parametrize("stamp", ["002355", "322355", "312360", "312500", "312461"])
def test_impossible_stamps_warn_and_leave_no_time(stamp: str) -> None:
    m = parse_metar(f"KDEN {stamp}Z {BODY}", datetime(2026, 11, 1, tzinfo=UTC))
    assert m.observed is None and m.warnings


@pytest.mark.parametrize(
    "ref",
    [
        datetime(2026, 3, 8, 1, 30, tzinfo=ZoneInfo("America/New_York")),  # spring forward, 02:00 does not exist
        datetime(2026, 3, 8, 3, 30, tzinfo=ZoneInfo("America/New_York")),
        datetime(2026, 11, 1, 1, 30, tzinfo=ZoneInfo("America/New_York"), fold=0),  # fall back, 01:30 happens twice
        datetime(2026, 11, 1, 1, 30, tzinfo=ZoneInfo("America/New_York"), fold=1),
        datetime(2026, 10, 25, 1, 30, tzinfo=ZoneInfo("Europe/London"), fold=0),
        datetime(2026, 10, 25, 1, 30, tzinfo=ZoneInfo("Europe/London"), fold=1),
        datetime(2026, 11, 1, 5, 0, tzinfo=timezone(timedelta(hours=-5))),
    ],
)
def test_reference_in_a_dst_zone_equals_the_same_instant_in_utc(ref: datetime) -> None:
    utc = ref.astimezone(UTC)
    for stamp in ("010100", "312355", "250100", "082359", "010130"):
        assert observed(stamp, ref) == observed(stamp, utc)


def test_naive_reference_is_taken_as_utc() -> None:
    assert observed("312355", datetime(2026, 11, 1, 0, 10)) == datetime(2026, 10, 31, 23, 55, tzinfo=UTC)


@settings(max_examples=300, deadline=None, derandomize=True, database=None, suppress_health_check=list(HealthCheck))
@given(
    ref=st.datetimes(min_value=datetime(2000, 1, 1), max_value=datetime(2040, 1, 1)),
    back=st.timedeltas(min_value=timedelta(0), max_value=timedelta(days=27)),
)
def test_a_report_issued_up_to_27_days_ago_resolves_to_exactly_that_instant(ref: datetime, back: timedelta) -> None:
    ref = ref.replace(tzinfo=UTC, second=0, microsecond=0)
    issued = ref - (back - timedelta(microseconds=back.microseconds) - timedelta(seconds=back.seconds % 60))
    day, hh, mm = issued.day, issued.hour, issued.minute
    got, warning = resolve_report_time(day, hh, mm, ref)
    assert warning is None and got == issued


@pytest.mark.parametrize(
    ("raw", "ref", "valid_from", "valid_to"),
    [
        (
            "TAF KDEN 312320Z 3123/0105 18010KT P6SM SCT050",
            datetime(2026, 12, 31, 23, 40, tzinfo=UTC),
            datetime(2026, 12, 31, 23, 0, tzinfo=UTC),
            datetime(2027, 1, 1, 5, 0, tzinfo=UTC),
        ),
        (
            "TAF KDEN 282320Z 2900/0106 18010KT P6SM SCT050",
            datetime(2028, 2, 28, 23, 40, tzinfo=UTC),
            datetime(2028, 2, 29, 0, 0, tzinfo=UTC),
            datetime(2028, 3, 1, 6, 0, tzinfo=UTC),
        ),
    ],
)
def test_taf_valid_period_across_year_end_and_leap_day(raw, ref, valid_from, valid_to) -> None:
    t = parse_taf(raw, ref)
    assert (t.valid_from, t.valid_to) == (valid_from, valid_to) and t.warnings == ()


@pytest.mark.parametrize(
    "raw",
    [
        "TAF KDEN 012320Z 0200/0500 18010KT P6SM SCT050",  # 72 h long; Annex 3 allows at most 30 h
        "TAF KDEN 012320Z 1500/1600 18010KT P6SM SCT050",  # starts 14 days after it was issued
        "TAF KDEN 282320Z 2900/0106 18010KT P6SM SCT050",  # 29 Feb 2027 does not exist: resolved to 29 March
    ],
)
def test_rt05_an_implausible_valid_period_is_warned(raw: str) -> None:
    ref = datetime(2027, 2, 28, 23, 40, tzinfo=UTC) if "282320Z" in raw else datetime(2026, 11, 1, 23, 40, tzinfo=UTC)
    assert parse_taf(raw, ref).warnings
