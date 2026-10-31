"""Recent weather: ``RE`` plus a weather group (``RERA``, ``RETSRA``, ``RESHSN``, ``REFZRA``, ``REBLSN``).

It reports weather since the previous report that has ended; it is a standard ICAO group, not an anomaly. The part
after ``RE`` is read as a present-weather group (optional intensity, descriptor, phenomena) in two-letter steps, so
there is no repeat for a regex to backtrack over.
"""

from __future__ import annotations

from wxbrief.decode.model import Descriptor, Intensity, Phenomenon, RecentWeather, SemanticKind, WeatherGroup
from wxbrief.decode.tables import DESCRIPTOR_CODES, PHENOMENON_CODES
from wxbrief.decode.tokens import Cursor

_INTENSITY = {"-": Intensity.LIGHT, "+": Intensity.HEAVY}
_ALONE = frozenset({Descriptor.TS, Descriptor.SH})  # descriptors that name an event by themselves


def recent_weather_of(text: str) -> RecentWeather | None:
    """The recent weather a token spells, or ``None`` if it is not an ``RE`` group."""
    if not text.startswith("RE") or len(text) < 4:
        return None
    body = text[2:]
    intensity = Intensity.MODERATE
    if body[0] in _INTENSITY:
        intensity = _INTENSITY[body[0]]
        body = body[1:]
    if len(body) % 2 or not body:
        return None
    chunks = [body[i : i + 2] for i in range(0, len(body), 2)]
    descriptor: Descriptor | None = None
    if chunks[0] in DESCRIPTOR_CODES:
        descriptor = DESCRIPTOR_CODES[chunks[0]]
        chunks = chunks[1:]
    if any(chunk not in PHENOMENON_CODES for chunk in chunks):
        return None
    phenomena: tuple[Phenomenon, ...] = tuple(PHENOMENON_CODES[chunk] for chunk in chunks)
    if not phenomena and descriptor not in _ALONE:
        return None
    return RecentWeather(WeatherGroup(intensity=intensity, descriptor=descriptor, phenomena=phenomena))


def parse_recent_weather(cur: Cursor) -> RecentWeather | None:
    token = cur.peek()
    if token is None:
        return None
    recent = recent_weather_of(token.text)
    if recent is None:
        return None
    cur.take(SemanticKind.RECENT_WEATHER)
    return recent
