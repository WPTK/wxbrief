"""Sky condition: layers (``OVC003``, ``SCT060CB``, ``VV002``), clear-sky codes and ``///`` placeholders."""

from __future__ import annotations

import re

from wxbrief.decode.model import CloudLayer, SemanticKind
from wxbrief.decode.tables import CLEAR_SKY_CODES, CLOUD_TYPE_CODES, SKY_COVER_CODES
from wxbrief.decode.tokens import Cursor
from wxbrief.decode.units import Distance, DistanceUnit

_LAYER = re.compile(r"^(?P<cover>FEW|SCT|BKN|OVC|VV|///)(?P<height>\d{3}|///)(?P<type>CB|TCU|///)?$")


def parse_sky(cur: Cursor) -> CloudLayer | None:
    token = cur.peek()
    if token is None:
        return None
    clear = SKY_COVER_CODES.get(token.text)
    if clear is not None and clear in CLEAR_SKY_CODES:
        cur.take(SemanticKind.SKY)
        return CloudLayer(clear)
    match = _LAYER.match(token.text)
    if match is None:
        return None
    cover = SKY_COVER_CODES[match.group("cover")]
    height = match.group("height")
    base = None if height == "///" else Distance(int(height) * 100, DistanceUnit.FT)
    cloud_type = CLOUD_TYPE_CODES.get(match.group("type") or "")
    cur.take(SemanticKind.SKY)
    return CloudLayer(cover, base, cloud_type)
