"""Present weather: intensity, descriptor and phenomena (``+TSRA``, ``-SHSN``, ``VCFG``, ``BR``), ``NSW``, ``//``."""

from __future__ import annotations

import re

from wxbrief.decode.model import Descriptor, Intensity, Phenomenon, SemanticKind, WeatherGroup
from wxbrief.decode.tables import DESCRIPTOR_CODES, PHENOMENON_CODES
from wxbrief.decode.tokens import Cursor

_DESCRIPTORS = "|".join(DESCRIPTOR_CODES)
_PHENOMENA = "|".join(PHENOMENON_CODES)
_WEATHER = re.compile(rf"^(?P<pre>[-+]|VC)?(?P<desc>{_DESCRIPTORS})?(?P<phen>(?:{_PHENOMENA})*)$")
_INTENSITY = {"-": Intensity.LIGHT, "+": Intensity.HEAVY}
# A descriptor may stand alone only when it names a weather event by itself (TS, VCSH).
_ALONE = frozenset({Descriptor.TS, Descriptor.SH})


def parse_weather(cur: Cursor) -> WeatherGroup | None:
    token = cur.peek()
    if token is None:
        return None
    text = token.text
    if text == "NSW":
        cur.take(SemanticKind.WEATHER)
        return WeatherGroup(nsw=True)
    if text == "//":
        cur.take(SemanticKind.WEATHER)
        return WeatherGroup(not_observed=True)
    match = _WEATHER.match(text)
    if match is None:
        return None
    desc = DESCRIPTOR_CODES.get(match.group("desc") or "")
    codes = match.group("phen")
    phenomena: tuple[Phenomenon, ...] = tuple(PHENOMENON_CODES[codes[i : i + 2]] for i in range(0, len(codes), 2))
    if not phenomena and desc not in _ALONE:
        return None
    prefix = match.group("pre") or ""
    cur.take(SemanticKind.WEATHER)
    return WeatherGroup(
        intensity=_INTENSITY.get(prefix, Intensity.MODERATE),
        descriptor=desc,
        phenomena=phenomena,
        vicinity=prefix == "VC",
    )
