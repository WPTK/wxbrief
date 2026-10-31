"""The only place where model values and catalog keys become sentences.

Every ``describe_*`` function takes a ``Translator`` and a model object and returns text; no other module composes
words. Measured values go through ``render.measure`` (unit symbols are not translated).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from wxbrief.decode.model import (
    RVR,
    CloudLayer,
    DirectionalVisibility,
    Flag,
    FlightCategory,
    Intensity,
    Metar,
    Modifier,
    ParseWarning,
    Phenomenon,
    ReportType,
    SkyCondition,
    Visibility,
    VisPrefix,
    WeatherGroup,
    Wind,
    WindVariation,
)
from wxbrief.decode.tables import (
    CLOUD_TYPE_KEYS,
    COMPASS_KEYS,
    DESCRIPTOR_ALONE_KEYS,
    DESCRIPTOR_WITH_KEYS,
    FLAG_KEYS,
    FLIGHT_CATEGORY_KEYS,
    INTENSITY_KEYS,
    MODIFIER_KEYS,
    PHENOMENON_KEYS,
    REPORT_TYPE_KEYS,
    RVR_TREND_KEYS,
    SKY_COVER_KEYS,
    compass_point,
)
from wxbrief.decode.units import Distance, DistanceUnit, Pressure, Temperature, UnitsMode
from wxbrief.i18n import Translator
from wxbrief.i18n.keys import K
from wxbrief.render.measure import (
    format_pressure,
    format_short_distance,
    format_speed,
    format_temperature,
    format_visibility,
)

CAVOK_CLOUD_BASE_FT = 5000  # CAVOK means no cloud below 5,000 ft (or the highest minimum sector altitude)

_WARNING_KEYS = {
    "unknown_token": K.WARN_UNKNOWN_TOKEN,
    "invalid_day": K.WARN_INVALID_DAY,
    "invalid_time": K.WARN_INVALID_TIME,
    "parser_error": K.WARN_PARSER_ERROR,
    "unsupported_report": K.WARN_UNSUPPORTED_REPORT,
}


def upper_first(text: str) -> str:
    """Capitalise the first character (sentence case for a standalone phrase)."""
    return text[:1].upper() + text[1:]


def lower_first(text: str) -> str:
    """Lowercase the first character unless the word is an acronym (``CAVOK``) or starts a unit/number."""
    if len(text) > 1 and (text[1].isupper() or not text[0].isalpha()):
        return text
    return text[:1].lower() + text[1:]


def join_list(t: Translator, items: Sequence[str]) -> str:
    """``a``, ``a and b``, ``a, b, and c``."""
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return t.t(K.COMMON_AND_PAIR, first=items[0], second=items[1])
    return t.t(K.COMMON_AND_LIST, head=", ".join(items[:-1]), last=items[-1])


def describe_time(t: Translator, moment: datetime | None) -> str:
    if moment is None:
        return t.t(K.TIME_UNRESOLVED)
    return t.t(K.TIME_UTC, value=moment.strftime("%Y-%m-%d %H:%M"))


def describe_report_type(t: Translator, report_type: ReportType) -> str:
    return t.t(REPORT_TYPE_KEYS[report_type])


def describe_modifier(t: Translator, modifier: Modifier) -> str:
    return t.t(MODIFIER_KEYS[modifier])


def describe_flight_category(t: Translator, category: FlightCategory) -> str:
    """``LIFR (low instrument flight rules)``: the code stays, the long name is translated."""
    return t.t(K.FCAT_DISPLAY, code=category.value, name=t.t(FLIGHT_CATEGORY_KEYS[category]))


def describe_flag(t: Translator, flag: Flag) -> str:
    return t.t(FLAG_KEYS[flag])


def describe_wind(t: Translator, wind: Wind, units: UnitsMode, variation: WindVariation | None = None) -> str:
    """Direction, speed and gusts, plus a direction variation when one was reported."""
    if wind.speed is None:
        text = t.t(K.WIND_NOT_REPORTED)
    elif wind.calm:
        text = t.t(K.WIND_CALM)
    else:
        speed = format_speed(wind.speed, units)
        if wind.speed_above:
            speed = t.t(K.COMMON_MORE_THAN, value=speed)
        if wind.variable:
            text = t.t(K.WIND_VARIABLE, speed=speed)
        elif wind.direction is None:
            text = t.t(K.WIND_NO_DIRECTION, speed=speed)
        else:
            compass = t.t(COMPASS_KEYS[compass_point(wind.direction)])
            text = t.t(K.WIND_STEADY, direction=f"{wind.direction:03d}", compass=compass, speed=speed)
        if wind.gust is not None:
            text = t.t(K.WIND_GUST, base=text, gust=format_speed(wind.gust, units))
    if variation is not None:
        text = t.t(K.WIND_VARIATION, base=text, from_deg=f"{variation.start:03d}", to_deg=f"{variation.end:03d}")
    return text


def _qualified(t: Translator, distance: Distance, prefix: VisPrefix | None, units: UnitsMode, *, short: bool) -> str:
    text = format_short_distance(distance, units) if short else format_visibility(distance, units)
    if prefix is VisPrefix.LESS_THAN:
        return t.t(K.COMMON_LESS_THAN, value=text)
    if prefix is VisPrefix.GREATER_THAN:
        return t.t(K.COMMON_MORE_THAN, value=text)
    return text


def _ten_km_or_more(t: Translator, units: UnitsMode) -> str:
    """The meaning of ``9999`` and of CAVOK's visibility."""
    return t.t(K.COMMON_OR_MORE, value=format_visibility(Distance(10, DistanceUnit.KM), units))


def _describe_minimum(t: Translator, item: DirectionalVisibility, units: UnitsMode) -> str:
    value = format_visibility(item.distance, units)
    if item.direction is None:
        return value
    return t.t(K.VIS_DIRECTIONAL, value=value, compass=t.t(COMPASS_KEYS[item.direction]))


def describe_visibility(t: Translator, visibility: Visibility, units: UnitsMode) -> str:
    if visibility.cavok:
        return t.t(
            K.VIS_CAVOK,
            visibility=_ten_km_or_more(t, units),
            height=format_short_distance(Distance(CAVOK_CLOUD_BASE_FT, DistanceUnit.FT), units),
        )
    if visibility.not_reported or visibility.distance is None:
        return t.t(K.VIS_NOT_REPORTED)
    if visibility.unlimited:
        text = _ten_km_or_more(t, units)
    else:
        text = _qualified(t, visibility.distance, visibility.prefix, units, short=False)
    if visibility.directional:
        lowest = "; ".join(_describe_minimum(t, item, units) for item in visibility.directional)
        text = t.t(K.VIS_LOWEST, base=text, minimum=lowest)
    if visibility.ndv:
        text = t.t(K.VIS_WITH_NDV, base=text, ndv=t.t(K.VIS_NDV))
    return text


def describe_rvr(t: Translator, rvr: RVR, units: UnitsMode) -> str:
    if rvr.distance is None:
        value = t.t(K.RVR_NOT_REPORTED)
    else:
        value = _qualified(t, rvr.distance, rvr.prefix, units, short=True)
        if rvr.variable_to is not None:
            high = _qualified(t, rvr.variable_to, rvr.variable_to_prefix, units, short=True)
            value = t.t(K.RVR_RANGE, low=value, high=high)
    if rvr.trend is not None:
        value = t.t(K.RVR_WITH_TREND, base=value, trend=t.t(RVR_TREND_KEYS[rvr.trend]))
    return t.t(K.RVR_RUNWAY, runway=rvr.runway, value=value)


def describe_weather_group(t: Translator, group: WeatherGroup) -> str:
    """One present-weather group in lower case (``light rain``, ``thunderstorm with rain``)."""
    if group.nsw:
        return t.t(K.WX_NONE)
    if group.not_observed:
        return t.t(K.WX_NOT_OBSERVED)
    tornado = group.intensity is Intensity.HEAVY and group.descriptor is None and group.phenomena == (Phenomenon.FC,)
    if tornado:
        body = t.t(K.WX_TORNADO)
    else:
        phenomena = join_list(t, [t.t(PHENOMENON_KEYS[p]) for p in group.phenomena])
        if group.descriptor is None:
            body = phenomena
        elif phenomena:
            body = t.t(DESCRIPTOR_WITH_KEYS[group.descriptor], phenomena=phenomena)
        else:
            body = t.t(DESCRIPTOR_ALONE_KEYS[group.descriptor])
        intensity_key = INTENSITY_KEYS[group.intensity]
        if intensity_key is not None:
            body = t.t(K.WX_WITH_INTENSITY, intensity=t.t(intensity_key), body=body)
    if group.vicinity:
        body = t.t(K.WX_VICINITY, body=body)
    return body


def describe_weather(t: Translator, groups: Sequence[WeatherGroup]) -> str:
    """All present-weather groups as one sentence fragment."""
    return upper_first(join_list(t, [describe_weather_group(t, group) for group in groups]))


def describe_cloud_layer(t: Translator, layer: CloudLayer, units: UnitsMode) -> str:
    if layer.cover is SkyCondition.VV:
        if layer.base is None:
            return t.t(K.SKY_VERTICAL_VISIBILITY_UNKNOWN)
        return t.t(K.SKY_VERTICAL_VISIBILITY, height=format_short_distance(layer.base, units))
    cover = t.t(SKY_COVER_KEYS[layer.cover])
    if layer.base is None:
        if layer.cover in (SkyCondition.FEW, SkyCondition.SCT, SkyCondition.BKN, SkyCondition.OVC):
            return t.t(K.SKY_LAYER_NO_HEIGHT, cover=cover)
        return cover
    height = format_short_distance(layer.base, units)
    if layer.cloud_type is not None:
        return t.t(K.SKY_LAYER_TYPED, cover=cover, height=height, type=t.t(CLOUD_TYPE_KEYS[layer.cloud_type]))
    return t.t(K.SKY_LAYER, cover=cover, height=height)


def describe_sky(t: Translator, layers: Sequence[CloudLayer], units: UnitsMode) -> str:
    return "; ".join(describe_cloud_layer(t, layer, units) for layer in layers)


def describe_ceiling(t: Translator, ceiling: Distance | None, units: UnitsMode) -> str:
    if ceiling is None:
        return t.t(K.SKY_NO_CEILING)
    return t.t(K.SKY_CEILING, height=format_short_distance(ceiling, units))


def describe_temperature(t: Translator, temperature: Temperature | None, units: UnitsMode) -> str:
    if temperature is None:
        return t.t(K.COMMON_NOT_REPORTED)
    return format_temperature(temperature, units)


def describe_humidity(t: Translator, percent: float) -> str:
    return t.t(K.TEMP_HUMIDITY, percent=round(percent))


def describe_pressure(t: Translator, pressure: Pressure | None, units: UnitsMode) -> str:
    if pressure is None:
        return t.t(K.COMMON_NOT_REPORTED)
    return format_pressure(pressure, units)


def describe_warning(t: Translator, warning: ParseWarning) -> str:
    key = _WARNING_KEYS.get(warning.code)
    if key is None:
        return f"{warning.code}: {warning.text}"
    return t.t(key, text=warning.text, start=warning.start, end=warning.end)


def summary_line(t: Translator, metar: Metar, units: UnitsMode) -> str:
    """One sentence: station, flight category, then weather, ceiling, visibility and wind."""
    details: list[str] = []
    present = [g for g in metar.weather if not g.nsw and not g.not_observed]
    if present:
        details.append(lower_first(describe_weather(t, present)))
    if metar.cavok:
        details.append(t.t(K.SUMMARY_CAVOK))
    if metar.ceiling is not None:
        details.append(t.t(K.SUMMARY_CEILING, height=format_short_distance(metar.ceiling, units)))
    if metar.visibility is not None and not metar.cavok and metar.visibility.distance is not None:
        details.append(t.t(K.SUMMARY_VISIBILITY, value=lower_first(describe_visibility(t, metar.visibility, units))))
    if metar.wind is not None and metar.wind.speed is not None:
        details.append(t.t(K.SUMMARY_WIND, value=lower_first(describe_wind(t, metar.wind, units))))
    if not details:
        return t.t(K.SUMMARY_NOTHING)
    joined = ", ".join(details)
    category = describe_flight_category(t, metar.flight_category) if metar.flight_category is not None else None
    if metar.station and category:
        return t.t(K.SUMMARY_REPORTING, station=metar.station, category=category, details=joined)
    if metar.station:
        return t.t(K.SUMMARY_REPORTING_NO_CATEGORY, station=metar.station, details=joined)
    if category:
        return t.t(K.SUMMARY_NO_STATION, category=category, details=joined)
    return t.t(K.SUMMARY_NO_STATION_NO_CATEGORY, details=joined)
