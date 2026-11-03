"""Headwind and crosswind components on a runway."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

_DESIGNATOR = re.compile(r"^(\d{1,2})[LRCW]?$")  # W: water runway


@dataclass(frozen=True, slots=True)
class WindComponents:
    """Knots (or whatever unit the speed came in). Crosswind is positive from the right, negative from the left;
    headwind is negative for a tailwind. The gust figures are ``None`` when no gust is reported."""

    headwind: float
    crosswind: float
    gust_headwind: float | None = None
    gust_crosswind: float | None = None


def _clean(value: float) -> float:
    """Rounded to 1e-9 so 180 degrees off never gives ``-0.0`` or a 1e-15 crosswind."""
    return round(value, 9) + 0.0


def _split(direction: float, speed: float, runway_deg: float) -> tuple[float, float]:
    """``(headwind, crosswind)`` for wind *from* ``direction``: speed * cos(angle) and speed * sin(angle), where
    the angle is the wind direction clockwise of the runway heading."""
    angle = math.radians(direction - runway_deg)
    return _clean(speed * math.cos(angle)), _clean(speed * math.sin(angle))


def wind_components(
    direction: float | None,
    speed: float | None,
    runway_deg: float | None,
    gust: float | None = None,
    variable: bool = False,
    variation_deg: float = 0.0,
) -> WindComponents | None:
    """Components of a surface wind on a runway of heading ``runway_deg``.

    METAR winds are true north and runway numbers are magnetic. Pass the local magnetic variation as
    ``variation_deg``, east positive and west negative (12 W is ``-12``): the runway's true heading is then
    ``runway_deg + variation_deg``. The default 0 treats both as the same north.

    ``None`` when the speed or runway is unknown, or the direction is unknown (missing, or ``variable`` for VRB)
    and the wind is not calm; a VRB wind has no single crosswind. A calm wind (speed 0) is all zeros, gust
    ignored. Gust components use the same direction; a gust below the steady speed is ignored as malformed.
    """
    if speed is None or not math.isfinite(speed) or speed < 0 or runway_deg is None or not math.isfinite(runway_deg):
        return None
    if not math.isfinite(variation_deg):
        return None
    if speed == 0:
        return WindComponents(0.0, 0.0)
    if variable or direction is None or not math.isfinite(direction):
        return None
    runway_deg += variation_deg
    head, cross = _split(direction, speed, runway_deg)
    if gust is None or not math.isfinite(gust) or gust < speed:
        return WindComponents(head, cross)
    gust_head, gust_cross = _split(direction, gust, runway_deg)
    return WindComponents(head, cross, gust_head, gust_cross)


def runway_heading(designator: str) -> int | None:
    """Magnetic heading in degrees of a runway designator (``27L``, ``9`` and ``09`` give 90 or 270); ``None`` if
    the number is not 1 to 36 or the suffix is not L, R, C or W."""
    match = _DESIGNATOR.match(designator.strip().upper())
    if match is None or not 1 <= int(match[1]) <= 36:
        return None
    return int(match[1]) * 10
