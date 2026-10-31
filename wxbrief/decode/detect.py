"""Report flavor detection.

Flavor is scored from the tokens themselves (statute miles, ``A####`` against ``Q####``, metres, ``CAVOK``,
``MPS``, colour-state codes), never from the station prefix: Mexican, Canadian and military reports mix conventions.
It is used to disambiguate, e.g. the runway-state group is only looked for in non-US reports.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from wxbrief.decode.groups.colorstate import color_state_of
from wxbrief.decode.model import Flavor
from wxbrief.decode.tokens import Token

_US_SIGNALS = (
    re.compile(r"^[PM]?\d{1,2}(?:/\d{1,2})?SM$"),  # statute-mile visibility
    re.compile(r"^A\d{4}$"),  # altimeter setting
    re.compile(r"^R\d{2}[LCR]?/.*FT(?:/?[UDN])?$"),  # RVR in feet
)
_STATION_TYPE = re.compile(r"^AO[12]$")  # automated station type, found in the remarks
_ICAO_SIGNALS = (
    re.compile(r"^Q\d{4}$"),  # QNH in hectopascals
    re.compile(r"^\d{4}(?:N|NE|E|SE|S|SW|W|NW|NDV)?$"),  # visibility in metres
    re.compile(r"^CAVOK$"),
    re.compile(r"^\S*(?:MPS|KMH)$"),  # wind in m/s or km/h
    re.compile(r"^(?:NOSIG|BECMG|TEMPO|NSC|NCD)$"),
    re.compile(r"^R\d{2}[LCR]?/[PM]?\d{4}(?:V[PM]?\d{4})?[UDN]?$"),  # RVR in metres
)


@dataclass(frozen=True)
class Detection:
    flavor: Flavor
    military: bool


def detect_flavor(tokens: Sequence[Token]) -> Detection:
    """Score ``tokens`` for US and ICAO conventions; colour-state codes also mark a military report."""
    us = icao = False
    military = False
    in_remarks = False
    for token in tokens:
        text = token.text
        if text == "RMK":
            in_remarks = True
            continue
        if in_remarks:
            # Remarks are free-form; only the station-type groups say anything about the convention.
            if _STATION_TYPE.match(text):
                us = True
            continue
        if any(signal.match(text) for signal in _US_SIGNALS):
            us = True
        if any(signal.match(text) for signal in _ICAO_SIGNALS):
            icao = True
        state = color_state_of(text)
        if state is not None and state.code is not None:  # not a bare BLACK, not "///"
            military = True
            icao = True
    if us and icao:
        flavor = Flavor.MIXED
    elif us:
        flavor = Flavor.US
    elif icao:
        flavor = Flavor.ICAO
    else:
        flavor = Flavor.UNKNOWN
    return Detection(flavor, military)
