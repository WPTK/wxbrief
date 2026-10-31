"""Property tests: the decoder never raises, and every character of the input stays accounted for.

Two sources of input: arbitrary text, and real reports (the saved corpus and AWC batches) mutated token by token --
dropped, duplicated, truncated, garbled, swapped -- the way copy-paste accidents and bad feeds break them.
"""

from __future__ import annotations

import io
import json
import os
import time
from datetime import UTC, datetime

from corpus import awc_rows, awc_taf_rows, read_raw, report_files, taf_files
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from rich.console import Console

from wxbrief.decode.metar import parse_metar
from wxbrief.decode.model import Metar, Taf
from wxbrief.decode.split import parse_any
from wxbrief.decode.taf import parse_taf
from wxbrief.decode.timeline import expand_timeline
from wxbrief.decode.tokens import strip_controls
from wxbrief.decode.units import UnitsMode
from wxbrief.i18n import Translator
from wxbrief.render.discord import discord_block
from wxbrief.render.highlight import highlight_spans
from wxbrief.render.jsonout import to_dict
from wxbrief.render.plain import render_plain
from wxbrief.render.richtext import DEFAULT_THEME, build_renderable

REF = datetime(2026, 10, 13, 15, 0, tzinfo=UTC)
T = Translator.load("en")

# 2,000 examples per property by default; set WXBRIEF_FUZZ_EXAMPLES for a deeper local run.
EXAMPLES = int(os.environ.get("WXBRIEF_FUZZ_EXAMPLES", "2000"))
FUZZ = settings(
    max_examples=EXAMPLES,
    deadline=None,
    database=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large, HealthCheck.filter_too_much],
)

# Characters that make up reports, so random strings look a little like them.
REPORT_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ/+-=. \t\n"
GARBLE_CHARS = "0123456789/+-=ABCXYZ°☃\x00 "

CORPUS = sorted({read_raw(path) for path in report_files()} | {row["rawOb"] for row in awc_rows()})


def check(raw: str) -> None:
    """The decoder's contract for any input."""
    metar = parse_metar(raw, REF)
    assert metar.raw == strip_controls(raw)  # tokens index the text with the control characters dropped
    raw = metar.raw

    covered: list[int] = []
    previous_end = 0
    for token in metar.tokens:
        assert 0 <= token.start < token.end <= len(raw)
        assert token.start >= previous_end  # in order, no overlap
        assert raw[token.start : token.end].upper() == token.text
        covered.extend(range(token.start, token.end))
        previous_end = token.end
    assert covered == [i for i, ch in enumerate(raw) if not ch.isspace()]

    for warning in metar.warnings:
        assert 0 <= warning.start <= warning.end <= len(raw)

    spans = highlight_spans(metar.tokens)
    assert [(s.start, s.end) for s in spans] == [(t.start, t.end) for t in metar.tokens]

    # Rendering what was decoded must not fail either.
    render_plain(metar, T, UnitsMode.MIXED)
    json.dumps(to_dict(metar))


@given(st.text())
@FUZZ
def test_arbitrary_text(raw: str) -> None:
    check(raw)


@given(st.text(alphabet=REPORT_ALPHABET, max_size=200))
@FUZZ
def test_text_made_of_report_characters(raw: str) -> None:
    check(raw)


@st.composite
def mutated_reports(draw: st.DrawFn) -> str:
    tokens = draw(st.sampled_from(CORPUS)).split(" ")
    for _ in range(draw(st.integers(min_value=0, max_value=6))):
        if not tokens:
            break
        operation = draw(st.sampled_from(["drop", "duplicate", "truncate", "garble", "swap", "insert"]))
        index = draw(st.integers(min_value=0, max_value=len(tokens) - 1))
        token = tokens[index]
        if operation == "drop":
            del tokens[index]
        elif operation == "duplicate":
            tokens.insert(index, token)
        elif operation == "truncate":
            tokens[index] = token[: draw(st.integers(min_value=0, max_value=len(token)))]
        elif operation == "garble" and token:
            at = draw(st.integers(min_value=0, max_value=len(token) - 1))
            tokens[index] = token[:at] + draw(st.sampled_from(GARBLE_CHARS)) + token[at + 1 :]
        elif operation == "swap":
            other = draw(st.integers(min_value=0, max_value=len(tokens) - 1))
            tokens[index], tokens[other] = tokens[other], tokens[index]
        elif operation == "insert":
            tokens.insert(index, draw(st.text(alphabet=REPORT_ALPHABET, max_size=8)))
    separator = draw(st.sampled_from([" ", "  ", "\n", " \t ", "="]))
    return separator.join(tokens)


@given(mutated_reports())
@FUZZ
def test_mutated_corpus_reports(raw: str) -> None:
    check(raw)


@given(mutated_reports())
@settings(max_examples=200, deadline=None, database=None, suppress_health_check=[HealthCheck.too_slow])
def test_rich_rendering_of_mutated_reports(raw: str) -> None:
    metar = parse_metar(raw, REF)
    console = Console(file=io.StringIO(), width=100, theme=DEFAULT_THEME, color_system=None)
    console.print(build_renderable(metar, T, UnitsMode.MIXED))


# Remark tokens of every shape (the saved reports and the hand-written variants) to mix at random.
REMARK_TOKENS = sorted(
    {
        token
        for raw in CORPUS
        if " RMK " in raw
        for token in raw.split(" RMK ", 1)[1].replace("=", " ").split()
    }
    | {
        "AO1", "PK", "WND", "20032/25", "28045/1547", "WSHFT", "1715", "FROPA", "TWR", "SFC", "VIS", "3/4V1", "1/2",
        "NE", "CIG", "013V017", "RWY11", "PRESRR", "PRESFR", "SLPNO", "P////", "60009", "6////", "70015", "T0233",
        "10233", "1////", "21012", "400461006", "53011", "58033", "RVRNO", "PWINO", "VISNO", "CHINO", "$", "4/012",
        "SNINCR", "2/10", "8/208", "GR", "LESS", "THAN", "DENSITY", "ALT", "2500FT", "SC5AC2", "TR", "A3007",
        "A30.06", "QFE756/1008", "QNH766", "R06/31003MPS", "WIND", "2600FT", "19040KT", "RED", "BECMG", "AMB",
        "FRQ", "OCNL", "LTGICCG", "DSNT", "OHD", "NE-SE", "AND", "TSB0159E30", "RAE0755RAB22E31", "-SNB10",
    }
)


@st.composite
def remark_reports(draw: st.DrawFn) -> str:
    """A body followed by RMK and a random run of remark tokens, some of them mangled."""
    body = draw(st.sampled_from(["METAR KDEN 311153Z 18006KT 10SM CLR 08/06 A3004", "METAR EGLL 311150Z 24010KT CAVOK 12/08 Q1013 NOSIG"]))
    tokens = [draw(st.sampled_from(REMARK_TOKENS)) for _ in range(draw(st.integers(min_value=0, max_value=14)))]
    for _ in range(draw(st.integers(min_value=0, max_value=3))):
        if not tokens:
            break
        index = draw(st.integers(min_value=0, max_value=len(tokens) - 1))
        token = tokens[index]
        operation = draw(st.sampled_from(["truncate", "garble", "drop", "duplicate"]))
        if operation == "drop":
            del tokens[index]
        elif operation == "duplicate":
            tokens.insert(index, token)
        elif operation == "truncate":
            tokens[index] = token[: draw(st.integers(min_value=0, max_value=len(token)))]
        elif token:
            at = draw(st.integers(min_value=0, max_value=len(token) - 1))
            tokens[index] = token[:at] + draw(st.sampled_from(GARBLE_CHARS)) + token[at + 1 :]
    return body + " RMK " + draw(st.sampled_from([" ", "  ", "\n"])).join(tokens)


@given(remark_reports())
@FUZZ
def test_random_remarks(raw: str) -> None:
    check(raw)


def test_corpus_is_large_enough_to_mutate() -> None:
    assert len(CORPUS) > 900


def test_pathological_inputs_stay_fast() -> None:
    """Long runs of group-like characters must not trigger catastrophic regex backtracking."""
    nasty = [
        "RE" + "TS" * 5000 + "X",
        "RE" + "TSRA" * 3000 + "?",
        "R" + "1" * 20000,
        "R35L/" + "P" * 10000,
        "-" * 20000,
        "VC" * 10000,
        "BKN" + "0" * 20000,
        "1 " * 20000,
        "M" * 20000 + "/" + "M" * 20000,
        "/" * 50000,
        "A" * 100000,
        " ".join(["TEMPO"] * 20000),
        "=" * 50000,
        # tail groups and remarks
        "RMK " + "RAB07E45" * 5000,
        "RMK " + "DZB04E37RA" * 4000 + "B37",
        "RMK " + "RAB" * 10000,
        "RMK SC5" + "AC2" * 10000,
        "RMK " + "SC9" * 10000 + "X",
        "RMK LTG" + "IC" * 20000 + "X",
        "RMK " + " ".join(["PK WND 20032/25"] * 5000),
        "RMK " + " ".join(["VIS 3/4V1 1/2"] * 5000),
        "RMK " + " ".join(["AC1 AC TR"] * 5000),
        "RMK " + " ".join(["T02330200"] * 5000),
        "RMK " + "4" * 50000,
        "RMK " + "/" * 50000,
        "RMK " + "GR 1 " * 10000,
        "BECMG " + "FM1130 " * 10000,
        "BECMG " + "3000 " * 10000,
        "BLU " + "TEMPO YLO " * 10000,
        "TEMPO " + "BLU " * 10000,
        "WS " + "R24L " * 10000,
        "WS " + "ALL RWY " * 10000,
        "R24L/" + "2" * 30000,
        "88" + "/" * 30000,
        "W" + "1" * 30000 + "/S3",
        "RE" + "-+" * 10000,
        "METAR EGLL 311150Z 24010KT 9999 FEW040 12/08 Q1013 " + " ".join(["RERA"] * 5000),
        "METAR EGLL 311150Z 24010KT 9999 FEW040 12/08 Q1013 " + " ".join(["TEMPO BECMG NOSIG BLU RMK"] * 3000),
    ]
    started = time.perf_counter()
    for raw in nasty:
        check(raw)
    assert time.perf_counter() - started < 120  # a quadratic blow-up takes many minutes; this only has to survive a slow runner


# --- TAFs ----------------------------------------------------------------------------------------------------------

TAF_CORPUS = sorted({read_raw(path) for path in taf_files()} | {row["rawTAF"].strip() for row in awc_taf_rows()})


def check_taf(raw: str) -> None:
    """The decoder's contract for any input read as a TAF: the same as ``check``, plus the timeline and the output."""
    taf = parse_taf(raw, REF)
    assert taf.raw == strip_controls(raw)
    raw = taf.raw

    covered: list[int] = []
    previous_end = 0
    for token in taf.tokens:
        assert 0 <= token.start < token.end <= len(raw)
        assert token.start >= previous_end
        assert raw[token.start : token.end].upper() == token.text
        covered.extend(range(token.start, token.end))
        previous_end = token.end
    assert covered == [i for i, ch in enumerate(raw) if not ch.isspace()]

    for warning in taf.warnings:
        assert 0 <= warning.start <= warning.end <= len(raw)
    known = set(taf.tokens)
    for period in taf.periods:
        assert set(period.tokens) <= known

    timeline = expand_timeline(taf)
    for left, right in zip(timeline.slices, timeline.slices[1:], strict=False):
        assert left.end == right.start
    timeline.hourly()
    render_plain(taf, T, UnitsMode.MIXED)
    discord_block(taf, T, UnitsMode.US)
    json.dumps(to_dict(taf))


def mutate(draw: st.DrawFn, corpus: list[str]) -> str:
    tokens = draw(st.sampled_from(corpus)).split(" ")
    for _ in range(draw(st.integers(min_value=0, max_value=6))):
        if not tokens:
            break
        operation = draw(st.sampled_from(["drop", "duplicate", "truncate", "garble", "swap", "insert"]))
        index = draw(st.integers(min_value=0, max_value=len(tokens) - 1))
        token = tokens[index]
        if operation == "drop":
            del tokens[index]
        elif operation == "duplicate":
            tokens.insert(index, token)
        elif operation == "truncate":
            tokens[index] = token[: draw(st.integers(min_value=0, max_value=len(token)))]
        elif operation == "garble" and token:
            at = draw(st.integers(min_value=0, max_value=len(token) - 1))
            tokens[index] = token[:at] + draw(st.sampled_from(GARBLE_CHARS)) + token[at + 1 :]
        elif operation == "swap":
            other = draw(st.integers(min_value=0, max_value=len(tokens) - 1))
            tokens[index], tokens[other] = tokens[other], tokens[index]
        elif operation == "insert":
            tokens.insert(index, draw(st.text(alphabet=REPORT_ALPHABET, max_size=8)))
    return draw(st.sampled_from([" ", "  ", "\n", " \t ", "="])).join(tokens)


@st.composite
def mutated_tafs(draw: st.DrawFn) -> str:
    return mutate(draw, TAF_CORPUS)


@given(mutated_tafs())
@FUZZ
def test_mutated_corpus_tafs(raw: str) -> None:
    check_taf(raw)


@given(st.text(alphabet=REPORT_ALPHABET, max_size=200).map(lambda text: "TAF KDEN 130500Z 1306/1412 " + text))
@FUZZ
def test_text_after_a_taf_header(raw: str) -> None:
    check_taf(raw)


@given(st.text())
@FUZZ
def test_arbitrary_text_as_a_taf(raw: str) -> None:
    check_taf(raw)


@given(mutated_tafs(), mutated_reports())
@settings(max_examples=300, deadline=None, database=None, suppress_health_check=[HealthCheck.too_slow])
def test_parse_any_of_a_mixed_blob(taf_raw: str, metar_raw: str) -> None:
    """Splitting loses nothing and every piece decodes: whatever the pieces look like."""
    blob = taf_raw + "\n" + metar_raw
    reports = parse_any(blob, REF)
    assert all(isinstance(report, (Metar, Taf)) for report in reports)
    assert "".join("".join(report.raw.split()) for report in reports) == "".join(strip_controls(blob).split())


@given(mutated_tafs())
@settings(max_examples=200, deadline=None, database=None, suppress_health_check=[HealthCheck.too_slow])
def test_rich_rendering_of_mutated_tafs(raw: str) -> None:
    taf = parse_taf(raw, REF)
    console = Console(file=io.StringIO(), width=100, theme=DEFAULT_THEME, color_system=None)
    console.print(build_renderable(taf, T, UnitsMode.MIXED))


def test_taf_corpus_is_large_enough_to_mutate() -> None:
    assert len(TAF_CORPUS) > 200


def test_pathological_tafs_stay_fast() -> None:
    nasty = [
        "TAF KDEN 130500Z 1306/1412 " + " ".join(["TEMPO 1306/1308 3SM BR"] * 3000),
        "TAF KDEN 130500Z 1306/1412 " + " ".join(["BECMG 1306/1308 VRB03KT"] * 3000),
        "TAF KDEN 130500Z 1306/1412 18010KT " + " ".join(["FM130800 18010KT P6SM SKC"] * 3000),
        "TAF KDEN 130500Z 1306/1412 " + "PROB30 " * 10000,
        "TAF KDEN 130500Z 1306/1412 " + "WS020/" * 10000,
        "TAF KDEN 130500Z 1306/1412 " + " ".join(["TX20/1318Z TNM05/1410Z"] * 3000),
        "TAF KDEN 130500Z 1306/1412 " + " ".join(["520009 610505 QNH2992INS"] * 3000),
        "TAF KDEN 130500Z 1306/1412 " + "FM" * 20000,
        "TAF " + "A" * 100000,
        "TAF KDEN 130500Z 1306/1412 " + "1306/1412 " * 10000,
        "TAF KDEN 130500Z 1306/1412 RMK " + "LAST NO AMDS AFT 3023 " * 5000,
        "TAF KDEN 130500Z 1306/1412 " + "LAST NO AMDS AFT 3023 NEXT 0207 " * 5000,
    ]
    started = time.perf_counter()
    for raw in nasty:
        check_taf(raw)
    assert time.perf_counter() - started < 120
