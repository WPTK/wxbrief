"""Red-team example-based traps for the METAR/SPECI/TAF decoders.

Passing tests pin behaviour that was checked against FMH-1 / ICAO Annex 3 and could plausibly regress. A test marked
``xfail(strict=True, reason="RT-nn")`` reproduces a finding in audit/redteam-findings.md; when the product is fixed
the strict xfail turns into a failure that says the marker should be removed.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from wxbrief.decode.flightcat import visibility_sm
from wxbrief.decode.metar import parse_metar
from wxbrief.decode.model import (
    DailyTemperatureExtremes,
    MaxTemperature6Hour,
    MinTemperature6Hour,
    PeakWind,
    PreciseTemperature,
    PressureTendency,
    SeaLevelPressure,
    SensorStatus,
    WindShift,
)
from wxbrief.decode.split import parse_any
from wxbrief.decode.taf import parse_taf
from wxbrief.decode.timeline import categorize_periods

REF = datetime(2026, 10, 31, 23, 59, tzinfo=UTC)


def decode(body: str, station: str = "KDEN"):
    return parse_metar(f"{station} 311853Z {body}", REF)


def remark(m, kind):
    found = [r for r in m.remarks if isinstance(r, kind)]
    assert found, [type(r).__name__ for r in m.remarks]
    return found[0]


# --- tokens, not station prefixes, decide units --------------------------------------------------------------------


@pytest.mark.parametrize("station", ["KDEN", "PANC", "CYYZ", "EGLL", "RJTT", "ETHB", "UUEE"])
def test_statute_miles_and_inhg_win_over_any_station_prefix(station: str) -> None:
    m = decode("18012KT 6SM FEW050 12/10 A2992", station)
    assert (m.visibility.distance.unit.name, m.altimeters[0].unit.name) == ("SM", "INHG")
    assert m.altimeters[0].value == 29.92


@pytest.mark.parametrize("station", ["KDEN", "PANC", "CYYZ", "EGLL", "RJTT"])
def test_metres_and_qnh_win_over_any_station_prefix(station: str) -> None:
    m = decode("18012KT 4000 FEW050 12/10 Q1013", station)
    assert (m.visibility.distance.unit.name, m.altimeters[0].unit.name) == ("M", "HPA")
    assert m.altimeters[0].value == 1013


@pytest.mark.parametrize("station", ["KDEN", "CYUL", "EGLL"])
def test_cavok_is_ten_km_everywhere(station: str) -> None:
    m = decode("24010KT CAVOK 12/10 Q1013", station)
    assert visibility_sm(m.visibility) == 10.0 and m.flight_category.name == "VFR"


@pytest.mark.parametrize("code", ["BLU", "WHT", "GRN", "YLO", "YLO1", "YLO2", "AMB", "RED"])
@pytest.mark.parametrize("station", ["ETHB", "KDEN", "CYQX", "EGVA"])
def test_nato_colour_state_is_read_on_any_station_and_marks_military(code: str, station: str) -> None:
    m = decode(f"24010KT 9999 FEW050 12/10 Q1013 {code}", station)
    assert m.color_state is not None and m.color_state.current.code.name == code
    assert m.military is True and m.warnings == ()


def test_black_alone_is_a_closed_state_not_a_colour() -> None:
    m = decode("24010KT 9999 FEW050 12/10 Q1013 BLACK", "ETHB")
    assert m.color_state.current.black is True and m.color_state.current.code is None


def test_black_prefix_keeps_the_colour() -> None:
    m = decode("24010KT 9999 FEW050 12/10 Q1013 BLACKBLU", "ETHB")
    assert m.color_state.current.black is True and m.color_state.current.code.name == "BLU"


def test_a_station_named_like_a_colour_is_not_a_colour_state() -> None:
    assert decode("24010KT 10SM FEW050 12/10 A2992", "KRED").color_state is None


# --- remarks -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("group", "temp", "dew"),
    [
        ("T01231045", 12.3, -4.5),
        ("T10151005", -1.5, -0.5),
        ("T00671011", 6.7, -1.1),
        ("T11001100", -10.0, -10.0),
        ("T00000000", 0.0, 0.0),
    ],
)
def test_t_group_carries_tenths_and_both_signs(group: str, temp: float, dew: float) -> None:
    m = decode(f"18012KT 10SM CLR 12/10 A2992 RMK AO2 {group}")
    precise = remark(m, PreciseTemperature)
    assert (precise.temperature.value, precise.dewpoint.value) == (temp, dew)


def test_t_group_does_not_overwrite_the_rounded_body_values() -> None:
    m = decode("18012KT 10SM CLR 12/M05 A2992 RMK AO2 T01231045")
    assert (m.temperature.value, m.dewpoint.value) == (12, -5)  # body stays as reported; the T-group is its own remark


@pytest.mark.parametrize(
    ("group", "kind", "value"),
    [
        ("10150", MaxTemperature6Hour, 15.0),
        ("11015", MaxTemperature6Hour, -1.5),
        ("10000", MaxTemperature6Hour, 0.0),
        ("20100", MinTemperature6Hour, 10.0),
        ("21020", MinTemperature6Hour, -2.0),
    ],
)
def test_six_hour_extremes_sign_digit(group: str, kind: type, value: float) -> None:
    assert remark(decode(f"18012KT 10SM CLR 12/10 A2992 RMK AO2 {group}"), kind).temperature.value == value


def test_twenty_four_hour_extremes() -> None:
    r = remark(decode("18012KT 10SM CLR 12/10 A2992 RMK AO2 400561039"), DailyTemperatureExtremes)
    assert (r.maximum.value, r.minimum.value) == (5.6, -3.9)


@pytest.mark.parametrize(
    ("group", "direction", "hpa"),
    [
        ("50012", "HIGHER", 1.2),
        ("52012", "HIGHER", 1.2),
        ("54000", "SAME", 0.0),
        ("55012", "LOWER", 1.2),
        ("58012", "LOWER", 1.2),
        ("53999", "HIGHER", 99.9),
    ],
)
def test_pressure_tendency(group: str, direction: str, hpa: float) -> None:
    r = remark(decode(f"18012KT 10SM CLR 12/10 A2992 RMK AO2 {group}"), PressureTendency)
    assert (r.direction.name, r.change_hpa) == (direction, hpa)


@pytest.mark.parametrize(
    ("slp", "hpa"),
    [
        ("SLP132", 1013.2),
        ("SLP982", 998.2),
        ("SLP000", 1000.0),
        ("SLP499", 1049.9),
        ("SLP500", 950.0),
        ("SLP999", 999.9),
    ],
)
def test_slp_reconstruction(slp: str, hpa: float) -> None:
    assert remark(decode(f"18012KT 10SM CLR 12/10 A2992 RMK AO2 {slp}"), SeaLevelPressure).pressure.value == hpa


def test_slp_no_report_has_no_pressure() -> None:
    assert remark(decode("18012KT 10SM CLR 12/10 A2992 RMK AO2 SLPNO"), SeaLevelPressure).pressure is None


def test_peak_wind_and_wind_shift_times() -> None:
    m = decode("18012KT 10SM CLR 12/10 A2992 RMK AO2 PK WND 28045/1715 WSHFT 1730 FROPA")
    peak, shift = remark(m, PeakWind), remark(m, WindShift)
    assert (peak.direction, peak.speed.value, peak.time.hour, peak.time.minute) == (280, 45, 17, 15)
    assert (shift.time.hour, shift.time.minute, shift.frontal_passage) == (17, 30, True)


def test_peak_wind_minute_only_time_has_no_hour() -> None:
    peak = remark(decode("18012KT 10SM CLR 12/10 A2992 RMK AO2 PK WND 28045/15"), PeakWind)
    assert (peak.time.hour, peak.time.minute) == (None, 15)


@pytest.mark.parametrize("sensor", ["FZRANO", "TSNO", "RVRNO", "PNO", "PWINO", "VISNO", "CHINO"])
def test_sensor_outage_remarks(sensor: str) -> None:
    m = decode(f"18012KT 10SM CLR 12/10 A2992 RMK AO2 {sensor}")
    assert remark(m, SensorStatus).sensor.value == sensor and m.warnings == ()


def test_recent_weather_groups_in_body() -> None:
    m = decode("18012KT 10SM CLR 12/10 A2992 RERA RETS REFZRA")
    assert len(m.recent_weather) == 3 and m.warnings == ()


# --- flight category: only BKN/OVC/VV make a ceiling, visibility fractions ----------------------------------------


@pytest.mark.parametrize(
    ("body", "category"),
    [
        ("10SM FEW002 SCT004 12/10 A2992", "VFR"),  # FEW/SCT are never a ceiling
        ("10SM SCT002 12/10 A2992", "VFR"),
        ("10SM BKN004 12/10 A2992", "LIFR"),
        ("10SM BKN005 12/10 A2992", "IFR"),
        ("10SM BKN010 12/10 A2992", "MVFR"),
        ("10SM OVC030 12/10 A2992", "MVFR"),
        ("10SM OVC031 12/10 A2992", "VFR"),
        ("10SM VV002 12/10 A2992", "LIFR"),
        ("10SM OVC000 12/10 A2992", "LIFR"),
        ("M1/4SM FG VV001 12/10 A2992", "LIFR"),
        ("1/2SM FG CLR 12/10 A2992", "LIFR"),
        ("1SM BR CLR 12/10 A2992", "IFR"),
        ("1 1/2SM BR CLR 12/10 A2992", "IFR"),
        ("2 3/4SM BR CLR 12/10 A2992", "IFR"),
        ("3SM BR CLR 12/10 A2992", "MVFR"),
        ("5SM HZ CLR 12/10 A2992", "MVFR"),
        ("6SM HZ CLR 12/10 A2992", "VFR"),
        ("P6SM CLR 12/10 A2992", "VFR"),
        ("10SM BKN004 BKN002 OVC010 12/10 A2992", "LIFR"),  # lowest layer wins whatever the order
        ("10SM OVC010 BKN002 12/10 A2992", "LIFR"),
    ],
)
def test_flight_category_boundaries(body: str, category: str) -> None:
    assert decode(f"18012KT {body}").flight_category.name == category


@pytest.mark.parametrize(
    ("metres", "category"),
    [
        ("1599", "LIFR"),
        ("1609", "LIFR"),
        ("1610", "IFR"),
        ("4800", "IFR"),
        ("4829", "MVFR"),
        ("8046", "MVFR"),
        ("8047", "VFR"),
        ("9999", "VFR"),
    ],
)
def test_flight_category_from_metres_uses_statute_mile_thresholds(metres: str, category: str) -> None:
    assert decode(f"18012KT {metres} CLR 12/10 Q1013").flight_category.name == category


def test_unknown_ceiling_is_not_a_green_badge() -> None:
    assert decode("18012KT 10SM FEW010 SCT020 BKN/// 12/10 A2992").flight_category is None


# --- TAF: BASE / FM / BECMG / TEMPO / PROB inheritance -------------------------------------------------------------

TAF_REF = datetime(2026, 11, 1, 0, 10, tzinfo=UTC)


def category_names(raw: str) -> list[str | None]:
    t = parse_taf(raw, TAF_REF)
    assert t.warnings == (), raw
    return [c.name if c else None for c in categorize_periods(t.periods, t.valid_from)]


def test_tempo_inherits_what_it_does_not_state() -> None:
    assert category_names("TAF KDEN 312320Z 0100/0112 18010KT P6SM OVC010 TEMPO 0102/0105 2SM BR") == ["MVFR", "IFR"]


def test_tempo_sky_replaces_the_whole_layer_list() -> None:
    assert category_names("TAF KDEN 312320Z 0100/0112 18010KT P6SM OVC010 TEMPO 0102/0105 SCT008") == ["MVFR", "VFR"]


def test_becmg_merges_over_the_prevailing_state() -> None:
    assert category_names("TAF KDEN 312320Z 0100/0112 18010KT P6SM SCT050 BECMG 0105/0107 BKN008") == ["VFR", "IFR"]


def test_fm_does_not_inherit() -> None:
    assert category_names("TAF KDEN 312320Z 0100/0112 18010KT P6SM OVC010 FM010500 18010KT 5SM") == ["MVFR", None]


def test_prob_without_tempo_is_an_overlay() -> None:
    assert category_names("TAF KDEN 312320Z 0100/0112 18010KT 9999 BKN040 PROB30 0102/0105 TSRA") == ["VFR", "VFR"]


def test_cavok_base_with_tempo_visibility_spells_out_cavok() -> None:
    assert category_names("TAF KDEN 312320Z 0100/0112 18010KT CAVOK TEMPO 0102/0105 3000") == ["VFR", "IFR"]


# --- findings (strict xfail) ---------------------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="RT-01")
@pytest.mark.parametrize("wind", ["18012G10KT", "18012G12KT", "18012G00KT"])
def test_rt01_a_gust_not_above_the_mean_wind_is_flagged(wind: str) -> None:
    m = decode(f"{wind} 10SM CLR 12/10 A2992")
    assert m.warnings or m.wind.gust is None


@pytest.mark.xfail(strict=True, reason="RT-02")
@pytest.mark.parametrize("group", ["A9999", "A0000", "A0100", "Q0000", "Q0001", "Q9999"])
def test_rt02_an_impossible_pressure_is_not_accepted_silently(group: str) -> None:
    m = decode(f"18012KT 10SM CLR 12/10 {group}")
    assert m.warnings or not m.altimeters


@pytest.mark.xfail(strict=True, reason="RT-04")
def test_rt04_fm_groups_out_of_time_order_are_warned() -> None:
    t = parse_taf("TAF KDEN 312320Z 0100/0124 18010KT P6SM SCT050 FM011200 18010KT FM010600 18005KT", TAF_REF)
    assert t.warnings


@pytest.mark.xfail(strict=True, reason="RT-04")
def test_rt04_becmg_window_ending_after_the_valid_period_is_warned() -> None:
    t = parse_taf("TAF KDEN 312320Z 0100/0103 18010KT P6SM SCT050 BECMG 0102/0104 BKN010", TAF_REF)
    assert t.warnings


@pytest.mark.xfail(strict=True, reason="RT-06")
def test_rt06_a_pasted_markdown_fence_is_not_a_report() -> None:
    reports = parse_any("```\nKDEN 311853Z 18012KT 10SM CLR 12/10 A2992\n```", REF)
    assert len(reports) == 1


@pytest.mark.xfail(strict=True, reason="RT-07")
def test_rt07_two_reports_on_one_line_without_keywords_are_two_reports() -> None:
    raw = "KDEN 311853Z 18012KT 10SM CLR 12/10 A2992 KJFK 311851Z 18012KT 10SM CLR 12/10 A2992"
    assert [r.station for r in parse_any(raw, REF)] == ["KDEN", "KJFK"]


@pytest.mark.xfail(strict=True, reason="RT-08")
@pytest.mark.parametrize("prob", ["PROB10", "PROB50", "PROB90"])
def test_rt08_only_prob30_and_prob40_exist(prob: str) -> None:
    """ICAO Annex 3 App. 5 and the FAA TAF code allow PROB30 and PROB40 only."""
    t = parse_taf(f"TAF KDEN 312320Z 0100/0124 18010KT P6SM SCT050 {prob} 0112/0118 TSRA", TAF_REF)
    assert t.warnings
