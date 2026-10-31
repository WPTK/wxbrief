"""Wind shear on the runways: ``WS ALL RWY``, ``WS R24L``, ``WS RWY24L``, ``WS RWY 24L``.

``WS`` is followed by ``ALL RWY`` or by one or more runway designators; each designator is one ``WindShearRunway``.
A bare ``WS`` is not a group.
"""

from __future__ import annotations

import re

from wxbrief.decode.model import SemanticKind, WindShearRunway
from wxbrief.decode.tokens import Cursor

_RUNWAY = re.compile(r"^(?:RWY|R)?(?P<rwy>\d{2}[LCR]?)$")


def parse_wind_shear(cur: Cursor) -> tuple[WindShearRunway, ...] | None:
    first = cur.peek()
    if first is None or first.text != "WS":
        return None
    mark = cur.mark()
    cur.take(SemanticKind.WIND_SHEAR)
    found: list[WindShearRunway] = []
    while (token := cur.peek()) is not None:
        if token.text == "ALL":
            cur.take(SemanticKind.WIND_SHEAR)
            following = cur.peek()
            if following is not None and following.text == "RWY":
                cur.take(SemanticKind.WIND_SHEAR)
            found.append(WindShearRunway(all_runways=True))
            continue
        if token.text == "RWY":
            # "RWY 24L": the designator is the next token.
            following = cur.peek(1)
            designator = _RUNWAY.match(following.text) if following is not None else None
            if designator is None:
                break
            cur.take(SemanticKind.WIND_SHEAR)
            cur.take(SemanticKind.WIND_SHEAR)
            found.append(WindShearRunway(runway=designator.group("rwy")))
            continue
        designator = _RUNWAY.match(token.text)
        if designator is None:
            break
        cur.take(SemanticKind.WIND_SHEAR)
        found.append(WindShearRunway(runway=designator.group("rwy")))
    if not found:
        cur.reset(mark)
        return None
    return tuple(found)
