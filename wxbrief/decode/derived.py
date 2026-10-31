"""Values derived from a decoded body: ceiling, operational flags, header condition, relative humidity."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import replace

from wxbrief.decode.flightcat import IFR_CEILING_FT, IFR_VISIBILITY_SM, flight_category, lowest_ceiling, visibility_sm
from wxbrief.decode.model import (
    CloudType,
    Condition,
    Descriptor,
    Flag,
    Metar,
    Modifier,
    Phenomenon,
    ReportType,
    SkyCondition,
    WeatherGroup,
)
from wxbrief.decode.units import Distance, Temperature

# Condition groups, from the metar-taf-decode reference notes (header glyph rules, listed there in priority order).
_SNOW_PHENOMENA = frozenset({Phenomenon.SN, Phenomenon.SG, Phenomenon.PL, Phenomenon.GS, Phenomenon.GR, Phenomenon.IC})
_RAIN_PHENOMENA = frozenset({Phenomenon.RA, Phenomenon.DZ, Phenomenon.UP})
_OBSCURATION_PHENOMENA = frozenset(
    {
        Phenomenon.FG,
        Phenomenon.BR,
        Phenomenon.HZ,
        Phenomenon.FU,
        Phenomenon.DU,
        Phenomenon.SA,
        Phenomenon.VA,
        Phenomenon.DS,
        Phenomenon.SS,
    }
)
_FREEZING_PRECIP_PHENOMENA = frozenset({Phenomenon.RA, Phenomenon.DZ, Phenomenon.UP})
_CORRECTION_MODIFIERS = frozenset({Modifier.COR, Modifier.CCA, Modifier.CCB, Modifier.CCC})

DAY_START_HOUR = 6  # local hours [6, 20) count as daytime for the clear-sky glyph
DAY_END_HOUR = 20


def _on_field(groups: Sequence[WeatherGroup]) -> list[WeatherGroup]:
    """Weather at the station itself (vicinity groups do not set the dominant condition)."""
    return [group for group in groups if not group.vicinity and not group.nsw and not group.not_observed]


def compute_condition(metar: Metar) -> Condition | None:
    """The dominant condition: thunderstorm, snow/freezing, rain, obscuration, then the densest cloud layer."""
    # Thunderstorms count even in the vicinity (VCTS); other vicinity weather does not.
    if any(group.descriptor is Descriptor.TS for group in metar.weather):
        return Condition.THUNDERSTORM
    present = _on_field(metar.weather)
    phenomena = {p for group in present for p in group.phenomena}
    if phenomena & _SNOW_PHENOMENA or any(
        group.descriptor is Descriptor.FZ and set(group.phenomena) & _FREEZING_PRECIP_PHENOMENA for group in present
    ):
        return Condition.SNOW
    if phenomena & _RAIN_PHENOMENA:
        return Condition.RAIN
    if phenomena & _OBSCURATION_PHENOMENA:
        return Condition.OBSCURATION
    covers = {layer.cover for layer in metar.sky}
    if SkyCondition.OVC in covers or SkyCondition.VV in covers:
        return Condition.OVERCAST
    if SkyCondition.BKN in covers:
        return Condition.BROKEN
    if covers & {SkyCondition.FEW, SkyCondition.SCT}:
        return Condition.PARTLY_CLOUDY
    if covers or metar.cavok:
        return Condition.CLEAR
    return None


def refine_clear(condition: Condition | None, local_hour: int) -> Condition | None:
    """Turn ``CLEAR`` into ``CLEAR_DAY``/``CLEAR_NIGHT`` once the station-local hour is known."""
    if condition is not Condition.CLEAR:
        return condition
    return Condition.CLEAR_DAY if DAY_START_HOUR <= local_hour < DAY_END_HOUR else Condition.CLEAR_NIGHT


def compute_flags(metar: Metar) -> tuple[Flag, ...]:
    """Operationally significant conditions, in the order of the ``Flag`` enum."""
    found: set[Flag] = set()
    types = {layer.cloud_type for layer in metar.sky}
    if CloudType.CB in types:
        found.add(Flag.CB)
    if CloudType.TCU in types:
        found.add(Flag.TCU)
    if metar.ceiling is not None and metar.ceiling.feet < IFR_CEILING_FT:
        found.add(Flag.LOW_CEILING)
    vis = visibility_sm(metar.visibility)
    if vis is not None and vis < IFR_VISIBILITY_SM:
        found.add(Flag.LOW_VISIBILITY)
    if metar.wind is not None and metar.wind.gust is not None:
        found.add(Flag.GUSTS)
    for group in metar.weather:
        if group.descriptor is Descriptor.FZ and set(group.phenomena) & _FREEZING_PRECIP_PHENOMENA:
            found.add(Flag.FREEZING_PRECIP)
        if group.descriptor is Descriptor.TS:
            found.add(Flag.THUNDERSTORM)
    if _CORRECTION_MODIFIERS & set(metar.modifiers):
        found.add(Flag.CORRECTED)
    if Modifier.AUTO in metar.modifiers:
        found.add(Flag.AUTOMATED)
    if metar.report_type is ReportType.SPECI:
        found.add(Flag.SPECIAL_REPORT)
    return tuple(flag for flag in Flag if flag in found)


def relative_humidity(temperature: Temperature | None, dewpoint: Temperature | None) -> float | None:
    """Relative humidity in percent from temperature and dew point (Magnus formula), capped at 100."""
    if temperature is None or dewpoint is None:
        return None
    a, b = 17.625, 243.04
    t, td = temperature.celsius, dewpoint.celsius
    humidity = 100.0 * math.exp(a * td / (b + td)) / math.exp(a * t / (b + t))
    return round(min(100.0, humidity), 1)


def derive(metar: Metar) -> Metar:
    """Fill in the derived fields of a parsed ``Metar``."""
    layer = lowest_ceiling(metar.sky)
    ceiling: Distance | None = layer.base if layer is not None else None
    staged = replace(metar, ceiling=ceiling)
    return replace(
        staged,
        flight_category=flight_category(metar.visibility, metar.sky),
        flags=compute_flags(staged),
        condition=compute_condition(staged),
        relative_humidity=relative_humidity(metar.temperature, metar.dewpoint),
    )
