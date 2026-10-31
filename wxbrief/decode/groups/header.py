"""Header groups: report type, station, day/time and modifiers."""

from __future__ import annotations

import re

from wxbrief.decode.model import Modifier, ReportType, SemanticKind
from wxbrief.decode.tables import MODIFIER_CODES
from wxbrief.decode.tokens import Cursor

_STATION = re.compile(r"^(?!AUTO$|COR$|NIL$)[A-Z][A-Z0-9]{3}$")
_TIME = re.compile(r"^(\d{2})(\d{2})(\d{2})Z$")


def parse_type(cur: Cursor) -> ReportType | None:
    """``METAR`` or ``SPECI``."""
    token = cur.peek()
    if token is None or token.text not in ("METAR", "SPECI"):
        return None
    cur.take(SemanticKind.TYPE)
    return ReportType(token.text)


def parse_station(cur: Cursor) -> str | None:
    """A four-character location indicator such as ``KDEN`` or ``K1G4``.

    Four letters and digits describe plenty of ordinary words, so the shape alone is not enough: the indicator must be
    followed by a day/time group, follow an explicit ``METAR``/``SPECI``, or be the only token.
    """
    token = cur.peek()
    if token is None or not _STATION.match(token.text):
        return None
    following = cur.peek(1)
    followed_by_time = following is not None and _TIME.match(following.text) is not None
    after_type = cur.pos > 0 and cur.kind_at(cur.pos - 1) is SemanticKind.TYPE
    if not (followed_by_time or after_type or len(cur) == 1):
        return None
    cur.take(SemanticKind.STATION)
    return token.text


def parse_time(cur: Cursor) -> tuple[int, int, int] | None:
    """``DDHHMMZ`` as raw ``(day, hour, minute)``; the caller resolves it against a reference date."""
    token = cur.peek()
    if token is None:
        return None
    match = _TIME.match(token.text)
    if match is None:
        return None
    cur.take(SemanticKind.TIME)
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def parse_modifier(cur: Cursor) -> Modifier | None:
    """``AUTO``, ``COR``, ``CCA``, ``NIL`` and friends."""
    token = cur.peek()
    if token is None:
        return None
    modifier = MODIFIER_CODES.get(token.text)
    if modifier is None:
        return None
    cur.take(SemanticKind.MODIFIER)
    return modifier
