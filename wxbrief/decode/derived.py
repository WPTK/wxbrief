"""Values derived from a decoded body: ceiling, operational flags, header condition, relative humidity."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import replace

from wxbrief.decode.colorstate import computed_color_state, is_below_green, visibility_meters
from wxbrief.decode.flightcat import (
    IFR_CEILING_FT,
    IFR_VISIBILITY_SM,
    ceiling_for_classification,
    flight_category,
    lowest_ceiling,
    visibility_sm,
    worst_of,
)
from wxbrief.decode.model import (
    CeilingStatus,
    CloudType,
    ColorCode,
    Condition,
    Descriptor,
    Flag,
    ForecastElements,
    IcingIntensity,
    Intensity,
    MaintenanceIndicator,
    Metar,
    Modifier,
    Phenomenon,
    PressureRapidChange,
    ReportType,
    RunwayDeposit,
    RunwayState,
    SeaLevelPressure,
    SensorStatus,
    SkyCondition,
    Taf,
    TurbulenceIntensity,
    WeatherGroup,
)
from wxbrief.decode.timeline import expand_timeline
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
_CLEAR_SKY_COVERS = frozenset({SkyCondition.SKC, SkyCondition.CLR, SkyCondition.NSC, SkyCondition.NCD})
_CORRECTION_MODIFIERS = frozenset({Modifier.COR, Modifier.CCA, Modifier.CCB, Modifier.CCC})

# Deposits that make a runway contaminated for the flag: anything but clear, damp or wet.
_CONTAMINATING_DEPOSITS = frozenset(
    {
        RunwayDeposit.FROST,
        RunwayDeposit.DRY_SNOW,
        RunwayDeposit.WET_SNOW,
        RunwayDeposit.SLUSH,
        RunwayDeposit.ICE,
        RunwayDeposit.COMPACTED_SNOW,
        RunwayDeposit.FROZEN_RUTS,
    }
)


def _on_field(groups: Sequence[WeatherGroup]) -> list[WeatherGroup]:
    """Weather at the station itself (vicinity groups do not set the dominant condition)."""
    return [group for group in groups if not group.vicinity and not group.nsw and not group.not_observed]


def compute_condition(metar: Metar) -> Condition | None:
    """The dominant condition: thunderstorm, snow/freezing, rain, obscuration, then the densest cloud layer."""
    present = _on_field(metar.weather)
    # Tornado, waterspout and funnel cloud (+FC, FC) outrank everything.
    if any(Phenomenon.FC in group.phenomena for group in present):
        return Condition.TORNADO
    # Thunderstorms count even in the vicinity (VCTS); other vicinity weather does not.
    if any(group.descriptor is Descriptor.TS for group in metar.weather):
        return Condition.THUNDERSTORM
    if any(Phenomenon.SQ in group.phenomena for group in present):
        return Condition.SQUALL
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
    if metar.cavok or covers & _CLEAR_SKY_COVERS:
        return Condition.CLEAR
    return None  # no sky, or only unknown ("///") layers: the sensor reported nothing usable


def refine_clear(condition: Condition | None, daylight: bool) -> Condition | None:
    """Turn ``CLEAR`` into ``CLEAR_DAY``/``CLEAR_NIGHT`` once it is known whether the sun is up."""
    if condition is not Condition.CLEAR:
        return condition
    return Condition.CLEAR_DAY if daylight else Condition.CLEAR_NIGHT


def _runway_contaminated(state: RunwayState) -> bool:
    return state.snoclo or (not state.cleared and state.deposit in _CONTAMINATING_DEPOSITS)


def _has_volcanic_ash(metar: Metar) -> bool:
    groups = [*metar.weather, *(recent.weather for recent in metar.recent_weather)]
    groups.extend(group for trend in metar.trends for group in trend.elements.weather)
    return any(Phenomenon.VA in group.phenomena for group in groups)


def _has_missing_data(metar: Metar) -> bool:
    """A sensor reported out, ``SLPNO``, or a group the station could not report (``//``, ``////``, ``///``)."""
    if any(isinstance(remark, SensorStatus) for remark in metar.remarks):
        return True
    if any(isinstance(remark, SeaLevelPressure) and remark.pressure is None for remark in metar.remarks):
        return True
    if any(group.not_observed for group in metar.weather):
        return True
    if metar.visibility is not None and metar.visibility.not_reported:
        return True
    if metar.wind is not None and metar.wind.speed is None:
        return True
    return any(
        layer.cover is SkyCondition.UNKNOWN or (layer.is_ceiling_layer and layer.base is None) for layer in metar.sky
    )


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
        if group.vicinity or group.nsw or group.not_observed:
            continue
        if Phenomenon.FC in group.phenomena:
            found.add(Flag.TORNADO if group.intensity is Intensity.HEAVY else Flag.FUNNEL_CLOUD)
        if Phenomenon.SQ in group.phenomena:
            found.add(Flag.SQUALL)
    if _CORRECTION_MODIFIERS & set(metar.modifiers):
        found.add(Flag.CORRECTED)
    if Modifier.AUTO in metar.modifiers:
        found.add(Flag.AUTOMATED)
    if metar.report_type is ReportType.SPECI:
        found.add(Flag.SPECIAL_REPORT)
    if metar.wind_shear:
        found.add(Flag.WIND_SHEAR)
    if metar.color_state is not None and is_below_green(metar.color_state.current):
        found.add(Flag.COLOR_BELOW_GRN)
    if any(isinstance(remark, PressureRapidChange) for remark in metar.remarks):
        found.add(Flag.RAPID_PRESSURE_CHANGE)
    if any(_runway_contaminated(state) for state in metar.runway_states):
        found.add(Flag.RUNWAY_CONTAMINATED)
    if any(isinstance(remark, MaintenanceIndicator) for remark in metar.remarks):
        found.add(Flag.MAINTENANCE)
    if _has_volcanic_ash(metar):
        found.add(Flag.VOLCANIC_ASH)
    if _has_missing_data(metar):
        found.add(Flag.MISSING_DATA)
    return tuple(flag for flag in Flag if flag in found)


def relative_humidity(temperature: Temperature | None, dewpoint: Temperature | None) -> float | None:
    """Relative humidity in percent from temperature and dew point (Magnus formula), capped at 100."""
    if temperature is None or dewpoint is None:
        return None
    a, b = 17.625, 243.04
    t, td = temperature.celsius, dewpoint.celsius
    humidity = 100.0 * math.exp(a * td / (b + td)) / math.exp(a * t / (b + t))
    return round(min(100.0, humidity), 1)


def _computed_color(metar: Metar) -> ColorCode | None:
    """The colour state the report's ceiling and visibility compute to, for reports that carry a colour state."""
    if metar.color_state is None:
        return None
    ceiling_ft = ceiling_for_classification(metar.sky, metar.cavok)
    return computed_color_state(ceiling_ft, visibility_meters(metar.visibility))


def _ceiling_status(metar: Metar, ceiling: Distance | None) -> CeilingStatus | None:
    if ceiling is not None:
        return CeilingStatus.HEIGHT
    if not metar.sky and not metar.cavok:
        return None
    return CeilingStatus.UNKNOWN if ceiling_for_classification(metar.sky, metar.cavok) is None else CeilingStatus.NONE


def derive(metar: Metar) -> Metar:
    """Fill in the derived fields of a parsed ``Metar``."""
    layer = lowest_ceiling(metar.sky)
    # A known layer is no ceiling while an unknown one may sit below it.
    known = ceiling_for_classification(metar.sky, metar.cavok) is not None
    ceiling: Distance | None = layer.base if layer is not None and known else None
    staged = replace(metar, ceiling=ceiling, ceiling_status=_ceiling_status(metar, ceiling))
    return replace(
        staged,
        flight_category=flight_category(metar.visibility, metar.sky),
        flags=compute_flags(staged),
        condition=compute_condition(staged),
        relative_humidity=relative_humidity(metar.temperature, metar.dewpoint),
        computed_color_state=_computed_color(staged),
    )


# --- TAF ---------------------------------------------------------------------------------------------------------


def _elements_of(taf: Taf) -> list[ForecastElements]:
    return [period.elements for period in taf.periods]


def compute_taf_flags(taf: Taf) -> tuple[Flag, ...]:
    """Operationally significant conditions anywhere in the forecast, in the order of the ``Flag`` enum."""
    found: set[Flag] = set()
    for elements in _elements_of(taf):
        types = {layer.cloud_type for layer in elements.sky}
        if CloudType.CB in types:
            found.add(Flag.CB)
        if CloudType.TCU in types:
            found.add(Flag.TCU)
        layer = lowest_ceiling(elements.sky)
        if layer is not None and layer.base is not None and layer.base.feet < IFR_CEILING_FT:
            found.add(Flag.LOW_CEILING)
        vis = visibility_sm(elements.visibility)
        if vis is not None and vis < IFR_VISIBILITY_SM:
            found.add(Flag.LOW_VISIBILITY)
        if elements.wind is not None and elements.wind.gust is not None:
            found.add(Flag.GUSTS)
        if elements.wind_shear is not None:
            found.add(Flag.WIND_SHEAR)
        for group in elements.weather:
            if group.descriptor is Descriptor.FZ and set(group.phenomena) & _FREEZING_PRECIP_PHENOMENA:
                found.add(Flag.FREEZING_PRECIP)
            if group.descriptor is Descriptor.TS:
                found.add(Flag.THUNDERSTORM)
            if Phenomenon.VA in group.phenomena:
                found.add(Flag.VOLCANIC_ASH)
        if is_below_green(elements.color_state):
            found.add(Flag.COLOR_BELOW_GRN)
        if any(item.intensity is not IcingIntensity.NONE for item in elements.icing):
            found.add(Flag.ICING)
        if any(item.intensity is not TurbulenceIntensity.NONE for item in elements.turbulence):
            found.add(Flag.TURBULENCE)
        if any(
            item.cover is SkyCondition.UNKNOWN or (item.is_ceiling_layer and item.base is None)
            for item in elements.sky
        ):
            found.add(Flag.MISSING_DATA)
    if _CORRECTION_MODIFIERS & set(taf.modifiers):
        found.add(Flag.CORRECTED)
    if Modifier.AMD in taf.modifiers:
        found.add(Flag.AMENDED)
    return tuple(flag for flag in Flag if flag in found)


def derive_taf(taf: Taf) -> Taf:
    """Fill in the derived fields of a parsed ``Taf``: its flags and the worst flight category anywhere.

    A cancelled TAF has no forecast: whatever groups its text still carries (AWC keeps the old body on a feed row
    marked ``CNL``) are dropped from the model, so no renderer can present them as a live forecast.
    """
    if taf.cancelled:
        taf = replace(taf, base=None, changes=(), temperatures=())
    timeline = expand_timeline(taf)
    worst = timeline.worst_category if timeline.slices else worst_of(period.flight_category for period in taf.periods)
    return replace(taf, flags=compute_taf_flags(taf), worst_category=worst)
