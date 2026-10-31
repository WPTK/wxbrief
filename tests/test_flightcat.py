"""Flight category: the COBOL thresholds, edge cases, and parity with the AWC API's own ``fltCat``."""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import datetime
from typing import Any

import pytest
from corpus import awc_rows

from wxbrief.decode.flightcat import classify, flight_category, lowest_ceiling, visibility_sm
from wxbrief.decode.metar import parse_metar
from wxbrief.decode.model import CloudLayer, FlightCategory, Metar, SkyCondition, Visibility, VisPrefix
from wxbrief.decode.units import Distance, DistanceUnit

VFR, MVFR, IFR, LIFR = FlightCategory.VFR, FlightCategory.MVFR, FlightCategory.IFR, FlightCategory.LIFR


@pytest.mark.parametrize(
    ("ceiling", "vis", "expected"),
    [
        # ceiling thresholds with good visibility: LIFR < 500, IFR < 1000, MVFR <= 3000
        (499, 10, LIFR),
        (500, 10, IFR),
        (999, 10, IFR),
        (1000, 10, MVFR),
        (3000, 10, MVFR),
        (3001, 10, VFR),
        (25000, 10, VFR),
        (math.inf, 10, VFR),
        # visibility thresholds with no ceiling: LIFR < 1, IFR < 3, MVFR <= 5
        (math.inf, 0.25, LIFR),
        (math.inf, 0.99, LIFR),
        (math.inf, 1, IFR),
        (math.inf, 2.99, IFR),
        (math.inf, 3, MVFR),
        (math.inf, 5, MVFR),
        (math.inf, 5.01, VFR),
        (math.inf, 6, VFR),
        # the worse of the two wins
        (400, 6, LIFR),
        (4000, 0.5, LIFR),
        (900, 2, IFR),
        (2500, 1.5, IFR),
        (2500, 4, MVFR),
        (400, 0.5, LIFR),
    ],
)
def test_thresholds(ceiling: float, vis: float, expected: FlightCategory) -> None:
    assert classify(ceiling, vis) is expected


def test_a_missing_component_is_never_assumed_clear() -> None:
    # the known component alone forces IFR or LIFR
    assert classify(None, 2) is IFR
    assert classify(None, 0.25) is LIFR
    assert classify(800, None) is IFR
    assert classify(300, None) is LIFR
    # otherwise nothing is known well enough for a category
    assert classify(None, 10) is None
    assert classify(None, 4) is None
    assert classify(5000, None) is None
    assert classify(2000, None) is None
    assert classify(None, None) is None
    # a known absence of limit is not unknown
    assert classify(math.inf, 10) is VFR
    assert classify(math.inf, math.inf) is VFR


def test_ceiling_is_the_lowest_broken_overcast_or_vertical_visibility_layer() -> None:
    sky = [
        CloudLayer(SkyCondition.FEW, Distance(500, DistanceUnit.FT)),
        CloudLayer(SkyCondition.SCT, Distance(800, DistanceUnit.FT)),
        CloudLayer(SkyCondition.OVC, Distance(4000, DistanceUnit.FT)),
        CloudLayer(SkyCondition.BKN, Distance(2000, DistanceUnit.FT)),
    ]
    layer = lowest_ceiling(sky)
    assert layer is not None
    assert layer.cover is SkyCondition.BKN
    assert flight_category(Visibility(Distance(10, DistanceUnit.SM)), sky) is MVFR


def test_vertical_visibility_is_a_ceiling() -> None:
    sky = [CloudLayer(SkyCondition.VV, Distance(200, DistanceUnit.FT))]
    assert flight_category(Visibility(Distance(10, DistanceUnit.SM)), sky) is LIFR


def test_few_and_scattered_are_not_a_ceiling() -> None:
    sky = [CloudLayer(SkyCondition.SCT, Distance(300, DistanceUnit.FT))]
    assert lowest_ceiling(sky) is None
    assert flight_category(Visibility(Distance(10, DistanceUnit.SM)), sky) is VFR


def test_unknown_ceiling_height_is_ignored() -> None:
    sky = [CloudLayer(SkyCondition.VV, None)]
    assert lowest_ceiling(sky) is None
    assert flight_category(Visibility(Distance(150, DistanceUnit.M)), sky) is LIFR
    assert flight_category(Visibility(Distance(10, DistanceUnit.SM)), sky) is None


def test_unknown_sky_gives_no_category_unless_visibility_forces_one() -> None:
    ten = Visibility(Distance(10, DistanceUnit.SM))
    assert flight_category(ten, []) is None
    assert flight_category(ten, [CloudLayer(SkyCondition.UNKNOWN)]) is None
    assert flight_category(ten, [CloudLayer(SkyCondition.BKN, None)]) is None
    assert flight_category(ten, [CloudLayer(SkyCondition.UNKNOWN, Distance(800, DistanceUnit.FT))]) is None
    assert flight_category(Visibility(Distance(0.25, DistanceUnit.SM)), []) is LIFR


def test_unknown_visibility_gives_no_category_even_with_a_clear_sky() -> None:
    assert flight_category(None, [CloudLayer(SkyCondition.CLR)]) is None
    assert flight_category(Visibility(not_reported=True), [CloudLayer(SkyCondition.NCD)]) is None
    assert flight_category(None, [CloudLayer(SkyCondition.OVC, Distance(300, DistanceUnit.FT))]) is LIFR
    assert flight_category(None, []) is None


@pytest.mark.parametrize(
    ("meters", "expected"),
    [
        (9999, VFR),
        (8000, MVFR),
        (8100, VFR),
        (5000, MVFR),
        (4800, IFR),
        (4900, MVFR),
        (1700, IFR),
        (1609, LIFR),
        (1610, IFR),
        (800, LIFR),
    ],
)
def test_metric_visibility_converts_at_1609_34(meters: int, expected: FlightCategory) -> None:
    sky = [CloudLayer(SkyCondition.NSC)]
    vis = Visibility(Distance(meters, DistanceUnit.M), unlimited=meters == 9999)
    assert flight_category(vis, sky) is expected


def test_9999_and_cavok_count_as_ten_miles() -> None:
    assert visibility_sm(Visibility(Distance(10000, DistanceUnit.M), unlimited=True)) == 10
    assert visibility_sm(Visibility(cavok=True)) == 10
    assert flight_category(Visibility(cavok=True), []) is VFR


def test_prefixes_keep_the_stated_value() -> None:
    assert visibility_sm(Visibility(Distance(0.25, DistanceUnit.SM), VisPrefix.LESS_THAN)) == 0.25
    assert visibility_sm(Visibility(Distance(6, DistanceUnit.SM), VisPrefix.GREATER_THAN)) == 6


def test_no_visibility() -> None:
    assert visibility_sm(None) is None
    assert visibility_sm(Visibility(not_reported=True)) is None
    assert visibility_sm(Visibility()) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("METAR KDEN 131453Z 06007KT 3/4SM R35L/P6000FT BR OVC003 09/08 A3001 RMK AO2 SFC", LIFR),
        ("METAR KDEN 131453Z 06007KT 10SM FEW180 BKN200 09/06 A3004", VFR),
        ("METAR KXYZ 131453Z 06007KT 4SM BR BKN020 09/08 A3001", MVFR),
        ("METAR KXYZ 131453Z 06007KT 2SM BR BKN020 09/08 A3001", IFR),
        ("METAR KXYZ 131453Z 06007KT 1/2SM FG VV001 09/08 A3001", LIFR),
        ("METAR EGLL 131453Z 24010KT CAVOK 12/08 Q1013", VFR),
        ("METAR EGLL 131453Z 24010KT 9999 BKN010 12/08 Q1013", MVFR),
        ("METAR EGLL 131453Z 24010KT 0800 FG VV001 12/08 Q1013", LIFR),
    ],
)
def test_decoded_reports(raw: str, expected: FlightCategory) -> None:
    assert parse_metar(raw, datetime(2026, 10, 13, 15, 0)).flight_category is expected


def test_a_sky_of_placeholders_is_not_a_clear_sky() -> None:
    """``//////`` (cloud not observed) says nothing about a ceiling, unlike FEW or CLR."""
    unknown = CloudLayer(SkyCondition.UNKNOWN)
    assert flight_category(Visibility(), [unknown]) is None
    assert flight_category(Visibility(Distance(1000, DistanceUnit.M)), [unknown]) is LIFR  # from visibility alone
    assert flight_category(Visibility(), [CloudLayer(SkyCondition.CLR)]) is None
    assert flight_category(Visibility(), [unknown, CloudLayer(SkyCondition.FEW, Distance(1000, DistanceUnit.FT))]) is None


# --- parity with the AWC API --------------------------------------------------------------------------------------

# Reports where our category legitimately differs from AWC's. Each rule says which saved reports it covers and why
# the difference is not a decoder bug; a rule must cover at least one saved report (the stale-rule test below).
# A rule gets the AWC row and our decode.


def _awc_has_no_category(row: dict[str, Any]) -> bool:
    return row.get("fltCat") is None


def _sky_not_observed(row: dict[str, Any], decoded: Metar) -> bool:
    """German military AUTO reports with ``// ////// ``: no weather and no sky, only a visibility."""
    return (
        _awc_has_no_category(row)
        and decoded.flight_category is not None
        and bool(decoded.sky)
        and all(layer.cover is SkyCondition.UNKNOWN for layer in decoded.sky)
        and decoded.visibility is not None
        and decoded.visibility.distance is not None
    )


def _undirectional_visibility_suffix(row: dict[str, Any], decoded: Metar) -> bool:
    """Greenland's ``9999NDV``: AWC does not read the NDV suffix and withholds a category."""
    return _awc_has_no_category(row) and decoded.visibility is not None and decoded.visibility.ndv


PARITY_RULES: dict[str, tuple[Callable[[dict[str, Any], Metar], bool], str]] = {
    "sky-not-observed": (
        _sky_not_observed,
        "AWC gives no category when the sky is `//////`; we give IFR or LIFR when the visibility alone forces it "
        "(an unknown ceiling cannot make it better) and none otherwise, so we differ only for those reports.",
    ),
    "ndv-suffix": (
        _undirectional_visibility_suffix,
        "AWC returns no category for `9999NDV` (every saved report with the NDV suffix); `9999` is 10 km, so with "
        "the layers decoded the category is VFR.",
    ),
}


def _covering_rule(row: dict[str, Any], decoded: Metar) -> str | None:
    for name, (applies, _reason) in PARITY_RULES.items():
        if applies(row, decoded):
            return name
    return None


def _decode_row(row: dict[str, Any]) -> Metar:
    return parse_metar(row["rawOb"], datetime.fromisoformat(row["reportTime"].replace("Z", "+00:00")))


def test_every_exception_rule_covers_a_saved_report() -> None:
    used = {_covering_rule(row, _decode_row(row)) for row in awc_rows()}
    assert set(PARITY_RULES) <= used


def test_category_matches_awc_for_every_saved_report() -> None:
    rows: list[dict[str, Any]] = awc_rows()
    assert len(rows) > 900
    checked = 0
    mismatches: list[str] = []
    for row in rows:
        decoded = _decode_row(row)
        ours = decoded.flight_category.name if decoded.flight_category else None
        checked += 1
        if ours != row.get("fltCat") and _covering_rule(row, decoded) is None:
            mismatches.append(f"{row['icaoId']}: ours={ours} awc={row.get('fltCat')} :: {row['rawOb']}")
    assert checked > 900
    assert not mismatches, "\n".join(mismatches)


def test_rules_only_excuse_a_difference() -> None:
    """A rule must not hide a report where AWC and we agree: excusing agreement would make a rule stale."""
    for row in awc_rows():
        decoded = _decode_row(row)
        ours = decoded.flight_category.name if decoded.flight_category else None
        if _covering_rule(row, decoded) is not None:
            assert ours != row.get("fltCat"), row["rawOb"]


@pytest.mark.parametrize(
    "raw",
    [
        "KXXX 311200Z 24005KT 10SM BKN/// 10/09 A2992",
        "EXXX 311200Z AUTO 24005KT 9999 ////// 10/09 Q1020",
        "EXXX 311200Z AUTO 24005KT 9999 ///008 10/09 Q1020",
        "EXXX 311200Z AUTO 24005KT //// NCD 10/09 Q1020",
    ],
)
def test_reports_with_unknown_data_get_no_category_and_no_colour_state(raw: str) -> None:
    metar = parse_metar(raw + " BLU", datetime(2026, 10, 31, 12, 0))
    assert metar.flight_category is None
    assert metar.computed_color_state is None


def test_a_known_low_component_still_forces_its_category_when_the_other_is_unknown() -> None:
    metar = parse_metar("KXXX 311200Z 24005KT 1/4SM BKN/// 10/09 A2992", datetime(2026, 10, 31, 12, 0))
    assert metar.flight_category is LIFR
