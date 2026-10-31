"""The groups between the pressure and ``RMK`` (trends, colour states, runway state and the rest).

``parse_tail_group`` looks at the token under the cursor, decodes one group with the matching parser and returns it
in a ``TailResult`` (``None``, with nothing consumed, if the token starts no tail group). The groups and how their
tokens are tagged:

* ``NOSIG``                      -> one ``TREND`` token.
* ``BECMG``/``TEMPO`` + body     -> the keyword and its ``FM``/``TL``/``AT`` times are ``TREND``; the body elements get
  their own kinds (``WIND``, ``VISIBILITY``, ``WEATHER``, ``SKY``, ``COLOR_STATE``); a token the body cannot place is
  ``UNKNOWN``.
* ``BLU``, ``YLO2``, ``BLACKRED``, ``BLU TEMPO YLO`` -> ``COLOR_STATE`` (a trend keyword inside the group is ``TREND``).
* ``RERA``, ``RETSRA`` ...       -> ``RECENT_WEATHER``.
* ``WS ALL RWY``, ``WS R24L``    -> ``WIND_SHEAR`` over the keyword and its runway tokens.
* ``W15/S3``                     -> ``SEA_STATE``.
* ``88290192``, ``R24L/290255``, ``R/SNOCLO`` (not in US-flavour reports) -> ``RUNWAY_STATE``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from wxbrief.decode.groups.colorstate import parse_color_state_group
from wxbrief.decode.groups.recentwx import parse_recent_weather, recent_weather_of
from wxbrief.decode.groups.runwaystate import is_runway_state, parse_runway_state
from wxbrief.decode.groups.seastate import parse_sea_state, sea_state_of
from wxbrief.decode.groups.trend import TREND_KEYWORDS, parse_trend
from wxbrief.decode.groups.windshear import parse_wind_shear
from wxbrief.decode.model import (
    ColorStateGroup,
    Flavor,
    RecentWeather,
    RunwayState,
    SeaState,
    SemanticKind,
    Trend,
    WindShearRunway,
)
from wxbrief.decode.tokens import Cursor, Token


@dataclass(frozen=True)
class TailResult:
    """One decoded tail group; exactly one of the value fields is set. ``kind`` is the kind of its first token."""

    kind: SemanticKind
    trend: Trend | None = None
    color_state: ColorStateGroup | None = None
    runway_state: RunwayState | None = None
    recent_weather: RecentWeather | None = None
    wind_shear: tuple[WindShearRunway, ...] = ()
    sea_state: SeaState | None = None


def _starts_other_group(token: Token, flavor: Flavor) -> bool:
    """Whether ``token`` begins a tail group that is not part of a trend body."""
    text = token.text
    return (
        text == "RMK"
        or text == "WS"
        or token.kind is SemanticKind.TERMINATOR
        or recent_weather_of(text) is not None
        or sea_state_of(text) is not None
        or (flavor is not Flavor.US and is_runway_state(text))
    )


def parse_tail_group(cur: Cursor, flavor: Flavor, observed: datetime | None = None) -> TailResult | None:
    """Decode the tail group at the cursor, consuming and tagging its tokens."""
    token = cur.peek()
    if token is None:
        return None

    # A colour group first: "TEMPO YLO" starts one, while "TEMPO 5000" starts a weather trend.
    if (colors := parse_color_state_group(cur)) is not None:
        return TailResult(SemanticKind.COLOR_STATE, color_state=colors)

    if token.text in TREND_KEYWORDS:
        trend = parse_trend(cur, observed, lambda tok: _starts_other_group(tok, flavor))
        return None if trend is None else TailResult(SemanticKind.TREND, trend=trend)

    if (shear := parse_wind_shear(cur)) is not None:
        return TailResult(SemanticKind.WIND_SHEAR, wind_shear=shear)

    if (recent := parse_recent_weather(cur)) is not None:
        return TailResult(SemanticKind.RECENT_WEATHER, recent_weather=recent)

    if (sea := parse_sea_state(cur)) is not None:
        return TailResult(SemanticKind.SEA_STATE, sea_state=sea)

    if flavor is not Flavor.US and (runway := parse_runway_state(cur)) is not None:
        return TailResult(SemanticKind.RUNWAY_STATE, runway_state=runway)

    return None
