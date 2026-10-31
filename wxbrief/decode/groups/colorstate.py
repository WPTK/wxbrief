"""NATO colour-state groups of military reports: ``BLU``, ``BLU+``, ``YLO1 YLO1``, ``GRN WHT TEMPO GRN``, ``BLACKRED``.

A group is the current state followed by the forecast states: a bare code expects that state, ``BECMG``/``TEMPO``
before a code qualify it. A trend keyword only belongs to the group when a colour code follows it, so
``BLU TEMPO YLO`` is one group while ``BLU TEMPO 5000 -RA`` is a group and a weather trend.
"""

from __future__ import annotations

import re

from wxbrief.decode.model import ColorCode, ColorForecast, ColorState, ColorStateGroup, SemanticKind, TrendKind
from wxbrief.decode.tokens import Cursor

_COLOR = re.compile(r"^(?P<black>BLACK)?(?P<code>BLU|WHT|GRN|YLO[12]?|AMB|RED)?(?P<plus>\+)?$")
_CHANGE_KEYWORDS = {"BECMG": TrendKind.BECMG, "TEMPO": TrendKind.TEMPO}


def color_state_of(text: str) -> ColorState | None:
    """The colour state a token spells (``BLACKRED``, ``BLU+``, ``///``), or ``None`` if it is not one."""
    if text == "///":
        return ColorState(None, not_reported=True)
    match = _COLOR.match(text)
    if match is None:
        return None
    black = match.group("black") is not None
    code = ColorCode(match.group("code")) if match.group("code") else None
    plus = match.group("plus") is not None
    if code is None and (not black or plus):  # nothing but "+", or an empty match
        return None
    return ColorState(code, black=black, plus=plus)


def is_color_state(text: str) -> bool:
    """Colour-state codes (``BLU``, ``YLO2``, ``BLACKRED``, ``BLU+``) and ``///`` (not reported)."""
    return color_state_of(text) is not None


def _qualified(cur: Cursor) -> tuple[TrendKind, ColorState] | None:
    """``TEMPO YLO`` / ``BECMG AMB`` at the cursor, without consuming anything."""
    keyword = cur.peek()
    following = cur.peek(1)
    if keyword is None or following is None:
        return None
    change = _CHANGE_KEYWORDS.get(keyword.text)
    state = color_state_of(following.text)
    if change is None or state is None:
        return None
    return change, state


def parse_color_state_group(cur: Cursor) -> ColorStateGroup | None:
    """A colour-state group at the cursor, or ``None`` (nothing consumed) if the cursor is not at one."""
    first = cur.peek()
    if first is None:
        return None
    current = color_state_of(first.text)
    if current is not None:
        cur.take(SemanticKind.COLOR_STATE)
    elif _qualified(cur) is None:
        return None
    forecast: list[ColorForecast] = []
    while (token := cur.peek()) is not None:
        state = color_state_of(token.text)
        if state is not None:
            cur.take(SemanticKind.COLOR_STATE)
            forecast.append(ColorForecast(state))
            continue
        qualified = _qualified(cur)
        if qualified is None:
            break
        change, state = qualified
        cur.take(SemanticKind.TREND)
        cur.take(SemanticKind.COLOR_STATE)
        forecast.append(ColorForecast(state, change))
    return ColorStateGroup(current, tuple(forecast))
