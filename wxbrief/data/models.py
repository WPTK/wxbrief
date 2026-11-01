"""Tolerant parsing of aviationweather.gov JSON into small frozen records.

AWC fields drift (``wdir`` is an int or ``"VRB"``, ``visib`` a number or ``"10+"``, ``obsTime`` epoch seconds), so every
field is read defensively: a wrong type becomes ``None`` and a record without its raw report is dropped. The raw report
is the truth that the decoder reads; the structured fields are only a cross-check and a fallback.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from wxbrief.decode.model import Modifier

_TAF_REMARK_MODIFIERS = {m.value: m for m in (Modifier.AMD, Modifier.COR, Modifier.CNL)}


def _str(value: object) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def _num(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        try:
            number = float(value)
        except OverflowError:
            return None
        return number if math.isfinite(number) else None
    return None


def _int(value: object) -> int | None:
    number = _num(value)
    return None if number is None else int(number)


def _epoch(value: object) -> datetime | None:
    seconds = _num(value)
    if seconds is None:
        return None
    try:
        return datetime.fromtimestamp(seconds, UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _iso(value: object) -> datetime | None:
    text = _str(value)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_visibility(value: object) -> tuple[float | None, bool]:
    """AWC ``visib`` as (statute miles, ``True`` when it is a lower bound such as ``"10+"``)."""
    if isinstance(value, str):
        text = value.strip()
        plus = text.endswith("+")
        try:
            return float(text.rstrip("+")), plus
        except ValueError:
            return None, False
    return _num(value), False


@dataclass(frozen=True, slots=True)
class AwcMetar:
    """One METAR or SPECI row from the AWC API."""

    icao: str
    raw: str
    observed: datetime | None
    name: str | None = None
    metar_type: str | None = None
    flight_category: str | None = None
    wind_direction: int | None = None
    wind_variable: bool = False
    wind_speed_kt: int | None = None
    visibility_sm: float | None = None
    visibility_is_minimum: bool = False
    temperature_c: float | None = None
    dewpoint_c: float | None = None
    altimeter_hpa: float | None = None
    lat: float | None = None
    lon: float | None = None
    elevation_m: float | None = None
    source: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)


@dataclass(frozen=True, slots=True)
class AwcTaf:
    """One TAF row from the AWC API."""

    icao: str
    raw: str
    issued: datetime | None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    name: str | None = None
    remarks: str | None = None  # AWC's own field: where it puts AMD, COR and CNL instead of rawTAF
    source: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def modifiers(self) -> tuple[Modifier, ...]:
        """The ``AMD``, ``COR`` and ``CNL`` words of ``remarks``, in order."""
        found = (_TAF_REMARK_MODIFIERS.get(word) for word in (self.remarks or "").upper().split())
        return tuple(dict.fromkeys(m for m in found if m is not None))


@dataclass(frozen=True, slots=True)
class AwcStation:
    """One station row from the AWC ``stationinfo`` endpoint."""

    icao: str
    name: str | None
    iata: str | None = None
    lat: float | None = None
    lon: float | None = None
    elevation_m: float | None = None
    state: str | None = None
    country: str | None = None
    site_types: tuple[str, ...] = ()


def parse_metar(item: object) -> AwcMetar | None:
    """One AWC METAR object, or ``None`` when it has no usable raw report or station."""
    if not isinstance(item, Mapping):
        return None
    raw, icao = _str(item.get("rawOb")), _str(item.get("icaoId"))
    if raw is None or icao is None:
        return None
    wdir = item.get("wdir")
    visibility, minimum = parse_visibility(item.get("visib"))
    return AwcMetar(
        icao=icao.upper(),
        raw=raw,
        observed=_epoch(item.get("obsTime")) or _iso(item.get("reportTime")),
        name=_str(item.get("name")),
        metar_type=_str(item.get("metarType")),
        flight_category=_str(item.get("fltCat")),
        wind_direction=_int(wdir),
        wind_variable=isinstance(wdir, str) and wdir.strip().upper() == "VRB",
        wind_speed_kt=_int(item.get("wspd")),
        visibility_sm=visibility,
        visibility_is_minimum=minimum,
        temperature_c=_num(item.get("temp")),
        dewpoint_c=_num(item.get("dewp")),
        altimeter_hpa=_num(item.get("altim")),
        lat=_num(item.get("lat")),
        lon=_num(item.get("lon")),
        elevation_m=_num(item.get("elev")),
        source=dict(item),
    )


def parse_taf(item: object) -> AwcTaf | None:
    """One AWC TAF object, or ``None`` when it has no usable raw report or station."""
    if not isinstance(item, Mapping):
        return None
    raw, icao = _str(item.get("rawTAF")), _str(item.get("icaoId"))
    if raw is None or icao is None:
        return None
    return AwcTaf(
        icao=icao.upper(),
        raw=raw,
        issued=_iso(item.get("issueTime")) or _iso(item.get("bulletinTime")),
        valid_from=_epoch(item.get("validTimeFrom")),
        valid_to=_epoch(item.get("validTimeTo")),
        name=_str(item.get("name")),
        remarks=_str(item.get("remarks")),
        source=dict(item),
    )


def parse_station(item: object) -> AwcStation | None:
    """One AWC station object, or ``None`` when it has no ICAO id."""
    if not isinstance(item, Mapping):
        return None
    icao = _str(item.get("icaoId")) or _str(item.get("id"))
    if icao is None:
        return None
    types = item.get("siteType")
    return AwcStation(
        icao=icao.upper(),
        name=_str(item.get("site")),
        iata=_str(item.get("iataId")),
        lat=_num(item.get("lat")),
        lon=_num(item.get("lon")),
        elevation_m=_num(item.get("elev")),
        state=_str(item.get("state")),
        country=_str(item.get("country")),
        site_types=tuple(t for t in types if isinstance(t, str)) if isinstance(types, list) else (),
    )


def parse_metars(payload: object) -> list[AwcMetar]:
    """Every usable METAR in a response body (anything that is not a list gives ``[]``)."""
    rows = payload if isinstance(payload, list) else []
    return [m for m in map(parse_metar, rows) if m is not None]


def parse_tafs(payload: object) -> list[AwcTaf]:
    """Every usable TAF in a response body."""
    rows = payload if isinstance(payload, list) else []
    return [t for t in map(parse_taf, rows) if t is not None]


def parse_stations(payload: object) -> list[AwcStation]:
    """Every usable station in a response body."""
    rows = payload if isinstance(payload, list) else []
    return [s for s in map(parse_station, rows) if s is not None]


def latest_by_station(metars: list[AwcMetar]) -> dict[str, AwcMetar]:
    """The newest report per station (reports without a time lose to any with one)."""
    newest: dict[str, AwcMetar] = {}
    floor = datetime.min.replace(tzinfo=UTC)
    for metar in metars:
        current = newest.get(metar.icao)
        if current is None or (metar.observed or floor) > (current.observed or floor):
            newest[metar.icao] = metar
    return newest
