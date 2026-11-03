"""Temperature / dew point spread, with the fog and icing alert at 3 C or less."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

ALERT_SPREAD_C = 3.0
_T_GROUP = re.compile(r"^T([01])(\d{3})(?:([01])(\d{3}))?$")


@dataclass(frozen=True, slots=True)
class Spread:
    spread_c: float  # temperature minus dew point, one decimal; negative when the report has dew point above air
    alert: bool  # spread <= 3 C: fog, low cloud or (near freezing) airframe icing is likely


def _known(value: float | None) -> bool:
    return value is not None and math.isfinite(value)


def temperature_spread(temperature_c: float | None, dewpoint_c: float | None) -> Spread | None:
    """The spread, or ``None`` when either value is missing. Rounded to tenths first so 3.0 C exactly alerts."""
    if temperature_c is None or dewpoint_c is None or not (_known(temperature_c) and _known(dewpoint_c)):
        return None
    spread = round(temperature_c - dewpoint_c, 1)
    return Spread(spread, spread <= ALERT_SPREAD_C)


def parse_t_group(group: str) -> tuple[float, float | None] | None:
    """Temperature and dew point in tenths of a degree from a METAR remark ``T01230108`` (12.3 and 10.8 C).

    The first digit of each half is the sign (1 is negative). A group with no dew point (``T0123``) gives ``None``
    for it; anything that is not a T-group gives ``None``.
    """
    match = _T_GROUP.match(group.strip().upper())
    if match is None:
        return None
    temp = int(match[2]) / 10 * (-1 if match[1] == "1" else 1)
    dew = None if match[3] is None else int(match[4]) / 10 * (-1 if match[3] == "1" else 1)
    return temp, dew
