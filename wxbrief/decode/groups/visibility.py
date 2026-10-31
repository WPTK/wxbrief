"""Prevailing visibility.

Statute miles (``3/4SM``, ``1 1/2SM``, ``M1/4SM``, ``P6SM``), metres (``9999``, ``1200NW``, ``0600NDV``),
kilometres (``10KM``) and ``CAVOK``.
"""

from __future__ import annotations

import re

from wxbrief.decode.model import DirectionalVisibility, SemanticKind, Visibility, VisPrefix
from wxbrief.decode.tokens import Cursor
from wxbrief.decode.units import Distance, DistanceUnit

_SM = re.compile(r"^(?P<prefix>[PM])?(?P<num>\d{1,2})(?:/(?P<den>\d{1,2}))?SM$")
_FRACTION_SM = re.compile(r"^(?P<num>\d{1,2})/(?P<den>\d{1,2})SM$")
_WHOLE = re.compile(r"^\d{1,2}$")
_FRACTION = re.compile(r"^(?P<num>\d{1,2})/(?P<den>\d{1,2})$")
_METERS = re.compile(r"^(?P<prefix>M)?(?P<m>\d{4})(?P<ndv>NDV)?$")
_KM = re.compile(r"^(?P<km>\d{1,2})KM$")
_DIRECTIONAL = re.compile(r"^(?P<m>\d{4})(?P<dir>NE|NW|SE|SW|N|E|S|W)?$")
_PREFIXES = {"P": VisPrefix.GREATER_THAN, "M": VisPrefix.LESS_THAN}


def _fraction(num: str, den: str | None) -> float | None:
    if den is None:
        return float(int(num))
    denominator = int(den)
    if denominator == 0:
        return None
    return int(num) / denominator


def _minimum_tail(cur: Cursor, ndv: bool, prevailing: int) -> tuple[tuple[DirectionalVisibility, ...], bool]:
    """Consume ``NDV`` and the minimum visibilities that follow a metric prevailing visibility.

    A minimum is ``1200NW`` (with its bearing) or, from automated stations, a bare ``1200`` lower than the
    prevailing value (``0350 0300``).
    """
    found: list[DirectionalVisibility] = []
    while (token := cur.peek()) is not None:
        match = _DIRECTIONAL.match(token.text)
        if match is not None and (match.group("dir") or int(match.group("m")) < prevailing):
            cur.take(SemanticKind.VISIBILITY)
            found.append(DirectionalVisibility(Distance(int(match.group("m")), DistanceUnit.M), match.group("dir")))
        elif token.text == "NDV":
            cur.take(SemanticKind.VISIBILITY)
            ndv = True
        else:
            break
    return tuple(found), ndv


def _spaced_miles(cur: Cursor) -> Visibility | None:
    """Miles written with a space before the unit (``3/4 SM``, ``M1/4 SM``, ``1 1/2 SM``).

    FMH-1 writes ``3/4SM``; some sources and hand-typed reports separate the unit, and the three tokens would
    otherwise be unrecognised groups.
    """
    first, second, third = cur.peek(), cur.peek(1), cur.peek(2)
    if first is None or second is None:
        return None
    if second.text == "SM":
        match = _SM.match(first.text + "SM")
        if match is None:
            return None
        value = _fraction(match.group("num"), match.group("den"))
        if value is None:
            return None
        cur.take(SemanticKind.VISIBILITY)
        cur.take(SemanticKind.VISIBILITY)
        return Visibility(Distance(value, DistanceUnit.SM), _PREFIXES.get(match.group("prefix") or ""))
    fraction = _FRACTION.match(second.text)
    if _WHOLE.match(first.text) and fraction is not None and third is not None and third.text == "SM":
        part = _fraction(fraction.group("num"), fraction.group("den"))
        if part is None:
            return None
        for _ in range(3):
            cur.take(SemanticKind.VISIBILITY)
        return Visibility(Distance(int(first.text) + part, DistanceUnit.SM))
    return None


def parse_visibility(cur: Cursor) -> Visibility | None:
    token = cur.peek()
    if token is None:
        return None
    text = token.text

    if text == "CAVOK":
        cur.take(SemanticKind.VISIBILITY)
        return Visibility(cavok=True)

    if text == "////":
        cur.take(SemanticKind.VISIBILITY)
        return Visibility(not_reported=True)

    spaced = _spaced_miles(cur)
    if spaced is not None:
        return spaced

    # Whole miles followed by a fraction: "1 1/2SM".
    if _WHOLE.match(text):
        following = cur.peek(1)
        frac = _FRACTION_SM.match(following.text) if following is not None else None
        if frac is None:
            return None
        part = _fraction(frac.group("num"), frac.group("den"))
        if part is None:
            return None
        cur.take(SemanticKind.VISIBILITY)
        cur.take(SemanticKind.VISIBILITY)
        return Visibility(Distance(int(text) + part, DistanceUnit.SM))

    match = _SM.match(text)
    if match is not None:
        value = _fraction(match.group("num"), match.group("den"))
        if value is None:
            return None
        cur.take(SemanticKind.VISIBILITY)
        prefix = _PREFIXES.get(match.group("prefix") or "")
        return Visibility(Distance(value, DistanceUnit.SM), prefix)

    match = _KM.match(text)
    if match is not None:
        cur.take(SemanticKind.VISIBILITY)
        return Visibility(Distance(int(match.group("km")), DistanceUnit.KM))

    match = _METERS.match(text)
    if match is not None:
        meters = int(match.group("m"))
        cur.take(SemanticKind.VISIBILITY)
        directional, ndv = _minimum_tail(cur, bool(match.group("ndv")), meters)
        if meters == 9999:
            return Visibility(Distance(10000, DistanceUnit.M), unlimited=True, ndv=ndv, directional=directional)
        if meters == 0:
            return Visibility(Distance(50, DistanceUnit.M), VisPrefix.LESS_THAN, ndv=ndv, directional=directional)
        prefix = _PREFIXES.get(match.group("prefix") or "")  # ``M0200``: less than 200 m, as some sources write it
        return Visibility(Distance(meters, DistanceUnit.M), prefix, ndv=ndv, directional=directional)

    return None
