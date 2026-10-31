"""Temperature and dew point in whole degrees Celsius (``15/13``, ``M05/M10``, ``12/M00``, ``15//``)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from wxbrief.decode.model import SemanticKind
from wxbrief.decode.tokens import Cursor
from wxbrief.decode.units import Temperature, TemperatureUnit

_TEMPDEW = re.compile(r"^(?P<t>M?\d{2}|//)/(?P<d>M?\d{2}|//)?$")


@dataclass(frozen=True)
class TempDew:
    temperature: Temperature | None
    dewpoint: Temperature | None


def _celsius(text: str | None) -> Temperature | None:
    if not text or text == "//":
        return None
    value = int(text.removeprefix("M"))
    return Temperature(-value if text.startswith("M") else value, TemperatureUnit.C)


def parse_tempdew(cur: Cursor) -> TempDew | None:
    token = cur.peek()
    if token is None:
        return None
    match = _TEMPDEW.match(token.text)
    if match is None:
        return None
    cur.take(SemanticKind.TEMPERATURE)
    return TempDew(_celsius(match.group("t")), _celsius(match.group("d")))
