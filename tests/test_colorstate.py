"""NATO colour states: the threshold table, computed_color_state edge cases, and agreement with real reports."""

from __future__ import annotations

import math
from datetime import datetime

import pytest
from corpus import awc_rows

from wxbrief.decode.colorstate import (
    THRESHOLDS,
    computed_color_state,
    is_below_green,
    reported_matches_computed,
    visibility_meters,
)
from wxbrief.decode.metar import parse_metar
from wxbrief.decode.model import ColorCode, ColorState, Visibility
from wxbrief.decode.units import Distance, DistanceUnit

BLU, WHT, GRN, YLO1, YLO2, AMB, RED = (
    ColorCode.BLU,
    ColorCode.WHT,
    ColorCode.GRN,
    ColorCode.YLO1,
    ColorCode.YLO2,
    ColorCode.AMB,
    ColorCode.RED,
)


def test_the_table_is_the_standard_one() -> None:
    """UK Met Office colour state register and the Wikipedia table agree on these figures."""
    assert [(row.code, row.ceiling_ft, row.visibility_m) for row in THRESHOLDS] == [
        (BLU, 2500, 8000),
        (WHT, 1500, 5000),
        (GRN, 700, 3700),
        (YLO1, 500, 2500),
        (YLO2, 300, 1600),
        (AMB, 200, 800),
    ]


def test_yellow_one_is_not_the_green_minimums() -> None:
    """The reference notes list YLO1 as 700 ft / 3.7 km, which would be GRN; the register says 500 ft / 2.5 km."""
    by_code = {row.code: row for row in THRESHOLDS}
    assert (by_code[YLO1].ceiling_ft, by_code[YLO1].visibility_m) == (500, 2500)
    assert computed_color_state(699, 3700) is YLO1
    assert computed_color_state(700, 3700) is GRN


@pytest.mark.parametrize(
    ("ceiling", "visibility", "expected"),
    [
        # every minimum, exactly on it and one step below it
        (2500, 8000, BLU),
        (2499, 8000, WHT),
        (2500, 7999, WHT),
        (1500, 5000, WHT),
        (1499, 5000, GRN),
        (1500, 4999, GRN),
        (700, 3700, GRN),
        (699, 3700, YLO1),
        (700, 3699, YLO1),
        (500, 2500, YLO1),
        (499, 2500, YLO2),
        (500, 2499, YLO2),
        (300, 1600, YLO2),
        (299, 1600, AMB),
        (300, 1599, AMB),
        (200, 800, AMB),
        (199, 800, RED),
        (200, 799, RED),
        (0, 0, RED),
        # the worse of the two decides
        (30000, 100, RED),
        (100, 9999, RED),
        (30000, 3000, YLO1),
        (900, 30000, GRN),
        # no ceiling is no limit
        (math.inf, 10000, BLU),
        (math.inf, 4000, GRN),
        (None, 4000, GRN),
        (900, None, GRN),
        (None, 100, RED),
        (None, 10000, BLU),
    ],
)
def test_computed_color_state(ceiling: float | None, visibility: float | None, expected: ColorCode) -> None:
    assert computed_color_state(ceiling, visibility) is expected


def test_nothing_known_computes_nothing() -> None:
    assert computed_color_state(None, None) is None


def test_visibility_in_metres() -> None:
    assert visibility_meters(None) is None
    assert visibility_meters(Visibility(not_reported=True)) is None
    assert visibility_meters(Visibility(cavok=True)) == 10000
    assert visibility_meters(Visibility(Distance(10000, DistanceUnit.M), unlimited=True)) == 10000
    assert visibility_meters(Visibility(Distance(3700, DistanceUnit.M))) == 3700
    assert visibility_meters(Visibility(Distance(5, DistanceUnit.SM))) == pytest.approx(8046.7)
    assert visibility_meters(Visibility()) is None


def test_a_statute_mile_visibility_counts_in_metres() -> None:
    assert computed_color_state(None, visibility_meters(Visibility(Distance(5, DistanceUnit.SM)))) is BLU
    assert computed_color_state(None, visibility_meters(Visibility(Distance(3, DistanceUnit.SM)))) is GRN  # 4828 m


def test_below_green() -> None:
    assert not is_below_green(None)
    assert not is_below_green(ColorState(BLU))
    assert not is_below_green(ColorState(GRN))
    assert not is_below_green(ColorState(None, black=True))
    for code in (ColorCode.YLO, YLO1, YLO2, AMB, RED):
        assert is_below_green(ColorState(code))


def test_reported_against_computed() -> None:
    assert reported_matches_computed(ColorState(GRN), GRN) is True
    assert reported_matches_computed(ColorState(GRN), WHT) is False
    assert reported_matches_computed(ColorState(ColorCode.YLO), YLO1) is True
    assert reported_matches_computed(ColorState(ColorCode.YLO), YLO2) is True
    assert reported_matches_computed(ColorState(ColorCode.YLO), AMB) is False
    assert reported_matches_computed(ColorState(YLO1), YLO2) is False
    assert reported_matches_computed(ColorState(BLU, plus=True), BLU) is True
    assert reported_matches_computed(ColorState(BLU, black=True), BLU) is True
    assert reported_matches_computed(ColorState(None, not_reported=True), BLU) is None
    assert reported_matches_computed(None, BLU) is None
    assert reported_matches_computed(ColorState(BLU), None) is None


# --- the metar fields -----------------------------------------------------------------------------------------


def test_a_report_with_a_colour_state_exposes_reported_and_computed() -> None:
    decoded = parse_metar("METAR ETNL 310820Z 35004KT 9999 OVC012 10/07 Q1032 BLU", datetime(2026, 10, 31, 9))
    assert decoded.color_state is not None
    assert decoded.color_state.current == ColorState(BLU)
    assert decoded.computed_color_state is GRN  # a 1,200 ft ceiling is Green, whatever was reported


def test_a_report_without_a_colour_state_computes_none() -> None:
    decoded = parse_metar("METAR EGLL 310820Z 35004KT 9999 OVC012 10/07 Q1032", datetime(2026, 10, 31, 9))
    assert decoded.color_state is None
    assert decoded.computed_color_state is None


def test_cavok_and_clear_skies_compute_blue() -> None:
    decoded = parse_metar("METAR ETNN 310820Z VRB02KT CAVOK 06/04 Q1032 BLU", datetime(2026, 10, 31, 9))
    assert decoded.computed_color_state is BLU
    decoded = parse_metar("METAR ETNN 310820Z VRB02KT 9999 NSC 06/04 Q1032 BLU+", datetime(2026, 10, 31, 9))
    assert decoded.computed_color_state is BLU


def test_scattered_cloud_is_not_a_ceiling() -> None:
    """Only broken, overcast or obscured skies count (the UK register counts scattered too; see decoding.md)."""
    decoded = parse_metar("METAR ETHL 310828Z 05007KT 9999 SCT008 05/05 Q1029 BLU+", datetime(2026, 10, 31, 9))
    assert decoded.computed_color_state is BLU


def test_vertical_visibility_is_a_ceiling() -> None:
    decoded = parse_metar("METAR EHDL 310825Z AUTO 09005KT 0550 FG VV000 07/07 Q1033 RED", datetime(2026, 10, 31, 9))
    assert decoded.computed_color_state is RED


def test_an_unknown_sky_leaves_visibility_to_decide() -> None:
    decoded = parse_metar("METAR ETHB 310820Z AUTO 30002KT 3000 // ////// 08/07 Q1033 ///", datetime(2026, 10, 31, 9))
    assert decoded.color_state is not None
    assert decoded.computed_color_state is YLO1  # 3,000 m: at least 2,500, below 3,700


# --- real reports ---------------------------------------------------------------------------------------------


def test_reported_colours_agree_with_the_computed_ones_on_every_saved_report() -> None:
    """47 saved reports from German, Dutch and UK military fields carry a colour: all of them recompute to it.

    This is what rules out the notes' YLO1 figures (700 ft / 3.7 km): the UK ``YLO1`` reports below would compute
    to Green with them.
    """
    checked = 0
    disagreements: list[str] = []
    for row in awc_rows():
        decoded = parse_metar(row["rawOb"], datetime.fromisoformat(row["reportTime"].replace("Z", "+00:00")))
        if decoded.color_state is None or decoded.color_state.current is None or decoded.color_state.current.code is None:
            continue
        checked += 1
        if reported_matches_computed(decoded.color_state.current, decoded.computed_color_state) is not True:
            disagreements.append(f"{decoded.color_state.current.code.value} vs {decoded.computed_color_state}: {row['rawOb']}")
    assert checked >= 40
    assert not disagreements, "\n".join(disagreements)


def test_the_saved_reports_include_both_yellows() -> None:
    codes = set()
    for row in awc_rows():
        decoded = parse_metar(row["rawOb"], datetime.fromisoformat(row["reportTime"].replace("Z", "+00:00")))
        if decoded.color_state is not None and decoded.color_state.current is not None:
            codes.add(decoded.color_state.current.code)
    assert {YLO1, YLO2, ColorCode.YLO, AMB, RED, GRN, BLU} <= codes
