"""The METAR state machine: ordering, tolerance, tagging and the never-raise contract."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from corpus import read_raw, reference_for, report_files

from wxbrief.decode import metar as metar_module
from wxbrief.decode.metar import parse_metar
from wxbrief.decode.model import (
    Flavor,
    FlightCategory,
    Modifier,
    ReportType,
    SemanticKind,
    SkyCondition,
)

REF = datetime(2026, 10, 13, 15, 0, tzinfo=UTC)
COBOL_SAMPLE = "METAR KDEN 131453Z 06007KT 3/4SM R35L/P6000FT BR OVC003 09/08 A3001 RMK AO2 SFC"


def kinds(raw: str, reference: datetime = REF) -> list[tuple[str, str]]:
    return [(t.text, t.kind.name) for t in parse_metar(raw, reference).tokens]


def assert_complete(raw: str) -> None:
    """Every non-blank character belongs to exactly one token, in order, with matching text."""
    decoded = parse_metar(raw, REF)
    covered: list[int] = []
    previous_end = 0
    for token in decoded.tokens:
        assert 0 <= token.start < token.end <= len(raw)
        assert token.start >= previous_end
        assert raw[token.start : token.end].upper() == token.text
        covered.extend(range(token.start, token.end))
        previous_end = token.end
    assert covered == [i for i, ch in enumerate(raw) if not ch.isspace()]


def test_cobol_sample() -> None:
    m = parse_metar(COBOL_SAMPLE, REF)
    assert m.report_type is ReportType.METAR
    assert m.station == "KDEN"
    assert m.observed == datetime(2026, 10, 13, 14, 53, tzinfo=UTC)
    assert m.wind is not None
    assert (m.wind.direction, m.wind.speed.value if m.wind.speed else None) == (60, 7)
    assert m.visibility is not None
    assert m.visibility.distance is not None
    assert m.visibility.distance.value == 0.75
    assert [r.runway for r in m.rvr] == ["35L"]
    assert [p.name for g in m.weather for p in g.phenomena] == ["BR"]
    assert [(layer.cover, layer.base.value if layer.base else None) for layer in m.sky] == [(SkyCondition.OVC, 300)]
    assert (m.temperature.value, m.dewpoint.value) == (9, 8)  # type: ignore[union-attr]
    assert m.altimeter is not None
    assert m.altimeter.value == 30.01
    assert m.remarks_raw == "AO2 SFC"
    assert m.flight_category is FlightCategory.LIFR
    assert m.warnings == ()
    assert_complete(COBOL_SAMPLE)


def test_tokens_are_tagged_in_report_order() -> None:
    assert kinds(COBOL_SAMPLE) == [
        ("METAR", "TYPE"),
        ("KDEN", "STATION"),
        ("131453Z", "TIME"),
        ("06007KT", "WIND"),
        ("3/4SM", "VISIBILITY"),
        ("R35L/P6000FT", "RVR"),
        ("BR", "WEATHER"),
        ("OVC003", "SKY"),
        ("09/08", "TEMPERATURE"),
        ("A3001", "PRESSURE"),
        ("RMK", "REMARK"),
        ("AO2", "REMARK"),
        ("SFC", "REMARK"),
    ]


def test_report_without_type_or_station_still_decodes() -> None:
    m = parse_metar("131453Z 06007KT 10SM CLR 09/08 A3001", REF)
    assert m.station is None
    assert m.observed is not None
    assert m.wind is not None
    assert m.flight_category is FlightCategory.VFR
    assert m.warnings == ()


def test_spec_style_report_type_default_is_metar() -> None:
    assert parse_metar("KDEN 131453Z 06007KT 10SM CLR 09/08 A3001", REF).report_type is ReportType.METAR
    assert parse_metar("SPECI KDEN 131453Z 06007KT 10SM CLR 09/08 A3001", REF).report_type is ReportType.SPECI


def test_modifier_before_the_station_is_accepted() -> None:
    m = parse_metar("METAR COR EGLL 311020Z 08005KT 9999 FEW040 10/08 Q1030", REF)
    assert m.station == "EGLL"
    assert m.modifiers == (Modifier.COR,)
    assert m.warnings == ()


def test_missing_groups_are_skipped() -> None:
    m = parse_metar("METAR KDEN 131453Z A3001", REF)
    assert m.wind is None
    assert m.visibility is None
    assert m.altimeter is not None
    assert m.flight_category is None
    assert m.warnings == ()


def test_unknown_token_gets_a_warning_and_parsing_continues() -> None:
    raw = "METAR KDEN 131453Z FOO 06007KT 10SM CLR 09/08 A3001"
    m = parse_metar(raw, REF)
    assert [(w.code, w.text) for w in m.warnings] == [("unknown_token", "FOO")]
    warning = m.warnings[0]
    assert raw[warning.start : warning.end] == "FOO"
    assert m.wind is not None
    assert m.altimeter is not None
    assert [t.kind for t in m.tokens if t.text == "FOO"] == [SemanticKind.UNKNOWN]


def test_a_repeated_group_is_unknown_not_overwritten() -> None:
    m = parse_metar("METAR KDEN 131453Z 06007KT 27015KT 10SM CLR 09/08 A3001", REF)
    assert m.wind is not None
    assert m.wind.direction == 60
    assert [w.text for w in m.warnings] == ["27015KT"]


def test_a_group_that_comes_too_late_is_unknown() -> None:
    m = parse_metar("METAR KDEN 131453Z 10SM 06007KT CLR 09/08 A3001", REF)
    assert m.wind is None
    assert [w.text for w in m.warnings] == ["06007KT"]
    assert m.sky


def test_rvr_weather_and_sky_may_come_in_any_order() -> None:
    m = parse_metar("METAR LFPG 131453Z 24008KT 0600 OVC002 FG R27L/0600N 06/06 Q1013", REF)
    assert m.warnings == ()
    assert m.rvr
    assert m.weather
    assert m.sky


def test_two_pressure_groups() -> None:
    m = parse_metar("METAR MMMX 131453Z 32005KT 6SM SKC 17/10 Q1020 A3012", REF)
    assert [p.unit.name for p in m.altimeters] == ["HPA", "INHG"]
    assert m.altimeter == m.altimeters[0]
    assert m.warnings == ()


def test_unreported_pressure_is_consumed_without_a_value() -> None:
    m = parse_metar("METAR KDEN 131453Z 06007KT 10SM CLR 09/08 A////", REF)
    assert m.altimeters == ()
    assert m.warnings == ()


def test_remarks_are_tagged_and_kept_verbatim() -> None:
    raw = "METAR KDEN 131453Z 06007KT 10SM CLR 09/08 A3001 RMK AO2   SLP162 T00890078 ="
    m = parse_metar(raw, REF)
    assert m.remarks_index == 8
    assert m.remarks_raw == "AO2   SLP162 T00890078"
    assert [t.text for t in m.remarks_tokens] == ["AO2", "SLP162", "T00890078"]
    assert m.tokens[-1].kind is SemanticKind.TERMINATOR
    assert all(t.kind is SemanticKind.REMARK for t in m.tokens[8:-1])
    assert m.warnings == ()


def test_rmk_without_content() -> None:
    m = parse_metar("METAR KDEN 131453Z 06007KT 10SM CLR 09/08 A3001 RMK", REF)
    assert m.remarks_raw == ""
    assert m.remarks_tokens == ()


def test_no_remarks() -> None:
    m = parse_metar("METAR EGLL 311050Z 24010KT CAVOK 12/08 Q1013", REF)
    assert m.remarks_index is None
    assert m.remarks_raw is None


def test_tail_groups_are_recognised_without_warnings() -> None:
    raw = "METAR EGLL 311050Z 24010KT 9999 FEW040 12/08 Q1013 RERA WS ALL RWY 8849//91 BLU TEMPO 5000 -RA NOSIG RMK X"
    m = parse_metar(raw, REF)
    assert m.warnings == ()
    assert m.tail_index == 8
    assert m.remarks_index == m.tail_index + len(m.tail_tokens)
    assert [t.kind.name for t in m.tail_tokens] == [
        "RECENT_WEATHER",
        "WIND_SHEAR",
        "WIND_SHEAR",
        "WIND_SHEAR",
        "RUNWAY_STATE",
        "COLOR_STATE",
        "TREND",
        "TREND",
        "TREND",
        "TREND",
    ]
    assert m.military


def test_tail_index_is_none_without_a_tail() -> None:
    m = parse_metar("METAR EGLL 311050Z 24010KT CAVOK 12/08 Q1013", REF)
    assert m.tail_index is None
    assert m.tail_tokens == ()


def test_terminator_is_not_part_of_the_tail() -> None:
    m = parse_metar("METAR EGLL 311050Z 24010KT CAVOK 12/08 Q1013 NOSIG=", REF)
    assert [t.text for t in m.tail_tokens] == ["NOSIG"]
    assert m.tokens[-1].kind is SemanticKind.TERMINATOR
    assert m.warnings == ()


def test_lowercase_input_is_accepted() -> None:
    raw = "metar kden 131453z 06007kt 3/4sm br ovc003 09/08 a3001"
    m = parse_metar(raw, REF)
    assert m.station == "KDEN"
    assert m.flight_category is FlightCategory.LIFR
    assert m.warnings == ()
    assert_complete(raw)


def test_leading_and_trailing_whitespace_and_newlines() -> None:
    raw = "\n  METAR KDEN 131453Z\n06007KT 10SM CLR 09/08 A3001  \n"
    m = parse_metar(raw, REF)
    assert m.warnings == ()
    assert m.wind is not None
    assert_complete(raw)


def test_invalid_day_produces_a_warning_not_a_time() -> None:
    m = parse_metar("METAR KDEN 321453Z 06007KT 10SM CLR 09/08 A3001", REF)
    assert m.observed is None
    assert [w.code for w in m.warnings] == ["invalid_day"]
    assert m.tokens[2].kind is SemanticKind.TIME


def test_invalid_time_produces_a_warning() -> None:
    m = parse_metar("METAR KDEN 139961Z 06007KT 10SM CLR 09/08 A3001", REF)
    assert m.observed is None
    assert [w.code for w in m.warnings] == ["invalid_time"]


def test_reference_decides_the_month() -> None:
    raw = "METAR KDEN 312350Z 06007KT 10SM CLR 09/08 A3001"
    assert parse_metar(raw, datetime(2026, 11, 1, 0, 10, tzinfo=UTC)).observed == datetime(
        2026, 10, 31, 23, 50, tzinfo=UTC
    )
    assert parse_metar(raw, datetime(2026, 10, 31, 23, 55, tzinfo=UTC)).observed == datetime(
        2026, 10, 31, 23, 50, tzinfo=UTC
    )


def test_reference_defaults_to_now() -> None:
    today = datetime.now(UTC)
    m = parse_metar(f"METAR KDEN {today:%d%H%M}Z 06007KT 10SM CLR 09/08 A3001")
    assert m.observed is not None
    assert abs(m.observed - today) < timedelta(minutes=2)


def test_naive_reference_is_utc() -> None:
    m = parse_metar("METAR KDEN 131453Z 06007KT 10SM CLR 09/08 A3001", datetime(2026, 10, 13, 15, 0))
    assert m.observed == datetime(2026, 10, 13, 14, 53, tzinfo=UTC)


def test_nil_report() -> None:
    m = parse_metar("METAR LIRF 311050Z NIL", REF)
    assert m.modifiers == (Modifier.NIL,)
    assert m.warnings == ()
    assert m.flight_category is None


def test_taf_is_not_decoded_but_not_lost() -> None:
    raw = "TAF KDEN 131130Z 1312/1418 06007KT P6SM SKC"
    m = parse_metar(raw, REF)
    assert [w.code for w in m.warnings] == ["unsupported_report"]
    assert all(t.kind is SemanticKind.UNKNOWN for t in m.tokens)
    assert m.wind is None
    assert_complete(raw)


@pytest.mark.parametrize("raw", ["", "   ", "\n\n", "="])
def test_empty_input(raw: str) -> None:
    m = parse_metar(raw, REF)
    assert m.station is None
    assert m.flight_category is None
    assert_complete(raw)


def test_garbage_input_is_all_unknown_with_warnings() -> None:
    m = parse_metar("hello world 12345", REF)
    assert [w.code for w in m.warnings] == ["unknown_token"] * 3
    assert all(t.kind is SemanticKind.UNKNOWN for t in m.tokens)


def test_a_failing_group_parser_is_contained(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(cur: object) -> None:
        raise RuntimeError("simulated bug")

    monkeypatch.setattr(metar_module, "parse_wind", boom)
    raw = "METAR KDEN 131453Z 06007KT 10SM CLR 09/08 A3001"
    m = parse_metar(raw, REF)
    assert m.wind is None
    assert "parser_error" in {w.code for w in m.warnings}
    assert m.visibility is not None  # parsing carried on
    assert m.altimeter is not None
    assert_complete(raw)


def test_total_failure_still_returns_every_token(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(tokens: object) -> None:
        raise RuntimeError("simulated bug")

    monkeypatch.setattr(metar_module, "detect_flavor", boom)
    raw = "METAR KDEN 131453Z 06007KT"
    m = parse_metar(raw, REF)
    assert [w.code for w in m.warnings] == ["parser_error"]
    assert [t.text for t in m.tokens] == ["METAR", "KDEN", "131453Z", "06007KT"]
    assert_complete(raw)


def test_flavor_us_icao_and_mixed() -> None:
    assert parse_metar(COBOL_SAMPLE, REF).flavor is Flavor.US
    assert parse_metar("METAR EGLL 311050Z 24010KT CAVOK 12/08 Q1013", REF).flavor is Flavor.ICAO
    assert parse_metar("METAR MMMX 131453Z 32005KT 6SM SKC 17/10 Q1020 A3012 NOSIG", REF).flavor is Flavor.MIXED


def test_flavor_ignores_us_remark_numbers() -> None:
    """A four-digit remark group (WSHFT 1715) must not turn a US report into a mixed one."""
    m = parse_metar("METAR KDEN 131453Z 06007KT 10SM CLR 09/08 A3001 RMK AO2 WSHFT 1715", REF)
    assert m.flavor is Flavor.US


def test_military_flag_comes_from_colour_states_not_the_prefix() -> None:
    assert parse_metar("METAR EGVN 311550Z 29006KT 9999 FEW040 10/04 Q1021 BLU NOSIG", REF).military
    assert not parse_metar("METAR EGLL 311050Z 24010KT CAVOK 12/08 Q1013 NOSIG", REF).military


@pytest.mark.parametrize("path", report_files(), ids=lambda p: p.stem)
def test_corpus_reports_decode_cleanly(path: Path) -> None:
    raw = read_raw(path)
    m = parse_metar(raw, reference_for(path))
    assert m.warnings == (), f"{path.name}: {m.warnings}"
    time_token = next((t for t in m.tokens if t.kind is SemanticKind.TIME), None)
    if time_token is not None:
        assert m.observed is not None
        assert m.observed.strftime("%d%H%MZ") == time_token.text
    assert_complete(raw)
