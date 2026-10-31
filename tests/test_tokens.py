"""Tokenizer and cursor."""

from __future__ import annotations

import pytest

from wxbrief.decode.model import SemanticKind
from wxbrief.decode.tokens import Cursor, tokenize


def test_tokens_index_the_original_text() -> None:
    raw = "METAR  KDEN\t131453Z\n06007KT"
    tokens = tokenize(raw)
    assert [t.text for t in tokens] == ["METAR", "KDEN", "131453Z", "06007KT"]
    for token in tokens:
        assert raw[token.start : token.end].upper() == token.text


def test_text_is_uppercased_but_offsets_stay_in_the_original() -> None:
    raw = "metar kden 131453z"
    tokens = tokenize(raw)
    assert [t.text for t in tokens] == ["METAR", "KDEN", "131453Z"]
    assert raw[tokens[2].start : tokens[2].end] == "131453z"


def test_trailing_terminator_is_split_off() -> None:
    tokens = tokenize("A3001=")
    assert [(t.text, t.kind) for t in tokens] == [("A3001", SemanticKind.UNKNOWN), ("=", SemanticKind.TERMINATOR)]
    assert tokens[1].start == 5
    assert tokens[1].end == 6


def test_lone_terminators() -> None:
    tokens = tokenize("== =")
    assert [(t.text, t.kind) for t in tokens] == [("==", SemanticKind.TERMINATOR), ("=", SemanticKind.TERMINATOR)]


def test_empty_and_blank_input() -> None:
    assert tokenize("") == []
    assert tokenize(" \t\n ") == []


@pytest.mark.parametrize("raw", ["METAR KDEN 131453Z", "a=b", "x= y", "ßeta  straße", "=A", "==A=="])
def test_every_non_blank_character_is_covered_once(raw: str) -> None:
    tokens = tokenize(raw)
    covered = [i for token in tokens for i in range(token.start, token.end)]
    assert covered == [i for i, ch in enumerate(raw) if not ch.isspace()]


def test_cursor_take_peek_and_tagging() -> None:
    cur = Cursor(tokenize("A B C"))
    second = cur.peek(1)
    assert second is not None
    assert second.text == "B"
    assert cur.peek(5) is None
    first = cur.take(SemanticKind.STATION)
    assert first.text == "A"
    assert cur.pos == 1
    assert [t.kind for t in cur.tagged()] == [SemanticKind.STATION, SemanticKind.UNKNOWN, SemanticKind.UNKNOWN]


def test_cursor_reset_forgets_tags() -> None:
    cur = Cursor(tokenize("A B C"))
    mark = cur.mark()
    cur.take(SemanticKind.WIND)
    cur.take(SemanticKind.WIND)
    cur.reset(mark)
    assert cur.pos == 0
    assert all(t.kind is SemanticKind.UNKNOWN for t in cur.tagged())


def test_cursor_reset_keeps_terminator_kind() -> None:
    cur = Cursor(tokenize("A ="))
    mark = cur.mark()
    cur.take(SemanticKind.WIND)
    cur.take(SemanticKind.WIND)
    cur.reset(mark)
    assert cur.tagged()[1].kind is SemanticKind.TERMINATOR


def test_cursor_end() -> None:
    cur = Cursor(tokenize("A"))
    assert not cur.at_end
    cur.take()
    assert cur.at_end
    assert cur.peek() is None
    assert len(cur) == 1
