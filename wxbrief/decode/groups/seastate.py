"""Sea state of offshore reports: ``W15/S3`` (water 15 °C, state of the sea 3), ``W15/H10`` (waves 1.0 m)."""

from __future__ import annotations

import re

from wxbrief.decode.model import SeaState, SemanticKind
from wxbrief.decode.tokens import Cursor
from wxbrief.decode.units import Temperature, TemperatureUnit

_SEA = re.compile(r"^W(?P<temp>M?\d{2}|//)/(?:S(?P<state>[\d/])|H(?P<height>\d{1,3}|///))$")


def sea_state_of(text: str) -> SeaState | None:
    match = _SEA.match(text)
    if match is None:
        return None
    raw = match.group("temp")
    temperature = None
    if raw != "//":
        value = int(raw.removeprefix("M"))
        temperature = Temperature(-value if raw.startswith("M") else value, TemperatureUnit.C)
    state = match.group("state")
    height = match.group("height")
    return SeaState(
        temperature=temperature,
        state=int(state) if state and state.isdigit() else None,
        wave_height_m=int(height) / 10 if height and height.isdigit() else None,
    )


def parse_sea_state(cur: Cursor) -> SeaState | None:
    token = cur.peek()
    if token is None:
        return None
    sea = sea_state_of(token.text)
    if sea is None:
        return None
    cur.take(SemanticKind.SEA_STATE)
    return sea
