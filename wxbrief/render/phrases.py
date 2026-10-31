"""The only place where model values and catalog keys become sentences.

Every ``describe_*`` function takes a ``Translator`` and a model object and returns text; no other module composes
words. Measured values go through ``render.measure`` (unit symbols are not translated).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime

from wxbrief.decode.model import (
    RVR,
    AltimeterSetting,
    AutomatedStationType,
    CloudLayer,
    CloudOpacity,
    CloudTypes,
    ColorState,
    ColorStateGroup,
    ColorStateRemark,
    DailyPrecipitation,
    DailyTemperatureExtremes,
    DensityAltitude,
    DirectionalVisibility,
    Flag,
    FlightCategory,
    ForecastElements,
    FreeText,
    HailSize,
    HourlyPrecipitation,
    Intensity,
    Lightning,
    MaintenanceIndicator,
    MaxTemperature6Hour,
    Metar,
    MinTemperature6Hour,
    Modifier,
    ParseWarning,
    PeakWind,
    PeriodPrecipitation,
    Phenomenon,
    PreciseTemperature,
    PressureRapidChange,
    PressureTendency,
    RecentWeather,
    Remark,
    RemarkTime,
    ReportType,
    RunwayBraking,
    RunwayState,
    RunwayWind,
    SeaLevelPressure,
    SeaState,
    SecondaryCeiling,
    SectorVisibility,
    SensorStatus,
    SkyCondition,
    SnowDepth,
    SnowIncrease,
    StationPressure,
    StationPressureKind,
    SurfaceVisibility,
    TendencyDirection,
    TimingSegment,
    TowerVisibility,
    Trend,
    TrendKind,
    TrendTime,
    VariableCeiling,
    VariableVisibility,
    Visibility,
    VisPrefix,
    WeatherGroup,
    WeatherTiming,
    Wind,
    WindAtHeight,
    WindShearRunway,
    WindShift,
    WindVariation,
)
from wxbrief.decode.tables import (
    BRAKING_ACTION_KEYS,
    CLOUD_HIGH_KEYS,
    CLOUD_LOW_KEYS,
    CLOUD_MIDDLE_KEYS,
    CLOUD_TYPE_KEYS,
    COLOR_NAME_KEYS,
    COMPASS_KEYS,
    DESCRIPTOR_ALONE_KEYS,
    DESCRIPTOR_WITH_KEYS,
    FLAG_KEYS,
    FLIGHT_CATEGORY_KEYS,
    FREE_TEXT_WORD_KEYS,
    INTENSITY_KEYS,
    LIGHTNING_FREQUENCY_KEYS,
    LIGHTNING_TYPE_KEYS,
    MODIFIER_KEYS,
    OPACITY_CLOUD_KEYS,
    PHENOMENON_KEYS,
    REPORT_TYPE_KEYS,
    RUNWAY_DEPOSIT_KEYS,
    RUNWAY_DEPTH_KEYS,
    RUNWAY_EXTENT_KEYS,
    RVR_TREND_KEYS,
    SEA_STATE_KEYS,
    SENSOR_KEYS,
    SKY_COVER_KEYS,
    TENDENCY_NAME_KEYS,
    TREND_TIME_KEYS,
    compass_point,
)
from wxbrief.decode.units import Distance, DistanceUnit, Pressure, Temperature, UnitsMode
from wxbrief.i18n import Translator
from wxbrief.i18n.keys import K
from wxbrief.render.measure import (
    format_inches,
    format_millimeters,
    format_pressure,
    format_pressure_change,
    format_short_distance,
    format_speed,
    format_temperature,
    format_visibility,
    format_wave_height,
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


# --- trends, colour states, runway state and the other tail groups ---------------------------------------------


def describe_color_code(t: Translator, state: ColorState) -> str:
    """One colour state: the name and the code as reported (``Blue (BLU+)``); ``BLACK`` is spelled out."""
    if state.not_reported:
        return t.t(K.COMMON_NOT_REPORTED)
    if state.code is None:
        return t.t(K.COLOR_BLACK_ALONE)
    code = state.code.value + ("+" if state.plus else "")
    text = t.t(K.COLOR_DISPLAY, name=t.t(COLOR_NAME_KEYS[state.code]), code=code)
    if state.black:
        return t.t(K.COLOR_BLACK_WITH, state=text)
    return text


_COLOR_CHANGE_KEYS = {
    None: K.COLOR_EXPECTED,
    TrendKind.BECMG: K.COLOR_BECOMING,
    TrendKind.TEMPO: K.COLOR_TEMPORARY,
}


def describe_color_state(t: Translator, group: ColorStateGroup) -> str:
    """The current colour state and the forecast ones (``Green (GRN); forecast: White (WHT) expected``)."""
    items = [
        t.t(_COLOR_CHANGE_KEYS[item.change], state=describe_color_code(t, item.state)) for item in group.forecast
    ]
    forecast = ", ".join(items)
    if group.current is None:
        return t.t(K.COLOR_FORECAST_ONLY, items=forecast) if items else t.t(K.COMMON_NOT_REPORTED)
    current = describe_color_code(t, group.current)
    return t.t(K.COLOR_FORECAST, current=current, items=forecast) if items else current


def describe_trend_time(t: Translator, item: TrendTime) -> str:
    """``from 11:30 UTC``; the time of day of the resolved moment when there is one."""
    clock = item.moment.strftime("%H:%M") if item.moment is not None else f"{item.hour:02d}:{item.minute:02d}"
    return t.t(TREND_TIME_KEYS[item.kind], time=t.t(K.TIME_UTC, value=clock))


def describe_forecast_elements(t: Translator, elements: ForecastElements, units: UnitsMode) -> str:
    """The elements a trend states, as one fragment (``visibility 350 m; broken clouds at 1,000 ft``)."""
    items: list[str] = []
    if elements.wind is not None:
        items.append(t.t(K.TREND_WIND, value=lower_first(describe_wind(t, elements.wind, units))))
    if elements.visibility is not None:
        text = describe_visibility(t, elements.visibility, units)
        items.append(text if elements.visibility.cavok else t.t(K.TREND_VISIBILITY, value=lower_first(text)))
    if elements.weather:
        items.append(lower_first(describe_weather(t, elements.weather)))
    if elements.sky:
        items.append(t.t(K.TREND_SKY, value=lower_first(describe_sky(t, elements.sky, units))))
    if elements.color_state is not None:
        items.append(t.t(K.TREND_COLOR, value=describe_color_code(t, elements.color_state)))
    return "; ".join(items)


def describe_trend(t: Translator, trend: Trend, units: UnitsMode) -> str:
    """``No significant change expected ...`` or ``Lasting change from 11:30 UTC until 12:30 UTC: visibility 350 m``."""
    if trend.kind is TrendKind.NOSIG:
        return t.t(K.TREND_NOSIG)
    details = describe_forecast_elements(t, trend.elements, units) or t.t(K.TREND_NO_DETAILS)
    when = " ".join(describe_trend_time(t, item) for item in trend.times)
    if trend.kind is TrendKind.BECMG:
        return t.t(K.TREND_BECMG_WHEN, when=when, details=details) if when else t.t(K.TREND_BECMG, details=details)
    return t.t(K.TREND_TEMPO_WHEN, when=when, details=details) if when else t.t(K.TREND_TEMPO, details=details)


def _runway_braking(t: Translator, braking: RunwayBraking) -> str | None:
    if braking.unreliable:
        return t.t(K.RWY_BRAKING_UNRELIABLE)
    if braking.action is not None:
        return t.t(BRAKING_ACTION_KEYS[braking.action])
    if braking.coefficient is not None:
        return t.t(K.RWY_BRAKING_COEFFICIENT, value=f"{braking.coefficient:.2f}")
    return None


def describe_runway_state(t: Translator, state: RunwayState, units: UnitsMode) -> str:
    """One runway state group in words (``Runway 24L: wet or water patches; ...; braking coefficient 0.55``)."""
    if state.snoclo:
        return t.t(K.RWY_SNOCLO)
    if state.repeated:
        return t.t(K.RWY_REPEATED)
    where = t.t(K.RWY_ALL) if state.all_runways else t.t(K.RWY_RUNWAY, runway=state.runway)
    braking = _runway_braking(t, state.braking) if state.braking is not None else None
    if state.cleared:
        if braking is None:
            return t.t(K.RWY_CLEARED, where=where)
        return t.t(K.RWY_CLEARED_BRAKING, where=where, braking=braking)
    parts: list[str] = []
    if state.deposit is not None:
        parts.append(t.t(RUNWAY_DEPOSIT_KEYS[state.deposit]))
    if state.extent is not None:
        parts.append(t.t(RUNWAY_EXTENT_KEYS[state.extent]))
    if state.depth is not None:
        value = format_millimeters(state.depth.mm, units) if state.depth.mm is not None else ""
        parts.append(t.t(RUNWAY_DEPTH_KEYS[state.depth.kind], value=value))
    if braking is not None:
        parts.append(braking)
    return t.t(K.RWY_STATE, where=where, details="; ".join(parts) or t.t(K.RWY_NOTHING))


def describe_recent_weather(t: Translator, recent: RecentWeather) -> str:
    """``Rain showers since the last report, now ended``."""
    return upper_first(t.t(K.RECENT_PHRASE, weather=describe_weather_group(t, recent.weather)))


def describe_wind_shear(t: Translator, items: Sequence[WindShearRunway]) -> str:
    """``Wind shear on all runways`` or ``Wind shear on runway 24L and runway 24R``."""
    if any(item.all_runways for item in items):
        where = t.t(K.SHEAR_ALL)
    else:
        where = join_list(t, [t.t(K.SHEAR_RUNWAY, runway=item.runway) for item in items])
    return t.t(K.SHEAR_VALUE, where=where)


def describe_sea_state(t: Translator, sea: SeaState, units: UnitsMode) -> str:
    """``Water temperature 15 °C, sea state 3 (slight)``."""
    parts: list[str] = []
    if sea.temperature is not None:
        parts.append(t.t(K.SEA_TEMPERATURE, value=format_temperature(sea.temperature, units)))
    if sea.state is not None:
        parts.append(t.t(K.SEA_STATE, code=sea.state, name=t.t(SEA_STATE_KEYS[sea.state])))
    if sea.wave_height_m is not None:
        parts.append(t.t(K.SEA_HEIGHT, value=format_wave_height(sea.wave_height_m, units)))
    return upper_first(", ".join(parts) or t.t(K.SEA_NOTHING))


# --- remarks ---------------------------------------------------------------------------------------------------

_FREE_TIME = re.compile(r"^(?P<kind>[BE])(?P<hh>\d{2})?(?P<mm>\d{2})$")
_COMPASS_RANGE = re.compile(r"^(?:N|NE|E|SE|S|SW|W|NW)(?:-(?:N|NE|E|SE|S|SW|W|NW))+$")


def _remark_time(t: Translator, when: RemarkTime) -> str:
    if when.hour is None:
        return t.t(K.REMARK_TIME_MINUTE, minute=when.minute)
    return t.t(K.REMARK_TIME_CLOCK, clock=f"{when.hour:02d}:{when.minute:02d}")


def _remark_place(t: Translator, location: str) -> str:
    """``RWY11`` -> ``at runway 11``; a compass sector -> ``toward northeast``."""
    if location.startswith("RWY"):
        return t.t(K.REMARK_AT_RUNWAY, runway=location.removeprefix("RWY"))
    key = FREE_TEXT_WORD_KEYS.get(location)
    return t.t(K.REMARK_TOWARD, compass=t.t(key) if key is not None else location)


def _free_word(t: Translator, word: str) -> str | None:
    """The words for one word of a plain-language remark, or ``None`` if the catalog does not know it."""
    key = FREE_TEXT_WORD_KEYS.get(word)
    if key is not None:
        return t.t(key)
    if _COMPASS_RANGE.match(word):
        parts = [_free_word(t, part) for part in word.split("-")]
        return f" {t.t(K.REMARK_WORD_TO)} ".join(part for part in parts if part is not None)
    timed = _FREE_TIME.match(word)
    if timed is not None:
        began = timed.group("kind") == "B"
        if timed.group("hh") is None:
            key = K.REMARK_FREE_BEGAN if began else K.REMARK_FREE_ENDED
            return t.t(key, minute=int(timed.group("mm")))
        key = K.REMARK_FREE_BEGAN_CLOCK if began else K.REMARK_FREE_ENDED_CLOCK
        return t.t(key, clock=f"{timed.group('hh')}:{timed.group('mm')}")
    return None


def describe_free_text(t: Translator, text: str) -> str:
    """A plain-language remark with the words the catalog knows spelled out; the rest is kept as written."""
    return upper_first(" ".join(_free_word(t, word) or word for word in text.split()))


def undecoded_free_text(t: Translator, metar: Metar) -> list[str]:
    """The free-text remarks that contain a word the catalog cannot spell out, verbatim."""
    return [
        remark.text
        for remark in metar.remarks
        if isinstance(remark, FreeText) and any(_free_word(t, word) is None for word in remark.text.split())
    ]


def _inches(t: Translator, value: float | None, units: UnitsMode, *, trace: bool = False) -> str:
    if trace:
        return t.t(K.REMARK_TRACE)
    if value is None:
        return t.t(K.REMARK_PRECIPITATION_MISSING)
    return format_inches(value, units)


def _temperature(t: Translator, value: Temperature | None, units: UnitsMode) -> str:
    if value is None:
        return t.t(K.REMARK_TEMPERATURE_MISSING)
    return format_temperature(value, units, precise=True)


def _vis(value: Distance, units: UnitsMode) -> str:
    return format_visibility(value, units)


def _timing_segment(t: Translator, segment: TimingSegment) -> str:
    group = WeatherGroup(segment.intensity, segment.descriptor, segment.phenomena)
    events = [
        t.t(K.REMARK_BEGAN if event.began else K.REMARK_ENDED, time=_remark_time(t, event.time))
        for event in segment.events
    ]
    return t.t(K.REMARK_TIMING, weather=upper_first(describe_weather_group(t, group)), events=join_list(t, events))


def _lightning(t: Translator, item: Lightning) -> str:
    words: list[str] = []
    if item.frequency is not None:
        words.append(t.t(LIGHTNING_FREQUENCY_KEYS[item.frequency]))
    if item.types:
        words.append(join_list(t, [t.t(LIGHTNING_TYPE_KEYS[kind]) for kind in item.types]))
    words.append(t.t(K.REMARK_LIGHTNING).lower())
    base = upper_first(" ".join(words))
    if not item.location:
        return base
    place = " ".join(_free_word(t, word) or word for word in item.location)
    return t.t(K.REMARK_LIGHTNING_LOCATED, base=base, location=place)


def _cloud_types(t: Translator, item: CloudTypes) -> str:
    parts: list[str] = []
    if item.low is not None:
        parts.append(t.t(K.REMARK_CLOUD_TYPES_LOW, name=t.t(CLOUD_LOW_KEYS[item.low])))
    if item.middle is not None:
        parts.append(t.t(K.REMARK_CLOUD_TYPES_MIDDLE, name=t.t(CLOUD_MIDDLE_KEYS[item.middle])))
    if item.high is not None:
        parts.append(t.t(K.REMARK_CLOUD_TYPES_HIGH, name=t.t(CLOUD_HIGH_KEYS[item.high])))
    return t.t(K.REMARK_CLOUD_TYPES, parts="; ".join(parts) or t.t(K.REMARK_CLOUD_TYPE_UNKNOWN))


def _opacity(t: Translator, item: CloudOpacity) -> str:
    layers = []
    for layer in item.layers:
        name = t.t(OPACITY_CLOUD_KEYS[layer.cloud])
        if layer.trace or layer.eighths is None:
            layers.append(t.t(K.REMARK_OPACITY_TRACE, cloud=name))
        else:
            layers.append(t.t(K.REMARK_OPACITY_LAYER, cloud=name, eighths=layer.eighths))
    return t.t(K.REMARK_OPACITY, layers="; ".join(layers))


def _station_pressure(t: Translator, item: StationPressure) -> str:
    if item.mmhg is not None and item.hpa is not None:
        value = t.t(K.REMARK_STATION_PRESSURE_BOTH, mmhg=item.mmhg, hpa=item.hpa)
    elif item.mmhg is not None:
        value = t.t(K.REMARK_STATION_PRESSURE_MMHG, mmhg=item.mmhg)
    else:
        value = t.t(K.REMARK_STATION_PRESSURE_HPA, hpa=item.hpa)
    key = K.REMARK_STATION_PRESSURE_QFE if item.kind is StationPressureKind.QFE else K.REMARK_STATION_PRESSURE_QNH
    return t.t(key, value=value)


def _tendency(t: Translator, item: PressureTendency, units: UnitsMode) -> str:
    name = t.t(TENDENCY_NAME_KEYS[item.character])
    if item.direction is TendencyDirection.SAME:
        return t.t(K.REMARK_TENDENCY_SAME, name=name)
    change = format_pressure_change(item.change_hpa, units)
    key = K.REMARK_TENDENCY_HIGHER if item.direction is TendencyDirection.HIGHER else K.REMARK_TENDENCY_LOWER
    return t.t(key, change=change, name=name)


def describe_remark(t: Translator, remark: Remark, units: UnitsMode) -> str:
    """One decoded remark as a sentence fragment; ``FreeText`` has its known words spelled out."""
    match remark:
        case AutomatedStationType(precipitation_discriminator=discriminator):
            return t.t(K.REMARK_STATION_TYPE_AO2 if discriminator else K.REMARK_STATION_TYPE_AO1)
        case PeakWind(direction=direction, speed=speed, time=when):
            compass = t.t(COMPASS_KEYS[compass_point(direction)])
            return t.t(
                K.REMARK_PEAK_WIND,
                direction=f"{direction:03d}",
                compass=compass,
                speed=format_speed(speed, units),
                time=_remark_time(t, when),
            )
        case WindShift(time=when, frontal_passage=frontal):
            return t.t(K.REMARK_WIND_SHIFT_FRONTAL if frontal else K.REMARK_WIND_SHIFT, time=_remark_time(t, when))
        case TowerVisibility(distance=distance):
            return t.t(K.REMARK_TOWER_VISIBILITY, value=_vis(distance, units))
        case SurfaceVisibility(distance=distance):
            return t.t(K.REMARK_SURFACE_VISIBILITY, value=_vis(distance, units))
        case VariableVisibility(low=low, high=high):
            return t.t(K.REMARK_VARIABLE_VISIBILITY, low=_vis(low, units), high=_vis(high, units))
        case SectorVisibility(distance=distance, location=location):
            return t.t(K.REMARK_SECTOR_VISIBILITY, value=_vis(distance, units), where=_remark_place(t, location))
        case Lightning():
            return _lightning(t, remark)
        case WeatherTiming(segments=segments):
            return "; ".join(_timing_segment(t, segment) for segment in segments)
        case VariableCeiling(low=low, high=high):
            return t.t(
                K.REMARK_VARIABLE_CEILING,
                low=format_short_distance(low, units),
                high=format_short_distance(high, units),
            )
        case SecondaryCeiling(height=height, location=location):
            return t.t(
                K.REMARK_SECONDARY_CEILING, value=format_short_distance(height, units), where=_remark_place(t, location)
            )
        case PressureRapidChange(rising=rising):
            return t.t(K.REMARK_PRESSURE_RISING if rising else K.REMARK_PRESSURE_FALLING)
        case SeaLevelPressure(pressure=pressure):
            if pressure is None:
                return t.t(K.REMARK_SEA_LEVEL_PRESSURE_MISSING)
            return t.t(K.REMARK_SEA_LEVEL_PRESSURE, value=format_pressure(pressure, units, precise=True))
        case HourlyPrecipitation(inches=inches, trace=trace):
            return t.t(K.REMARK_HOURLY_PRECIPITATION, value=_inches(t, inches, units, trace=trace))
        case PeriodPrecipitation(inches=inches, hours=hours, trace=trace):
            key = {
                3: K.REMARK_PERIOD_PRECIPITATION_3,
                6: K.REMARK_PERIOD_PRECIPITATION_6,
            }.get(hours or 0, K.REMARK_PERIOD_PRECIPITATION_OTHER)
            return t.t(key, value=_inches(t, inches, units, trace=trace))
        case DailyPrecipitation(inches=inches, trace=trace):
            return t.t(K.REMARK_DAILY_PRECIPITATION, value=_inches(t, inches, units, trace=trace))
        case PreciseTemperature(temperature=temperature, dewpoint=dewpoint):
            if dewpoint is None:
                return t.t(K.REMARK_PRECISE_TEMPERATURE_ONLY, temperature=_temperature(t, temperature, units))
            return t.t(
                K.REMARK_PRECISE_TEMPERATURE,
                temperature=_temperature(t, temperature, units),
                dewpoint=_temperature(t, dewpoint, units),
            )
        case MaxTemperature6Hour(temperature=temperature):
            return t.t(K.REMARK_MAX_TEMPERATURE_6H, value=_temperature(t, temperature, units))
        case MinTemperature6Hour(temperature=temperature):
            return t.t(K.REMARK_MIN_TEMPERATURE_6H, value=_temperature(t, temperature, units))
        case DailyTemperatureExtremes(maximum=maximum, minimum=minimum):
            return t.t(
                K.REMARK_DAILY_TEMPERATURES,
                maximum=_temperature(t, maximum, units),
                minimum=_temperature(t, minimum, units),
            )
        case PressureTendency():
            return _tendency(t, remark, units)
        case SensorStatus(sensor=sensor, location=location):
            text = t.t(SENSOR_KEYS[sensor])
            if location is None:
                return text
            return t.t(K.REMARK_SENSOR_LOCATED, sensor=text, where=_remark_place(t, location))
        case MaintenanceIndicator():
            return t.t(K.REMARK_MAINTENANCE)
        case SnowDepth(inches=inches):
            if inches is None:
                return t.t(K.REMARK_SNOW_DEPTH_MISSING)
            return t.t(K.REMARK_SNOW_DEPTH, value=format_inches(inches, units))
        case SnowIncrease(last_hour_inches=hour, total_inches=total):
            return t.t(K.REMARK_SNOW_INCREASE, hour=format_inches(hour, units), total=format_inches(total, units))
        case CloudTypes():
            return _cloud_types(t, remark)
        case HailSize(inches=inches, less_than=less_than):
            return t.t(K.REMARK_HAIL_LESS if less_than else K.REMARK_HAIL, size=format_inches(inches, units))
        case DensityAltitude(altitude=altitude):
            return t.t(K.REMARK_DENSITY_ALTITUDE, value=format_short_distance(altitude, units))
        case CloudOpacity():
            return _opacity(t, remark)
        case StationPressure():
            return _station_pressure(t, remark)
        case AltimeterSetting(pressure=pressure):
            return t.t(K.REMARK_ALTIMETER, value=format_pressure(pressure, units))
        case RunwayWind(runway=runway, wind=wind, variation=variation):
            return t.t(K.REMARK_RUNWAY_WIND, runway=runway, wind=lower_first(describe_wind(t, wind, units, variation)))
        case WindAtHeight(height=height, wind=wind):
            return t.t(
                K.REMARK_WIND_AT_HEIGHT,
                height=format_short_distance(height, units),
                wind=lower_first(describe_wind(t, wind, units)),
            )
        case ColorStateRemark(group=group):
            return t.t(K.REMARK_COLOR_STATE, group=describe_color_state(t, group))
        case FreeText(text=text):
            return describe_free_text(t, text)
    return type(remark).__name__
