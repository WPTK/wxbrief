"""Recognition of the groups between the pressure and ``RMK``.

Trends, colour states, runway state, recent weather, wind shear and sea state are only *recognised* here: their
tokens get the right ``SemanticKind`` (so highlighting works and no "unknown token" warning is raised) and the
text stays in the token list. Decoding them into model objects is the next session's job.

Layout the next session can rely on:

* ``NOSIG``                      -> one ``TREND`` token.
* ``BECMG``/``TEMPO`` + body     -> the keyword and every following token up to the next trend keyword, ``RMK`` or
  the end are ``TREND`` (a colour-state code inside the body is ``COLOR_STATE``).
* ``RERA``, ``RETSRA`` ...       -> ``RECENT_WEATHER``.
* ``WS ALL RWY``, ``WS R24L``    -> ``WIND_SHEAR`` over the keyword and its runway tokens.
* ``W15/S3``                     -> ``SEA_STATE``.
* ``BLU``, ``YLO2``, ``BLACK``   -> ``COLOR_STATE``.
* ``88290192``, ``R24L/290255``, ``R/SNOCLO`` (ICAO flavour only) -> ``RUNWAY_STATE``.
"""

from __future__ import annotations

import re

from wxbrief.decode.model import Flavor, SemanticKind
from wxbrief.decode.tables import COLOR_STATE_BASE_CODES, DESCRIPTOR_CODES, PHENOMENON_CODES
from wxbrief.decode.tokens import Cursor

TREND_KEYWORDS = frozenset({"NOSIG", "BECMG", "TEMPO"})

_DESC = "|".join(DESCRIPTOR_CODES)
_PHEN = "|".join(PHENOMENON_CODES)
# Two-letter codes only, so the repeat is unambiguous (no catastrophic backtracking on junk input).
_RECENT = re.compile(rf"^RE(?:[-+]?(?:{_DESC}|{_PHEN}))+$")
_SEA_STATE = re.compile(r"^W(?:M?\d{2}|//)/(?:S[\d/]|H\d{1,3}|H///)$")
_RUNWAY_STATE = re.compile(r"^(?:R\d{2}[LCR]?/(?:[\d/]{6}|CLRD(?:\d{2}|//))|R/SNOCLO|SNOCLO|\d{2}[\d/]{6})$")
_WIND_SHEAR_ARGS = re.compile(r"^(?:ALL|RWY|(?:RWY)?\d{2}[LCR]?|R\d{2}[LCR]?)$")


def is_color_state(text: str) -> bool:
    """Colour-state codes (``BLU``, ``YLO2``, ``RED`` ...), optionally ``BLACK``-prefixed or ``+``-suffixed."""
    if text == "BLACK":
        return True
    stem = text.removeprefix("BLACK").removesuffix("+")
    return stem in COLOR_STATE_BASE_CODES


def parse_tail_group(cur: Cursor, flavor: Flavor) -> SemanticKind | None:
    """Consume one tail group at the cursor and return its kind, or ``None`` if nothing here is a tail group."""
    token = cur.peek()
    if token is None:
        return None
    text = token.text

    if text == "NOSIG":
        cur.take(SemanticKind.TREND)
        return SemanticKind.TREND

    if text in ("BECMG", "TEMPO"):
        cur.take(SemanticKind.TREND)
        while (nxt := cur.peek()) is not None:
            if nxt.text == "RMK" or nxt.text in TREND_KEYWORDS or nxt.kind is SemanticKind.TERMINATOR:
                break
            cur.take(SemanticKind.COLOR_STATE if is_color_state(nxt.text) else SemanticKind.TREND)
        return SemanticKind.TREND

    if text == "WS":
        cur.take(SemanticKind.WIND_SHEAR)
        while (nxt := cur.peek()) is not None and _WIND_SHEAR_ARGS.match(nxt.text):
            cur.take(SemanticKind.WIND_SHEAR)
        return SemanticKind.WIND_SHEAR

    if _RECENT.match(text):
        cur.take(SemanticKind.RECENT_WEATHER)
        return SemanticKind.RECENT_WEATHER

    if _SEA_STATE.match(text):
        cur.take(SemanticKind.SEA_STATE)
        return SemanticKind.SEA_STATE

    if is_color_state(text):
        cur.take(SemanticKind.COLOR_STATE)
        return SemanticKind.COLOR_STATE

    if flavor is not Flavor.US and _RUNWAY_STATE.match(text):
        cur.take(SemanticKind.RUNWAY_STATE)
        return SemanticKind.RUNWAY_STATE

    return None
