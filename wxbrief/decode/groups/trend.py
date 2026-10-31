"""Landing-forecast trends: ``NOSIG``, and ``BECMG``/``TEMPO`` with time qualifiers and changed elements.

``BECMG FM1130 TL1230 0350`` is a lasting change from 11:30 until 12:30 to a visibility of 350 m;
``TEMPO TL0630 3000 TSRA`` a temporary fluctuation. A trend body is read left to right: time qualifiers (``FM``, ``TL``,
``AT``), then wind, visibility (or ``CAVOK``), weather (or ``NSW``), sky and colour state, each decoded with the
same parsers as the report body. The body ends at the next trend keyword, ``RMK``, the terminator or a token that
starts another tail group. A token the body cannot place stays ``UNKNOWN`` (the driver warns) and the body carries on.

``parse_trend_body`` is shared with the forecast parsers that read the same elements.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime

from wxbrief.decode.groups.colorstate import color_state_of
from wxbrief.decode.groups.sky import parse_sky
from wxbrief.decode.groups.visibility import parse_visibility
from wxbrief.decode.groups.weather import parse_weather
from wxbrief.decode.groups.wind import parse_wind
from wxbrief.decode.model import (
    CloudLayer,
    ColorState,
    ForecastElements,
    SemanticKind,
    Trend,
    TrendKind,
    TrendTime,
    TrendTimeKind,
    Visibility,
    WeatherGroup,
    Wind,
)
from wxbrief.decode.times import resolve_clock_time
from wxbrief.decode.tokens import Cursor, Token

TREND_KEYWORDS = frozenset(kind.value for kind in TrendKind)

_TIME = re.compile(r"^(?P<kind>FM|TL|AT)(?P<hour>\d{2})(?P<minute>\d{2})$")
_TIME_KINDS = {kind.value: kind for kind in TrendTimeKind}

StopTest = Callable[[Token], bool]


def parse_trend_time(cur: Cursor, observed: datetime | None) -> TrendTime | None:
    """``FM1130``, ``TL1230`` or ``AT1200`` at the cursor."""
    token = cur.peek()
    if token is None:
        return None
    match = _TIME.match(token.text)
    if match is None:
        return None
    hour, minute = int(match.group("hour")), int(match.group("minute"))
    if hour > 24 or minute > 59 or (hour == 24 and minute != 0):
        return None
    cur.take(SemanticKind.TREND)
    return TrendTime(_TIME_KINDS[match.group("kind")], hour, minute, resolve_clock_time(hour, minute, observed))


def parse_trend_body(
    cur: Cursor, observed: datetime | None, stop: StopTest
) -> tuple[tuple[TrendTime, ...], ForecastElements]:
    """Read time qualifiers and forecast elements until ``stop`` says a token is not part of the body."""
    times: list[TrendTime] = []
    wind: Wind | None = None
    visibility: Visibility | None = None
    weather: list[WeatherGroup] = []
    sky: list[CloudLayer] = []
    color: ColorState | None = None
    while (token := cur.peek()) is not None and not stop(token):
        moment = parse_trend_time(cur, observed)
        if moment is not None:
            times.append(moment)
            continue
        state = color_state_of(token.text)
        if state is not None:
            if color is None:
                cur.take(SemanticKind.COLOR_STATE)
                color = state
            else:
                cur.take(SemanticKind.UNKNOWN)  # a second colour state in one body
            continue
        if wind is None and (found_wind := parse_wind(cur)) is not None:
            wind = found_wind
        elif visibility is None and (found_visibility := parse_visibility(cur)) is not None:
            visibility = found_visibility
        elif (found_weather := parse_weather(cur)) is not None:
            weather.append(found_weather)
        elif (found_layer := parse_sky(cur)) is not None:
            sky.append(found_layer)
        else:
            cur.take(SemanticKind.UNKNOWN)
    elements = ForecastElements(wind, visibility, tuple(weather), tuple(sky), color)
    return tuple(times), elements


def parse_trend(cur: Cursor, observed: datetime | None, stop: StopTest) -> Trend | None:
    """A trend at the cursor: ``NOSIG``, or ``BECMG``/``TEMPO`` and its body."""
    token = cur.peek()
    if token is None or token.text not in TREND_KEYWORDS:
        return None
    kind = TrendKind(token.text)
    cur.take(SemanticKind.TREND)
    if kind is TrendKind.NOSIG:
        return Trend(kind)
    times, elements = parse_trend_body(cur, observed, lambda tok: stop(tok) or tok.text in TREND_KEYWORDS)
    return Trend(kind, times, elements)
