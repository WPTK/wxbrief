"""Syntax highlighting as data: tokens in, ``HighlightSpan`` out. Pure; no colours, no UI imports.

The Rich renderer and the Textual widgets both map ``kind`` to a style through ``style_name``/``STYLE_KEYS``, so the
CLI and the TUI colour the same groups the same way.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from wxbrief.decode.model import ChangeType, SemanticKind, Taf
from wxbrief.decode.tokens import Token

# Style key per kind; the full style name is ``wx.<key>`` (and ``$wx-<key>`` as a Textual CSS variable).
STYLE_KEYS: dict[SemanticKind, str] = {
    SemanticKind.TYPE: "station",
    SemanticKind.STATION: "station",
    SemanticKind.TIME: "time",
    SemanticKind.MODIFIER: "remark",
    SemanticKind.WIND: "wind",
    SemanticKind.WIND_VARIATION: "wind",
    SemanticKind.VISIBILITY: "vis",
    SemanticKind.RVR: "vis",
    SemanticKind.WEATHER: "wx",
    SemanticKind.SKY: "cloud",
    SemanticKind.TEMPERATURE: "temp",
    SemanticKind.PRESSURE: "pressure",
    SemanticKind.RECENT_WEATHER: "wx",
    SemanticKind.WIND_SHEAR: "wind",
    SemanticKind.SEA_STATE: "remark",
    SemanticKind.RUNWAY_STATE: "vis",
    SemanticKind.TREND: "trend",
    SemanticKind.COLOR_STATE: "color-state",
    SemanticKind.HAZARD: "wx",
    SemanticKind.REMARK: "remark",
    SemanticKind.TERMINATOR: "remark",
    SemanticKind.UNKNOWN: "unknown",
}


@dataclass(frozen=True)
class HighlightSpan:
    """``raw[start:end]`` is one token of the given kind."""

    start: int
    end: int
    kind: SemanticKind


def highlight_spans(tokens: Iterable[Token]) -> list[HighlightSpan]:
    """One span per token, in order. Whitespace between tokens belongs to no span."""
    return [HighlightSpan(token.start, token.end, token.kind) for token in tokens]


@dataclass(frozen=True)
class PeriodSpan:
    """``raw[start:end]`` is the text of one forecast period of a TAF (``index`` points into ``Taf.periods``)."""

    start: int
    end: int
    index: int
    change: ChangeType


def period_spans(taf: Taf) -> list[PeriodSpan]:
    """The stretch of the raw TAF each forecast period covers, for hover linking and block highlighting."""
    return [
        PeriodSpan(period.tokens[0].start, period.tokens[-1].end, index, period.change)
        for index, period in enumerate(taf.periods)
        if period.tokens
    ]


def style_key(kind: SemanticKind) -> str:
    """The short style key for ``kind`` (``wind``, ``vis``, ``color-state`` ...)."""
    return STYLE_KEYS[kind]


def style_name(kind: SemanticKind) -> str:
    """The dotted Rich style name for ``kind`` (``wx.wind``)."""
    return f"wx.{STYLE_KEYS[kind]}"
