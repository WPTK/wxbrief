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

from corpus import awc_rows, read_raw, report_files
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from rich.console import Console

from wxbrief.decode.metar import parse_metar
from wxbrief.decode.units import UnitsMode
from wxbrief.i18n import Translator
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


def test_corpus_is_large_enough_to_mutate() -> None:
    assert len(CORPUS) > 500


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
    ]
    started = time.perf_counter()
    for raw in nasty:
        check(raw)
    assert time.perf_counter() - started < 20
