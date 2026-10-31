"""Control characters in report text are dropped where it enters the decoder, so no renderer can pass them on."""

from __future__ import annotations

import io
from datetime import UTC, datetime

from rich.console import Console

from wxbrief.decode.metar import parse_metar
from wxbrief.decode.split import parse_any
from wxbrief.decode.taf import parse_taf
from wxbrief.decode.units import UnitsMode
from wxbrief.i18n import Translator
from wxbrief.render.plain import render_plain
from wxbrief.render.richtext import DEFAULT_THEME, build_renderable

REF = datetime(2025, 1, 13, 12, tzinfo=UTC)
ESC = chr(27)
OSC52 = f"{ESC}]52;c;aGkh{ESC}\\"
TITLE = f"{ESC}]0;owned{ESC}\\"
CSI = f"{ESC}[31m"
METAR = "METAR KDEN 131453Z 06007KT 10SM FEW030 09/08 A3001 RMK AO2"
T = Translator.load("en")


def _has_control(text: str) -> bool:
    return any(ch not in "\n\t" and (ord(ch) < 32 or 127 <= ord(ch) < 160) for ch in text)


def test_osc52_and_title_sequences_do_not_reach_any_renderer() -> None:
    (report,) = parse_any(f"{METAR} {OSC52} {TITLE}", REF)
    assert not _has_control(report.raw)
    assert not _has_control(render_plain(report, T, UnitsMode.US))
    buf = io.StringIO()
    Console(file=buf, force_terminal=True, theme=DEFAULT_THEME, width=200).print(build_renderable(report, T, UnitsMode.US))
    assert OSC52 not in buf.getvalue() and TITLE not in buf.getvalue()
    assert ESC + "]" not in buf.getvalue()


def test_csi_sequence_is_not_uppercased_into_a_working_one() -> None:
    (report,) = parse_any(f"{METAR} {CSI}", REF)
    assert ESC not in render_plain(report, T, UnitsMode.US)


def test_direct_parsers_strip_too_because_the_tui_data_layer_calls_them() -> None:
    assert not _has_control(parse_metar(f"{METAR} {OSC52}", REF).raw)
    assert not _has_control(parse_taf(f"TAF KDEN 131130Z 1312/1418 06007KT P6SM SKC {CSI}", REF).raw)


def test_newline_tab_and_crlf_survive() -> None:
    cr, nl, tab, nul, bel = chr(13), chr(10), chr(9), chr(0), chr(7)
    text = f"TAF KDEN 131130Z 1312/1418 06007KT P6SM SKC{cr}{nl}{tab}FM131800 09010KT P6SM SKC"
    (taf,) = parse_any(text, REF)
    assert taf.raw.replace(cr, "") == text.replace(cr, "")
    assert not _has_control(parse_metar(f"KDEN 131453Z{nul} 06007KT{bel}{cr}10SM 09/08 A3001", REF).raw)
