"""Altimeter setting (``A3001``, inches of mercury) and QNH (``Q1013``, hectopascals)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from wxbrief.decode.model import SemanticKind
from wxbrief.decode.tokens import Cursor
from wxbrief.decode.units import Pressure, PressureUnit

_ALTIMETER = re.compile(r"^A(?P<v>\d{4}|////)$")
_QNH = re.compile(r"^Q(?P<v>\d{4}|////)$")
_QNH_INS = re.compile(r"^QNH(?P<v>\d{4})INS$")


@dataclass(frozen=True)
class PressureGroup:
    """A pressure group; ``value`` is ``None`` when the report marks it as not available (``Q////``)."""

    value: Pressure | None


def parse_pressure(cur: Cursor) -> PressureGroup | None:
    token = cur.peek()
    if token is None:
        return None
    match = _ALTIMETER.match(token.text)
    if match is not None:
        digits = match.group("v")
        value = None if digits == "////" else Pressure(int(digits) / 100, PressureUnit.INHG)
    elif (match := _QNH.match(token.text)) is not None:
        digits = match.group("v")
        value = None if digits == "////" else Pressure(int(digits), PressureUnit.HPA)
    elif (match := _QNH_INS.match(token.text)) is not None:
        value = Pressure(int(match.group("v")) / 100, PressureUnit.INHG)
    else:
        return None
    cur.take(SemanticKind.PRESSURE)
    return PressureGroup(value)
