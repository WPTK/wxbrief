"""Surface wind (``27015G25KT``, ``VRB03KT``, ``12012MPS``) and its direction variation (``180V240``)."""

from __future__ import annotations

import re

from wxbrief.decode.model import SemanticKind, Wind, WindVariation
from wxbrief.decode.tokens import Cursor
from wxbrief.decode.units import Speed, SpeedUnit

_WIND = re.compile(
    r"^(?P<dir>\d{3}|VRB|///)(?P<above>P|ABV)?(?P<spd>\d{2,3}|//)"
    r"(?:G(?P<gabove>P|ABV)?(?P<gst>\d{2,3}))?(?P<unit>KT|MPS|KMH)$"
)
_VARIATION = re.compile(r"^(\d{3})V(\d{3})$")
_UNITS = {"KT": SpeedUnit.KT, "MPS": SpeedUnit.MPS, "KMH": SpeedUnit.KMH}


def decode_wind(text: str) -> tuple[Wind | None, bool]:
    """The wind in ``text``, and whether its gust was dropped for not being above the mean wind."""
    match = _WIND.match(text)
    if match is None:
        return None, False
    direction: int | None = None
    variable = match.group("dir") == "VRB"
    if match.group("dir").isdigit():
        direction = int(match.group("dir"))
        if direction > 360:
            return None, False
    unit = _UNITS[match.group("unit")]
    speed = None if match.group("spd") == "//" else Speed(int(match.group("spd")), unit)
    gust = Speed(int(match.group("gst")), unit) if match.group("gst") else None
    ignored = (
        speed is not None
        and gust is not None
        and not (match.group("above") or match.group("gabove"))
        and gust.value <= speed.value
    )
    wind = Wind(
        direction,
        speed,
        None if ignored else gust,
        variable=variable,
        speed_above=bool(match.group("above")),
        gust_above=bool(match.group("gabove")),
    )
    return wind, ignored


def wind_kind(gust_ignored: bool) -> SemanticKind:
    """How to tag a wind token: a gust is a peak above the mean wind, so a dropped one leaves the group ``UNKNOWN``,
    which every caller reports as an unrecognised group."""
    return SemanticKind.UNKNOWN if gust_ignored else SemanticKind.WIND


def parse_wind(cur: Cursor) -> Wind | None:
    token = cur.peek()
    if token is None:
        return None
    wind, gust_ignored = decode_wind(token.text)
    if wind is None:
        return None
    cur.take(wind_kind(gust_ignored))
    return wind


def parse_wind_variation(cur: Cursor) -> WindVariation | None:
    token = cur.peek()
    if token is None:
        return None
    match = _VARIATION.match(token.text)
    if match is None:
        return None
    start, end = int(match.group(1)), int(match.group(2))
    if start > 360 or end > 360:
        return None
    cur.take(SemanticKind.WIND_VARIATION)
    return WindVariation(start, end)
