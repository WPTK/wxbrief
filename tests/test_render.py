"""Highlight spans, plain text, Rich text and JSON output."""

from __future__ import annotations

import io
import itertools
import json
from datetime import UTC, datetime

import pytest
from rich.console import Console

from wxbrief.decode.metar import parse_metar
from wxbrief.decode.model import FlightCategory, Metar, SemanticKind
from wxbrief.decode.units import UnitsMode
from wxbrief.i18n import Translator
from wxbrief.render.highlight import STYLE_KEYS, HighlightSpan, highlight_spans, style_key, style_name
from wxbrief.render.jsonout import to_dict
from wxbrief.render.plain import decode_rows, render_plain, warning_lines
from wxbrief.render.richtext import DEFAULT_THEME, build_renderable, highlighted_raw

T = Translator.load("en")
REF = datetime(2026, 10, 13, 15, 0, tzinfo=UTC)
COBOL = "METAR KDEN 131453Z 06007KT 3/4SM R35L/P6000FT BR OVC003 09/08 A3001 RMK AO2 SFC"
DEG = "°"


def decode(raw: str, reference: datetime = REF) -> Metar:
    return parse_metar(raw, reference)


# --- highlight ------------------------------------------------------------------------------------------------


def test_one_span_per_token_in_order() -> None:
    m = decode(COBOL)
    spans = highlight_spans(m.tokens)
    assert len(spans) == len(m.tokens)
    assert spans[0] == HighlightSpan(0, 5, SemanticKind.TYPE)
    assert [COBOL[s.start : s.end] for s in spans][:3] == ["METAR", "KDEN", "131453Z"]
    assert all(a.end <= b.start for a, b in itertools.pairwise(spans))


def test_every_kind_has_a_style() -> None:
    assert set(STYLE_KEYS) == set(SemanticKind)
    for kind in SemanticKind:
        assert style_name(kind) == f"wx.{style_key(kind)}"
        assert style_name(kind) in DEFAULT_THEME.styles


def test_style_names_follow_the_plan() -> None:
    assert style_name(SemanticKind.WIND) == "wx.wind"
    assert style_name(SemanticKind.VISIBILITY) == "wx.vis"
    assert style_name(SemanticKind.WEATHER) == "wx.wx"
    assert style_name(SemanticKind.SKY) == "wx.cloud"
    assert style_name(SemanticKind.COLOR_STATE) == "wx.color-state"
    assert style_name(SemanticKind.UNKNOWN) == "wx.unknown"


# --- plain ----------------------------------------------------------------------------------------------------


def test_plain_decode_in_us_units() -> None:
    assert render_plain(decode(COBOL), T, UnitsMode.US).splitlines() == [
        "Station:             KDEN",
        "Report:              Routine observation (METAR)",
        "Observed:            2026-10-13 14:53 UTC",
        "Flight category:     LIFR (low instrument flight rules)",
        f"Wind:                From 060{DEG} (ENE) at 7 kt",
        "Visibility:          3/4 SM",
        "Runway visual range: Runway 35L: more than 6,000 ft",
        "Weather:             Mist",
        "Sky:                 Overcast at 300 ft",
        "Ceiling:             300 ft",
        f"Temperature:         48 {DEG}F (9 {DEG}C)",
        f"Dew point:           46 {DEG}F (8 {DEG}C)",
        "Relative humidity:   94%",
        "Pressure:            30.01 inHg",
        "Remark:              Automated station with a precipitation discriminator",
        "Remark:              Surface",
        "Flags:               Low ceiling, Low visibility",
        "Summary:             KDEN is reporting LIFR (low instrument flight rules): mist, ceiling 300 ft, "
        f"visibility 3/4 SM, wind from 060{DEG} (ENE) at 7 kt.",
    ]


def test_plain_decode_of_an_icao_report_shows_metres_and_hpa_with_conversions() -> None:
    raw = "METAR EGLL 311050Z AUTO 24010KT 200V280 CAVOK 12/08 Q1013 NOSIG"
    text = render_plain(decode(raw, datetime(2026, 10, 31, 11, 0, tzinfo=UTC)), T, UnitsMode.MIXED)
    assert (
        f"Wind:              From 240{DEG} (WSW) at 10 kt (19 km/h); direction varies between 200{DEG} and 280{DEG}"
        in text
    )
    assert (
        "Visibility:        CAVOK: visibility at least 10 km (6.2 SM), no cloud below 5,000 ft (1,524 m)" in text
    )
    assert "Pressure:          1013 hPa (29.91 inHg)" in text
    assert f"Temperature:       12 {DEG}C (54 {DEG}F)" in text
    assert "Trend:             No significant change expected in the next 2 hours" in text
    assert "Flags:             Automated observation" in text


def test_plain_decode_in_metric_units() -> None:
    text = render_plain(decode(COBOL), T, UnitsMode.METRIC)
    assert "Visibility:          1.2 km (3/4 SM)" in text
    assert "Pressure:            1016 hPa (30.01 inHg)" in text
    assert f"Temperature:         9 {DEG}C" in text


def test_plain_labels_line_up() -> None:
    lines = render_plain(decode(COBOL), T, UnitsMode.US).splitlines()
    value_columns = set()
    for line in lines:
        label, rest = line.split(":", 1)
        value_columns.add(len(label) + 1 + len(rest) - len(rest.lstrip()))
    assert len(value_columns) == 1


def test_plain_decode_lists_warnings_after_a_blank_line() -> None:
    lines = render_plain(decode("METAR KDEN 131453Z FOO BAR"), T, UnitsMode.US).splitlines()
    assert lines[-4:] == ["", "2 warnings", "  - Unrecognized group: FOO", "  - Unrecognized group: BAR"]
    assert warning_lines(decode("METAR KDEN 131453Z FOO"), T) == ["1 warning", "  - Unrecognized group: FOO"]
    assert warning_lines(decode(COBOL), T) == []


def test_plain_decode_of_garbage_says_so() -> None:
    text = render_plain(decode("hello"), T, UnitsMode.US)
    assert text.splitlines() == [
        "Summary: No conditions could be decoded.",
        "",
        "1 warning",
        "  - Unrecognized group: HELLO",
    ]


def test_plain_decode_has_no_ansi_escapes() -> None:
    assert "\x1b" not in render_plain(decode(COBOL), T)


def test_rows_expose_category_for_badges() -> None:
    rows = decode_rows(decode(COBOL), T, UnitsMode.US)
    category_rows = [row for row in rows if row.category is not None]
    assert [row.category for row in category_rows] == [FlightCategory.LIFR]
    assert rows[0].label == "Station"
    assert rows[0].style == "wx.station"


def test_notes_row_for_modifiers_that_are_not_flags() -> None:
    rows = {row.label: row.value for row in decode_rows(decode("METAR LIRF 311050Z NIL"), T, UnitsMode.US)}
    assert rows["Notes"] == "No report available (NIL)"
    quiet = {
        row.label
        for row in decode_rows(decode("METAR KDEN 131453Z AUTO 06007KT 10SM CLR 09/08 A3001"), T, UnitsMode.US)
    }
    assert "Notes" not in quiet


def test_two_altimeters_get_two_rows() -> None:
    rows = decode_rows(decode("METAR MMMX 131453Z 32005KT 6SM SKC 17/10 Q1020 A3012"), T, UnitsMode.MIXED)
    assert [row.value for row in rows if row.label == "Pressure"] == ["1020 hPa (30.12 inHg)", "30.12 inHg (1020 hPa)"]


# --- Rich -----------------------------------------------------------------------------------------------------


def render_to_text(raw: str) -> str:
    sink = io.StringIO()
    console = Console(theme=DEFAULT_THEME, width=120, force_terminal=False, color_system=None, file=sink)
    console.print(build_renderable(decode(raw), T, UnitsMode.MIXED))
    return sink.getvalue()


def test_rich_output_contains_the_decode() -> None:
    text = render_to_text(COBOL)
    assert text.splitlines()[0] == COBOL
    assert "LIFR (low instrument flight rules)" in text
    assert "Runway 35L: more than 6,000 ft (1,829 m)" in text


def test_rich_output_lists_warnings() -> None:
    assert "1 warning" in render_to_text("METAR KDEN 131453Z FOO")


def test_highlighted_raw_styles_each_token() -> None:
    m = decode(COBOL)
    text = highlighted_raw(m)
    assert text.plain == COBOL
    spans = {(span.start, span.end): str(span.style) for span in text.spans}
    assert spans[(0, 5)] == "wx.station"
    assert spans[(19, 26)] == "wx.wind"
    assert spans[(27, 32)] == "wx.vis"
    assert len(spans) == len(m.tokens)


def test_default_theme_defines_flight_category_styles() -> None:
    for category in FlightCategory:
        assert f"fcat.{category.value.lower()}" in DEFAULT_THEME.styles
        assert f"fcat.{category.value.lower()}.badge" in DEFAULT_THEME.styles


def test_flight_category_badge_is_coloured_on_a_terminal() -> None:
    sink = io.StringIO()
    console = Console(theme=DEFAULT_THEME, width=120, force_terminal=True, color_system="standard", file=sink)
    console.print(build_renderable(decode(COBOL), T, UnitsMode.MIXED))
    badge_line = next(line for line in sink.getvalue().splitlines() if "LIFR (low instrument" in line)
    assert "[" in badge_line.split("LIFR")[0]  # the badge carries its own colour codes


# --- JSON -----------------------------------------------------------------------------------------------------


def test_to_dict_is_json_serialisable_and_uses_names() -> None:
    data = to_dict(decode(COBOL))
    json.dumps(data)  # must not raise
    assert data["station"] == "KDEN"
    assert data["report_type"] == "METAR"
    assert data["observed"] == "2026-10-13T14:53:00+00:00"
    assert data["flight_category"] == "LIFR"
    assert data["wind"] == {
        "direction": 60,
        "speed": {"value": 7, "unit": "KT"},
        "gust": None,
        "variable": False,
        "speed_above": False,
    }
    assert data["rvr"][0]["prefix"] == "GREATER_THAN"
    assert data["flags"] == ["LOW_CEILING", "LOW_VISIBILITY"]
    assert data["tokens"][0] == {"text": "METAR", "start": 0, "end": 5, "kind": "TYPE"}
    assert data["remarks_raw"] == "AO2 SFC"


def test_to_dict_covers_every_model_field() -> None:
    from dataclasses import fields

    assert set(to_dict(decode(COBOL))) == {f.name for f in fields(Metar)}


def test_to_dict_round_trips_through_json() -> None:
    data = to_dict(decode(COBOL))
    assert json.loads(json.dumps(data)) == data


def test_to_dict_rejects_non_dataclasses() -> None:
    with pytest.raises(TypeError):
        to_dict("not a dataclass")
