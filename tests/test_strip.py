"""The cells of a forecast strip, computed without Textual."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta

from wxbrief.data.demo import DEMO_NOW, demo_text
from wxbrief.decode.model import FlightCategory, Taf
from wxbrief.decode.split import parse_any
from wxbrief.decode.taf import parse_taf
from wxbrief.ui.strip import StripCell, cell_at, group_cells, hour_step, mini_cells, strip_for

REF = datetime(2026, 10, 31, 11, 0, tzinfo=UTC)


def hourly(raw: str):
    taf = parse_taf(raw, REF)
    return strip_for(taf)[1]


def letters(cells) -> str:
    """One letter per cell: the prevailing category, ``~`` after it when becoming, ``*`` when an overlay is active."""
    return "".join(
        (c.category.value[0] if c.category else "?") + ("~" if c.becoming else "") + ("*" if c.overlay else "")
        for c in cells
    )


def demo_taf(icao: str) -> Taf:
    taf = next(item for item in parse_any(demo_text(icao), DEMO_NOW) if isinstance(item, Taf))
    return taf


# TAF TEST 3112/3118: VFR; BECMG 14-16 to IFR (hours 14 and 15 are hatched); TEMPO 16-18 to LIFR over the IFR.
SMALL = "TAF TEST 311100Z 3112/3118 09010KT 9999 SCT030 BECMG 3114/3116 3000 BR BKN008 TEMPO 3116/3118 0800 FG"


def test_small_taf_hour_by_hour() -> None:
    hours = hourly(SMALL)
    cells = group_cells(hours)
    assert len(cells) == 6
    assert letters(cells) == "VVV~V~I*I*"
    assert [c.category for c in cells[:2]] == [FlightCategory.VFR] * 2
    # the hatched hours carry the worst case of the change, which lands at any moment of its window
    assert cells[2].worst_category == FlightCategory.IFR
    assert cells[3].worst_category == FlightCategory.IFR
    # the temporary group is the worst case on its own row
    assert cells[4].overlay_category == FlightCategory.LIFR
    assert cells[4].worst_category == FlightCategory.LIFR
    assert cells[0].overlay_category is None


def test_real_kden_forecast() -> None:
    # Read against the raw text: LIFR fog to 20Z (the TEMPO at 17-19Z is better than the prevailing OVC001, so it is
    # an overlay on hours 17 and 18 only), then VFR for the rest of the forecast.
    cells = group_cells(strip_for(demo_taf("KDEN"))[1])
    assert len(cells) == 30
    assert letters(cells) == "LLLLLL*L*L" + "V" * 22
    assert cells[0].start == datetime(2026, 10, 31, 12, tzinfo=UTC)


def test_egll_forecast_becoming_and_overlays() -> None:
    cells = group_cells(strip_for(demo_taf("EGLL"))[1])
    assert letters(cells) == "V" * 9 + "V~" * 3 + "M*" * 3 + "M~" * 3 + "L" * 3 + "L~" * 3 + "V" * 6
    assert cells[12].overlay_category == FlightCategory.LIFR


def test_three_hour_cells_take_the_worst_case() -> None:
    hours = hourly(SMALL)
    cells = group_cells(hours, 3)
    assert [c.hours for c in cells] == [(0, 1, 2), (3, 4, 5)]
    assert cells[0].start == hours[0].start and cells[0].end == hours[2].end
    assert cells[0].category == FlightCategory.VFR and cells[0].becoming
    assert cells[1].category == FlightCategory.IFR and cells[1].overlay
    assert cells[1].worst_category == FlightCategory.LIFR
    assert len(group_cells(hours, 4)) == 2 and group_cells(hours, 4)[1].hours == (4, 5)  # the last cell may be short


def test_cell_lookup_by_time() -> None:
    cells = group_cells(hourly(SMALL))
    assert cell_at(cells, datetime(2026, 10, 31, 12, tzinfo=UTC)) == 0
    assert cell_at(cells, datetime(2026, 10, 31, 14, 59, tzinfo=UTC)) == 2
    assert cell_at(cells, datetime(2026, 10, 31, 18, tzinfo=UTC)) is None
    assert cell_at(cells, datetime(2026, 10, 31, 11, 59, tzinfo=UTC)) is None


def test_mini_strip_is_the_next_twelve_hours() -> None:
    hours = strip_for(demo_taf("KDEN"))[1]
    now = datetime(2026, 10, 31, 17, 30, tzinfo=UTC)
    cells = mini_cells(hours, now)
    assert len(cells) == 12
    assert cells[0].start == datetime(2026, 10, 31, 17, tzinfo=UTC)
    assert letters(cells) == "L*L*L" + "V" * 9
    assert mini_cells(hours, datetime(2026, 10, 31, 6, tzinfo=UTC))[0].start == hours[0].start  # before the TAF
    assert len(mini_cells(hours, datetime(2026, 11, 1, 12, tzinfo=UTC))) == 6  # runs out at 18Z
    assert mini_cells(hours, datetime(2026, 11, 1, 18, tzinfo=UTC)) == ()
    assert mini_cells((), now) == ()


def test_hour_step() -> None:
    assert hour_step(30, 100, narrow=False) == 1
    assert hour_step(30, 59, narrow=False) == 3  # thirty two-column cells need sixty columns
    assert hour_step(30, 200, narrow=True) == 3
    assert hour_step(30, 0, narrow=False) == 1  # width not known yet


def test_no_valid_period_gives_no_cells() -> None:
    taf = parse_taf("TAF TEST 311100Z CNL", REF)
    assert group_cells(strip_for(taf)[1]) == ()


def test_cells_are_contiguous() -> None:
    for icao in ("KDEN", "EGLL", "YSSY", "VIDP"):
        cells: tuple[StripCell, ...] = group_cells(strip_for(demo_taf(icao))[1])
        assert all(b.start == a.end for a, b in itertools.pairwise(cells))
        assert all(c.end - c.start == timedelta(hours=1) for c in cells)
