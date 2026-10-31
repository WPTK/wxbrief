"""Runway state (contamination) groups, in the forms still found in ICAO reports.

* ``R24L/290255``  runway designator, then deposit, extent, depth and braking (six characters)
* ``R06R/CLRD62``  contamination cleared, braking 0.62 (``CLRD//``: braking not reported)
* ``88290192``     the older eight-digit form: two-digit runway (88 all, 99 repeat, 51 to 86 right runway) + six
* ``R/SNOCLO``, ``SNOCLO``  aerodrome closed by snow

The six characters are ``E`` deposit, ``R`` extent, ``DD`` depth and ``BB`` braking (WMO code tables 0919, 0519,
1079 and 0366); ``/`` marks a value not reported. Not looked for in US-flavour reports (see ``tail.py``).
"""

from __future__ import annotations

import re

from wxbrief.decode.model import (
    BrakingAction,
    RunwayBraking,
    RunwayDeposit,
    RunwayDepth,
    RunwayDepthKind,
    RunwayExtent,
    RunwayState,
    SemanticKind,
)
from wxbrief.decode.tokens import Cursor

_R_FORM = re.compile(r"^R(?P<rwy>\d{2}[LCR]?)/(?:(?P<body>[\d/]{6})|CLRD(?P<cleared>\d{2}|//))$")
_EIGHT_DIGIT = re.compile(r"^(?P<rwy>\d{2})(?P<body>[\d/]{6})$")
_SNOCLO = re.compile(r"^(?:R/)?SNOCLO$")

ALL_RUNWAYS = "88"
REPEATED = "99"
_EXTENTS = {
    "0": RunwayExtent.NONE,
    "1": RunwayExtent.UP_TO_10,
    "2": RunwayExtent.FROM_11_TO_25,
    "5": RunwayExtent.FROM_26_TO_50,
    "9": RunwayExtent.FROM_51_TO_100,
}
_ACTIONS = {
    91: BrakingAction.POOR,
    92: BrakingAction.MEDIUM_POOR,
    93: BrakingAction.MEDIUM,
    94: BrakingAction.MEDIUM_GOOD,
    95: BrakingAction.GOOD,
}
_UNREPORTED = "//"


def is_runway_state(text: str) -> bool:
    """Whether a token spells a runway state group."""
    return bool(_R_FORM.match(text) or _EIGHT_DIGIT.match(text) or _SNOCLO.match(text))


def decode_depth(code: str) -> RunwayDepth | None:
    """Two characters of depth: ``00`` under 1 mm, ``01``-``90`` mm, ``92``-``97`` 10-35 cm, ``98`` 40 cm or more."""
    if code == _UNREPORTED:
        return RunwayDepth(RunwayDepthKind.NOT_SIGNIFICANT)
    if not code.isdigit():
        return None
    value = int(code)
    if value == 0:
        return RunwayDepth(RunwayDepthKind.LESS_THAN_1)
    if value <= 90:
        return RunwayDepth(RunwayDepthKind.MILLIMETERS, value)
    if value == 91:
        return RunwayDepth(RunwayDepthKind.RESERVED)
    if value <= 97:
        return RunwayDepth(RunwayDepthKind.MILLIMETERS, (value - 92) * 50 + 100)  # 92 -> 100 mm ... 97 -> 350 mm
    if value == 98:
        return RunwayDepth(RunwayDepthKind.AT_LEAST, 400)
    return RunwayDepth(RunwayDepthKind.NOT_OPERATIONAL)


def decode_braking(code: str) -> RunwayBraking | None:
    """Two characters of friction: a coefficient ``00``-``90``, an action ``91``-``95``, ``99`` unreliable."""
    if not code.isdigit():
        return None
    value = int(code)
    if value <= 90:
        return RunwayBraking(coefficient=value / 100)
    if value in _ACTIONS:
        return RunwayBraking(action=_ACTIONS[value])
    if value == 99:
        return RunwayBraking(unreliable=True)
    return None


def _designator(rwy: str) -> tuple[str | None, bool, bool]:
    """``(runway, all_runways, repeated)`` for the runway part of a group."""
    if rwy == ALL_RUNWAYS:
        return None, True, False
    if rwy == REPEATED:
        return None, False, True
    return rwy, False, False


def _eight_digit_runway(rr: str) -> str | None:
    """The runway of the eight-digit form: 01-36, or 51-86 for the right-hand runway (``51`` is ``01R``)."""
    value = int(rr)
    if 51 <= value <= 86:
        return f"{value - 50:02d}R"
    if 1 <= value <= 36:
        return rr
    return None


def _from_body(body: str, runway: str | None, *, all_runways: bool, repeated: bool) -> RunwayState:
    deposit = RunwayDeposit(body[0]) if body[0].isdigit() else None
    extent = None
    if body[1] != "/":
        extent = _EXTENTS.get(body[1], RunwayExtent.OTHER)
    return RunwayState(
        runway=runway,
        all_runways=all_runways,
        repeated=repeated,
        deposit=deposit,
        extent=extent,
        depth=decode_depth(body[2:4]),
        braking=decode_braking(body[4:6]),
    )


def parse_runway_state(cur: Cursor) -> RunwayState | None:
    token = cur.peek()
    if token is None:
        return None
    text = token.text

    if _SNOCLO.match(text):
        cur.take(SemanticKind.RUNWAY_STATE)
        return RunwayState(snoclo=True, all_runways=text.startswith("R/"))

    match = _R_FORM.match(text)
    if match is not None:
        runway, every, repeated = _designator(match.group("rwy"))
        cur.take(SemanticKind.RUNWAY_STATE)
        if match.group("body") is not None:
            return _from_body(match.group("body"), runway, all_runways=every, repeated=repeated)
        return RunwayState(
            runway=runway,
            all_runways=every,
            repeated=repeated,
            cleared=True,
            braking=decode_braking(match.group("cleared")),
        )

    match = _EIGHT_DIGIT.match(text)
    if match is not None:
        rr = match.group("rwy")
        runway, every, repeated = _designator(rr)
        if runway is not None:
            runway = _eight_digit_runway(rr)
            if runway is None:
                return None
        cur.take(SemanticKind.RUNWAY_STATE)
        return _from_body(match.group("body"), runway, all_runways=every, repeated=repeated)
    return None
