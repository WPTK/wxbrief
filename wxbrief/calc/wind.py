"""Headwind and crosswind components on a runway."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

_DESIGNATOR = re.compile(r"^(0[1-9]|[12]\d|3[0-6])[LRC]?$")


@dataclass(frozen=True, slots=True)
class WindComponents:
    """Knots (or whatever unit the speed came in). Crosswind is positive from the right, negative from the left;
    headwind is negative for a tailwind. The gust figures are ``None`` when no gust is reported."""

    headwind: float
    crosswind: float
    gust_headwind: float | None = None
    gust_crosswind: float | None = None


def _split(direction: float, speed: float, runway_deg: float) -> tuple[float, float]:
    """``(headwind, crosswind)`` for wind *from* ``direction``: speed * cos(angle) and speed * sin(angle), where
    the angle is the wind direction clockwise of the runway heading."""
    angle = math.radians(direction - runway_deg)
    return speed * math.cos(angle), speed * math.sin(angle)


def wind_components(
    direction: float | None,
    speed: float | None,
    runway_deg: float,
    gust: float | None = None,
    variable: bool = False,
) -> WindComponents | None:
    """Components of a surface wind on a runway of heading ``runway_deg``.

    Wind and runway must use the same north: METAR winds are true, runway numbers are magnetic. ``None`` when the
    speed is unknown, or the direction is (VRB or missing) and the wind is not calm. A calm wind is all zeros.
    Gust components use the same direction; a gust below the steady speed is ignored as malformed.
    """
    if speed is None or not math.isfinite(speed) or speed < 0 or not math.isfinite(runway_deg):
        return None
    if speed == 0:
        return WindComponents(0.0, 0.0)
    if variable or direction is None or not math.isfinite(direction):
        return None
    head, cross = _split(direction, speed, runway_deg)
    if gust is None or not math.isfinite(gust) or gust < speed:
        return WindComponents(head, cross)
    gust_head, gust_cross = _split(direction, gust, runway_deg)
    return WindComponents(head, cross, gust_head, gust_cross)


def runway_heading(designator: str) -> int | None:
    """Magnetic heading in degrees of a runway designator (``27L`` is 270, ``09`` is 90); ``None`` if invalid."""
    text = designator.strip().upper()
    match = _DESIGNATOR.match(text)
    return None if match is None else int(match[1]) * 10
