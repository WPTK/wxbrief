"""Runway visual range.

Feet in US reports (``R35L/P6000FT``, ``R21/2000VP6000FT``), metres elsewhere (``R12/1000U``, ``R01L/0700N``).
Canadian reports put a slash before the trend (``R06L/2600FT/D``).
"""

from __future__ import annotations

import re

from wxbrief.decode.model import RVR, SemanticKind, VisPrefix
from wxbrief.decode.tables import RVR_TREND_CODES
from wxbrief.decode.tokens import Cursor
from wxbrief.decode.units import Distance, DistanceUnit

_RVR = re.compile(
    r"^R(?P<rwy>\d{2}[LCR]?)/(?:(?P<p1>[PM])?(?P<d1>\d{4})(?:V(?P<p2>[PM])?(?P<d2>\d{4}))?|/{4})"
    r"(?P<ft>FT)?(?:/(?=[UDN]$))?(?P<trend>[UDN])?$"
)
_PREFIXES = {"P": VisPrefix.GREATER_THAN, "M": VisPrefix.LESS_THAN}


def parse_rvr(cur: Cursor) -> RVR | None:
    token = cur.peek()
    if token is None:
        return None
    match = _RVR.match(token.text)
    if match is None:
        return None
    unit = DistanceUnit.FT if match.group("ft") else DistanceUnit.M
    low = Distance(int(match.group("d1")), unit) if match.group("d1") else None
    high = Distance(int(match.group("d2")), unit) if match.group("d2") else None
    trend = RVR_TREND_CODES.get(match.group("trend") or "")
    cur.take(SemanticKind.RVR)
    return RVR(
        runway=match.group("rwy"),
        distance=low,
        prefix=_PREFIXES.get(match.group("p1") or ""),
        variable_to=high,
        variable_to_prefix=_PREFIXES.get(match.group("p2") or ""),
        trend=trend,
    )
