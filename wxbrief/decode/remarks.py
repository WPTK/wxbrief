"""Remarks: everything after ``RMK``.

``parse_remarks`` walks the remark tokens once. At each position it offers the tokens to the known patterns in turn
(automated station type, peak wind, sea-level pressure, the numeric temperature and precipitation groups ...); the
first parser that recognises a group decodes it into a ``Remark`` variant and tags the tokens it used. Tokens no
parser recognises are collected into ``FreeText`` remarks (consecutive ones form one remark), so every token stays
accounted for and nothing raises: a parser that fails counts as "no match" and the cursor is rewound.

Each pattern is a fixed-width code or a short token sequence; the one repeating shape (weather timing,
``DZB04E37RAB37``) is scanned in explicit steps rather than with a nested regex.

To add a remark variant, see "Adding a remark variant" in ``docs/decoding.md``.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from wxbrief.decode.groups.colorstate import parse_color_state_group
from wxbrief.decode.groups.wind import wind_from_text
from wxbrief.decode.model import (
    AutomatedStationType,
    CloudOpacity,
    CloudTypes,
    ColorStateRemark,
    DailyPrecipitation,
    DailyTemperatureExtremes,
    DensityAltitude,
    Descriptor,
    FreeText,
    HailSize,
    HourlyPrecipitation,
    Intensity,
    Lightning,
    LightningFrequency,
    LightningType,
    MaintenanceIndicator,
    MaxTemperature6Hour,
    MinTemperature6Hour,
    OpacityLayer,
    PeakWind,
    PeriodPrecipitation,
    PreciseTemperature,
    PressureRapidChange,
    PressureTendency,
    Remark,
    RemarkTime,
    RunwayWind,
    SeaLevelPressure,
    SecondaryCeiling,
    SectorVisibility,
    SemanticKind,
    SensorKind,
    SensorStatus,
    SnowDepth,
    SnowIncrease,
    StationPressure,
    StationPressureKind,
    SurfaceVisibility,
    TendencyDirection,
    TimingEvent,
    TimingSegment,
    TowerVisibility,
    VariableCeiling,
    VariableVisibility,
    WeatherTiming,
    WindShift,
    WindVariation,
)
from wxbrief.decode.tables import DESCRIPTOR_CODES, PHENOMENON_CODES
from wxbrief.decode.tokens import Cursor, Token
from wxbrief.decode.units import Distance, DistanceUnit, Pressure, PressureUnit, Speed, SpeedUnit, Temperature


@dataclass(frozen=True)
class Context:
    """What a remark parser may need to know about the report."""

    observed: datetime | None = None


Parser = Callable[[Cursor, Context], Remark | None]

# --- shared pieces ---------------------------------------------------------------------------------------------

_WHOLE = re.compile(r"^\d{1,2}$")
_FRACTION = re.compile(r"^\d{1,2}/\d{1,2}$")
_COMPASS = re.compile(r"^(?:N|NE|E|SE|S|SW|W|NW)$")
_COMPASS_RANGE = re.compile(r"^(?:N|NE|E|SE|S|SW|W|NW)(?:-(?:N|NE|E|SE|S|SW|W|NW))+$")
_RUNWAY = re.compile(r"^RWY\d{2}[LCR]?$")
_LOCATION_WORDS = frozenset({"DSNT", "VC", "OHD", "OVHD", "OVR", "ALQDS"})


def synoptic_hour(observed: datetime | None) -> int | None:
    """The UTC hour a report belongs to for the 3- and 6-hourly groups: the nearest hour (a ``:56`` report is the next
    hour's)."""
    if observed is None:
        return None
    return (observed + timedelta(minutes=30)).hour


def _fraction_text(text: str) -> float | None:
    """``"3/4"`` -> 0.75, ``"2"`` -> 2.0; ``None`` for a zero denominator."""
    if "/" not in text:
        return float(int(text))
    numerator, denominator = text.split("/")
    if int(denominator) == 0:
        return None
    return int(numerator) / int(denominator)


def _take_miles(cur: Cursor, kind: SemanticKind) -> float | None:
    """Consume a statute-mile value (``2``, ``3/4``, ``1 1/2``) and return it, or ``None`` leaving the cursor alone."""
    first = cur.peek()
    if first is None:
        return None
    if _WHOLE.match(first.text):
        second = cur.peek(1)
        if second is not None and _FRACTION.match(second.text):
            part = _fraction_text(second.text)
            if part is None:
                return None
            cur.take(kind)
            cur.take(kind)
            return int(first.text) + part
        cur.take(kind)
        return float(int(first.text))
    if _FRACTION.match(first.text):
        value = _fraction_text(first.text)
        if value is None:
            return None
        cur.take(kind)
        return value
    return None


def _miles(value: float) -> Distance:
    return Distance(value, DistanceUnit.SM)


def _remark_time(text: str) -> RemarkTime | None:
    """``30`` (minutes past the hour) or ``1715`` (hour and minute)."""
    if len(text) == 2 and text.isdigit() and int(text) <= 59:
        return RemarkTime(int(text))
    if len(text) == 4 and text.isdigit() and int(text[:2]) <= 23 and int(text[2:]) <= 59:
        return RemarkTime(int(text[2:]), int(text[:2]))
    return None


def _tenths(sign: str, digits: str) -> Temperature:
    """``("1", "017")`` -> -1.7 °C."""
    value = round(int(digits) / 10, 1)
    return Temperature(-value if sign == "1" else value)


def _hundredths(text: str) -> float | None:
    return None if "/" in text else int(text) / 100


def _location(cur: Cursor, kind: SemanticKind) -> str | None:
    """A runway (``RWY11``) or compass sector at the cursor, consumed with the given kind."""
    token = cur.peek()
    if token is not None and (_RUNWAY.match(token.text) or _COMPASS.match(token.text)):
        cur.take(kind)
        return token.text
    return None


# --- parsers, one per remark variant ---------------------------------------------------------------------------


def _station_type(cur: Cursor, _ctx: Context) -> Remark | None:
    token = cur.peek()
    if token is None or token.text not in ("AO1", "AO2"):
        return None
    cur.take(SemanticKind.REMARK)
    return AutomatedStationType(precipitation_discriminator=token.text == "AO2")


_PEAK = re.compile(r"^(?P<dir>\d{3})(?P<spd>\d{2,3})/(?P<time>\d{2}|\d{4})$")


def _peak_wind(cur: Cursor, _ctx: Context) -> Remark | None:
    first, second, third = cur.peek(), cur.peek(1), cur.peek(2)
    if first is None or second is None or third is None or first.text != "PK" or second.text != "WND":
        return None
    match = _PEAK.match(third.text)
    if match is None or int(match.group("dir")) > 360:
        return None
    when = _remark_time(match.group("time"))
    if when is None:
        return None
    for _ in range(3):
        cur.take(SemanticKind.WIND)
    return PeakWind(int(match.group("dir")), Speed(int(match.group("spd")), SpeedUnit.KT), when)


def _wind_shift(cur: Cursor, _ctx: Context) -> Remark | None:
    first, second = cur.peek(), cur.peek(1)
    if first is None or second is None or first.text != "WSHFT":
        return None
    when = _remark_time(second.text)
    if when is None:
        return None
    cur.take(SemanticKind.WIND)
    cur.take(SemanticKind.WIND)
    third = cur.peek()
    frontal = third is not None and third.text == "FROPA"
    if frontal:
        cur.take(SemanticKind.WIND)
    return WindShift(when, frontal)


def _tower_surface_visibility(cur: Cursor, _ctx: Context) -> Remark | None:
    first, second = cur.peek(), cur.peek(1)
    if first is None or second is None or first.text not in ("TWR", "SFC") or second.text != "VIS":
        return None
    mark = cur.mark()
    cur.take(SemanticKind.VISIBILITY)
    cur.take(SemanticKind.VISIBILITY)
    value = _take_miles(cur, SemanticKind.VISIBILITY)
    if value is None:
        cur.reset(mark)
        return None
    return TowerVisibility(_miles(value)) if first.text == "TWR" else SurfaceVisibility(_miles(value))


_VARIABLE = re.compile(r"^(?P<lo>\d{1,2}(?:/\d{1,2})?)V(?P<hi>\d{1,2}(?:/\d{1,2})?)$")


def _vis_remark(cur: Cursor, _ctx: Context) -> Remark | None:
    """``VIS 3/4V1 1/2`` (variable), ``VIS NE 2 1/2`` (sector) and ``VIS 3/4 RWY11`` (second location)."""
    first = cur.peek()
    if first is None or first.text != "VIS":
        return None
    mark = cur.mark()
    cur.take(SemanticKind.VISIBILITY)

    # Variable: "VIS 3/4V1 1/2" or "VIS 1 1/2V2".
    token = cur.peek()
    if token is None:
        cur.reset(mark)
        return None
    lead = 0.0
    following = cur.peek(1)
    if _WHOLE.match(token.text) and following is not None and _VARIABLE.match(following.text):
        lead = float(int(token.text))
        cur.take(SemanticKind.VISIBILITY)
        token = following
    match = _VARIABLE.match(token.text)
    if match is not None:
        low, high = _fraction_text(match.group("lo")), _fraction_text(match.group("hi"))
        if low is not None and high is not None:
            cur.take(SemanticKind.VISIBILITY)
            extra = cur.peek()
            if "/" not in match.group("hi") and extra is not None and _FRACTION.match(extra.text):
                part = _fraction_text(extra.text)
                if part is not None:
                    cur.take(SemanticKind.VISIBILITY)
                    high += part
            return VariableVisibility(_miles(lead + low), _miles(high))
        cur.reset(mark)
        return None

    # Sector: "VIS NE 2 1/2".
    if _COMPASS.match(token.text):
        sector = token.text
        cur.take(SemanticKind.VISIBILITY)
        value = _take_miles(cur, SemanticKind.VISIBILITY)
        if value is not None:
            return SectorVisibility(_miles(value), sector)
        cur.reset(mark)
        return None

    # Second location: "VIS 3/4 RWY11".
    value = _take_miles(cur, SemanticKind.VISIBILITY)
    if value is not None:
        place = _location(cur, SemanticKind.VISIBILITY)
        if place is not None:
            return SectorVisibility(_miles(value), place)
    cur.reset(mark)
    return None


_FREQUENCIES = {member.value: member for member in LightningFrequency}
_LIGHTNING_TYPES = re.compile(r"(IC|CC|CG|CA)")
_LTG_WORD = re.compile(r"^LTG(?P<types>(?:IC|CC|CG|CA)*)$")
_TYPE_RUN = re.compile(r"^(?:IC|CC|CG|CA)+$")


def _lightning_types(text: str) -> tuple[LightningType, ...]:
    return tuple(LightningType(code) for code in _LIGHTNING_TYPES.findall(text))


def _lightning(cur: Cursor, _ctx: Context) -> Remark | None:
    first = cur.peek()
    if first is None:
        return None
    mark = cur.mark()
    frequency = _FREQUENCIES.get(first.text)
    if frequency is not None:
        cur.take(SemanticKind.WEATHER)
    word = cur.peek()
    match = _LTG_WORD.match(word.text) if word is not None else None
    if match is None:
        cur.reset(mark)
        return None
    cur.take(SemanticKind.WEATHER)
    types = list(_lightning_types(match.group("types")))
    while (token := cur.peek()) is not None and _TYPE_RUN.match(token.text):
        cur.take(SemanticKind.WEATHER)
        types.extend(_lightning_types(token.text))
    words: list[str] = []
    while (token := cur.peek()) is not None:
        if token.text in _LOCATION_WORDS or _COMPASS.match(token.text) or _COMPASS_RANGE.match(token.text):
            words.append(token.text)
            cur.take(SemanticKind.WEATHER)
            continue
        after = cur.peek(1)
        if (
            token.text == "AND"
            and words
            and after is not None
            and (_COMPASS.match(after.text) or _COMPASS_RANGE.match(after.text))
        ):
            words.append(token.text)
            cur.take(SemanticKind.WEATHER)
            continue
        break
    return Lightning(frequency, tuple(types), tuple(words))


_TIMING_HEAD = re.compile(
    r"(?P<pre>[-+])?(?P<desc>MI|PR|BC|DR|BL|SH|TS|FZ)?(?P<phen>(?:DZ|RA|SN|SG|IC|PL|GR|GS|UP)*)(?=[BE]\d)"
)
_TIMING_EVENT = re.compile(r"(?P<kind>[BE])(?P<hh>\d{2})(?P<mm>\d{2})?")
_INTENSITIES = {"-": Intensity.LIGHT, "+": Intensity.HEAVY}


def _timing_segments(text: str) -> tuple[TimingSegment, ...] | None:
    """Scan ``RAB07E45``, ``TSB0159E30`` or ``DZB04E37RAB37`` in explicit steps; ``None`` if it is not one."""
    position = 0
    segments: list[TimingSegment] = []
    while position < len(text):
        head = _TIMING_HEAD.match(text, position)
        if head is None:
            return None
        phen = head.group("phen")
        phenomena = tuple(PHENOMENON_CODES[phen[i : i + 2]] for i in range(0, len(phen), 2))
        descriptor = DESCRIPTOR_CODES.get(head.group("desc") or "")
        if not phenomena and descriptor is not Descriptor.TS:
            return None
        position = head.end()
        events: list[TimingEvent] = []
        while (event := _TIMING_EVENT.match(text, position)) is not None:
            if event.group("mm") is None:
                when = _remark_time(event.group("hh"))
            else:
                when = _remark_time(event.group("hh") + event.group("mm"))
            if when is None:
                return None
            events.append(TimingEvent(event.group("kind") == "B", when))
            position = event.end()
        if not events:
            return None
        intensity = _INTENSITIES.get(head.group("pre") or "", Intensity.MODERATE)
        segments.append(TimingSegment(intensity, descriptor, phenomena, tuple(events)))
    return tuple(segments) or None


def _weather_timing(cur: Cursor, _ctx: Context) -> Remark | None:
    token = cur.peek()
    if token is None or len(token.text) < 4 or len(token.text) > 40:
        return None
    segments = _timing_segments(token.text)
    if segments is None:
        return None
    cur.take(SemanticKind.WEATHER)
    return WeatherTiming(segments)


_CIG_VARIABLE = re.compile(r"^(?P<lo>\d{3})V(?P<hi>\d{3})$")


def _ceiling(cur: Cursor, _ctx: Context) -> Remark | None:
    first, second = cur.peek(), cur.peek(1)
    if first is None or second is None or first.text != "CIG":
        return None
    variable = _CIG_VARIABLE.match(second.text)
    if variable is not None:
        cur.take(SemanticKind.SKY)
        cur.take(SemanticKind.SKY)
        return VariableCeiling(
            Distance(int(variable.group("lo")) * 100, DistanceUnit.FT),
            Distance(int(variable.group("hi")) * 100, DistanceUnit.FT),
        )
    if len(second.text) == 3 and second.text.isdigit():
        mark = cur.mark()
        cur.take(SemanticKind.SKY)
        cur.take(SemanticKind.SKY)
        place = _location(cur, SemanticKind.SKY)
        if place is not None:
            return SecondaryCeiling(Distance(int(second.text) * 100, DistanceUnit.FT), place)
        cur.reset(mark)
    return None


def _pressure_rapid(cur: Cursor, _ctx: Context) -> Remark | None:
    token = cur.peek()
    if token is None or token.text not in ("PRESRR", "PRESFR"):
        return None
    cur.take(SemanticKind.PRESSURE)
    return PressureRapidChange(rising=token.text == "PRESRR")


_SLP = re.compile(r"^SLP(?P<v>\d{3})$")


def _sea_level_pressure(cur: Cursor, _ctx: Context) -> Remark | None:
    token = cur.peek()
    if token is None:
        return None
    if token.text in ("SLPNO", "SLP///"):
        cur.take(SemanticKind.PRESSURE)
        return SeaLevelPressure(None)
    match = _SLP.match(token.text)
    if match is None:
        return None
    digits = match.group("v")
    # The leading 9 or 10 is dropped: 5xx-9xx are 95x-99x hPa, 0xx-4xx are 100x-104x hPa.
    base = 900 if int(digits[0]) >= 5 else 1000
    cur.take(SemanticKind.PRESSURE)
    return SeaLevelPressure(Pressure(round(base + int(digits) / 10, 1), PressureUnit.HPA))


_HOURLY = re.compile(r"^P(?P<v>\d{4}|////)$")
_PERIOD = re.compile(r"^6(?P<v>\d{4}|////)$")
_DAILY = re.compile(r"^7(?P<v>\d{4}|////)$")


def _hourly_precipitation(cur: Cursor, _ctx: Context) -> Remark | None:
    token = cur.peek()
    match = _HOURLY.match(token.text) if token is not None else None
    if match is None:
        return None
    cur.take(SemanticKind.WEATHER)
    value = _hundredths(match.group("v"))
    return HourlyPrecipitation(value, trace=value == 0)


def _period_precipitation(cur: Cursor, ctx: Context) -> Remark | None:
    token = cur.peek()
    match = _PERIOD.match(token.text) if token is not None else None
    if match is None:
        return None
    hour = synoptic_hour(ctx.observed)
    hours = None
    if hour is not None:
        hours = 6 if hour % 6 == 0 else 3 if hour % 3 == 0 else None
    cur.take(SemanticKind.WEATHER)
    value = _hundredths(match.group("v"))
    return PeriodPrecipitation(value, hours, trace=value == 0)


def _daily_precipitation(cur: Cursor, _ctx: Context) -> Remark | None:
    token = cur.peek()
    match = _DAILY.match(token.text) if token is not None else None
    if match is None:
        return None
    cur.take(SemanticKind.WEATHER)
    value = _hundredths(match.group("v"))
    return DailyPrecipitation(value, trace=value == 0)


_T_GROUP = re.compile(r"^T(?P<ts>[01])(?P<t>\d{3})(?:(?P<ds>[01])(?P<d>\d{3}))?$")
_SIX_HOUR_MAX = re.compile(r"^1(?:(?P<s>[01])(?P<v>\d{3})|////)$")
_SIX_HOUR_MIN = re.compile(r"^2(?:(?P<s>[01])(?P<v>\d{3})|////)$")
_DAILY_EXTREMES = re.compile(r"^4(?P<xs>[01])(?P<x>\d{3})(?P<ns>[01])(?P<n>\d{3})$")


def _precise_temperature(cur: Cursor, _ctx: Context) -> Remark | None:
    token = cur.peek()
    match = _T_GROUP.match(token.text) if token is not None else None
    if match is None:
        return None
    cur.take(SemanticKind.TEMPERATURE)
    dewpoint = _tenths(match.group("ds"), match.group("d")) if match.group("d") else None
    return PreciseTemperature(_tenths(match.group("ts"), match.group("t")), dewpoint)


def _six_hour_maximum(cur: Cursor, _ctx: Context) -> Remark | None:
    token = cur.peek()
    match = _SIX_HOUR_MAX.match(token.text) if token is not None else None
    if match is None:
        return None
    cur.take(SemanticKind.TEMPERATURE)
    return MaxTemperature6Hour(_tenths(match.group("s"), match.group("v")) if match.group("v") else None)


def _six_hour_minimum(cur: Cursor, _ctx: Context) -> Remark | None:
    token = cur.peek()
    match = _SIX_HOUR_MIN.match(token.text) if token is not None else None
    if match is None:
        return None
    cur.take(SemanticKind.TEMPERATURE)
    return MinTemperature6Hour(_tenths(match.group("s"), match.group("v")) if match.group("v") else None)


def _daily_extremes(cur: Cursor, _ctx: Context) -> Remark | None:
    token = cur.peek()
    match = _DAILY_EXTREMES.match(token.text) if token is not None else None
    if match is None:
        return None
    cur.take(SemanticKind.TEMPERATURE)
    return DailyTemperatureExtremes(
        _tenths(match.group("xs"), match.group("x")), _tenths(match.group("ns"), match.group("n"))
    )


_TENDENCY = re.compile(r"^5(?P<a>[0-8])(?P<ppp>\d{3})$")


def _pressure_tendency(cur: Cursor, _ctx: Context) -> Remark | None:
    token = cur.peek()
    match = _TENDENCY.match(token.text) if token is not None else None
    if match is None:
        return None
    character = int(match.group("a"))
    if character <= 3:
        direction = TendencyDirection.HIGHER
    elif character == 4:
        direction = TendencyDirection.SAME
    else:
        direction = TendencyDirection.LOWER
    cur.take(SemanticKind.PRESSURE)
    return PressureTendency(character, direction, int(match.group("ppp")) / 10)


_SENSORS = {kind.value: kind for kind in SensorKind}
_LOCATED_SENSORS = frozenset({SensorKind.VISIBILITY, SensorKind.CEILING})


def _sensor_status(cur: Cursor, _ctx: Context) -> Remark | None:
    token = cur.peek()
    sensor = _SENSORS.get(token.text) if token is not None else None
    if sensor is None:
        return None
    cur.take(SemanticKind.REMARK)
    place = _location(cur, SemanticKind.REMARK) if sensor in _LOCATED_SENSORS else None
    return SensorStatus(sensor, place)


def _maintenance(cur: Cursor, _ctx: Context) -> Remark | None:
    token = cur.peek()
    if token is None or token.text != "$":
        return None
    cur.take(SemanticKind.REMARK)
    return MaintenanceIndicator()


_SNOW_DEPTH = re.compile(r"^4/(?P<v>\d{3}|///)$")


def _snow_depth(cur: Cursor, _ctx: Context) -> Remark | None:
    token = cur.peek()
    match = _SNOW_DEPTH.match(token.text) if token is not None else None
    if match is None:
        return None
    cur.take(SemanticKind.WEATHER)
    return SnowDepth(None if "/" in match.group("v") else float(int(match.group("v"))))


_SNINCR = re.compile(r"^(?P<hour>\d{1,3})/(?P<total>\d{1,3})$")


def _snow_increase(cur: Cursor, _ctx: Context) -> Remark | None:
    first, second = cur.peek(), cur.peek(1)
    if first is None or second is None or first.text != "SNINCR":
        return None
    match = _SNINCR.match(second.text)
    if match is None:
        return None
    cur.take(SemanticKind.WEATHER)
    cur.take(SemanticKind.WEATHER)
    return SnowIncrease(float(int(match.group("hour"))), float(int(match.group("total"))))


_CLOUD_TYPES = re.compile(r"^8/(?P<l>[\d/])(?P<m>[\d/])(?P<h>[\d/])$")


def _cloud_types(cur: Cursor, _ctx: Context) -> Remark | None:
    token = cur.peek()
    match = _CLOUD_TYPES.match(token.text) if token is not None else None
    if match is None:
        return None

    def digit(text: str) -> int | None:
        return int(text) if text.isdigit() else None

    cur.take(SemanticKind.SKY)
    return CloudTypes(digit(match.group("l")), digit(match.group("m")), digit(match.group("h")))


def _hail_size(cur: Cursor, _ctx: Context) -> Remark | None:
    first = cur.peek()
    if first is None or first.text != "GR":
        return None
    mark = cur.mark()
    cur.take(SemanticKind.WEATHER)
    less_than = False
    second, third = cur.peek(), cur.peek(1)
    if second is not None and third is not None and second.text == "LESS" and third.text == "THAN":
        cur.take(SemanticKind.WEATHER)
        cur.take(SemanticKind.WEATHER)
        less_than = True
    value = _take_miles(cur, SemanticKind.WEATHER)
    if value is None:
        cur.reset(mark)
        return None
    return HailSize(value, less_than)


_FEET = re.compile(r"^(?P<v>\d{3,5})(?:FT)?$")


def _density_altitude(cur: Cursor, _ctx: Context) -> Remark | None:
    first, second, third = cur.peek(), cur.peek(1), cur.peek(2)
    if first is None or second is None or third is None:
        return None
    if first.text != "DENSITY" or second.text not in ("ALT", "ALTITUDE"):
        return None
    match = _FEET.match(third.text)
    if match is None:
        return None
    for _ in range(3):
        cur.take(SemanticKind.REMARK)
    return DensityAltitude(Distance(int(match.group("v")), DistanceUnit.FT))


_CLOUD_WORD = r"TCU|ACC|CU|CB|SC|ST|SF|CF|AC|AS|NS|CI|CC|CS"
_OPACITY_UNIT = re.compile(rf"(?P<cloud>{_CLOUD_WORD})(?P<eighths>\d)")
_CLOUD_ONLY = re.compile(rf"^(?:{_CLOUD_WORD})$")


def _opacity_layers(text: str) -> list[OpacityLayer] | None:
    """Split ``SC5AC2`` into layers; ``None`` unless the whole token is made of cloud+digit units."""
    layers: list[OpacityLayer] = []
    position = 0
    while position < len(text):
        unit = _OPACITY_UNIT.match(text, position)
        if unit is None:
            return None
        layers.append(OpacityLayer(unit.group("cloud"), int(unit.group("eighths"))))
        position = unit.end()
    return layers or None


def _cloud_opacity(cur: Cursor, _ctx: Context) -> Remark | None:
    layers: list[OpacityLayer] = []
    while (token := cur.peek()) is not None:
        found = _opacity_layers(token.text)
        if found is not None:
            cur.take(SemanticKind.SKY)
            layers.extend(found)
            continue
        after = cur.peek(1)
        if _CLOUD_ONLY.match(token.text) and after is not None and after.text == "TR":
            cur.take(SemanticKind.SKY)
            cur.take(SemanticKind.SKY)
            layers.append(OpacityLayer(token.text, None, trace=True))
            continue
        break
    return CloudOpacity(tuple(layers)) if layers else None


_STATION_PRESSURE = re.compile(r"^(?P<kind>QFE|QNH)(?P<a>\d{3,4})(?:/(?P<b>\d{3,4}))?$")
_MMHG_LIMIT = 900  # a lone value below this is millimetres of mercury, at or above it hectopascals


def _station_pressure(cur: Cursor, _ctx: Context) -> Remark | None:
    token = cur.peek()
    match = _STATION_PRESSURE.match(token.text) if token is not None else None
    if match is None:
        return None
    kind = StationPressureKind(match.group("kind"))
    first = int(match.group("a"))
    second = match.group("b")
    cur.take(SemanticKind.PRESSURE)
    if second is not None:
        return StationPressure(kind, mmhg=first, hpa=int(second))
    if first >= _MMHG_LIMIT:
        return StationPressure(kind, hpa=first)
    return StationPressure(kind, mmhg=first)


_RUNWAY_WIND_SLASH = re.compile(r"^R(?P<rwy>\d{2}[LCR]?)/(?P<wind>\S+)$")
_RUNWAY_WORD = re.compile(r"^RWY(?P<rwy>\d{2}[LCR]?)$")
_VARIATION = re.compile(r"^(\d{3})V(\d{3})$")


def _runway_wind(cur: Cursor, _ctx: Context) -> Remark | None:
    """``R06/31003MPS`` (one token) or ``RWY17L 02008KT [310V110]``."""
    token = cur.peek()
    if token is None:
        return None
    slash = _RUNWAY_WIND_SLASH.match(token.text)
    word = _RUNWAY_WORD.match(token.text)
    following = cur.peek(1)
    if slash is not None:
        wind = wind_from_text(slash.group("wind"))
        runway = slash.group("rwy")
        used = 1
    elif word is not None and following is not None:
        wind = wind_from_text(following.text)
        runway = word.group("rwy")
        used = 2
    else:
        return None
    if wind is None:
        return None
    for _ in range(used):
        cur.take(SemanticKind.WIND)
    variation = None
    extra = cur.peek()
    match = _VARIATION.match(extra.text) if extra is not None else None
    if match is not None and int(match.group(1)) <= 360 and int(match.group(2)) <= 360:
        cur.take(SemanticKind.WIND)
        variation = WindVariation(int(match.group(1)), int(match.group(2)))
    return RunwayWind(runway, wind, variation)


def _color_state(cur: Cursor, _ctx: Context) -> Remark | None:
    group = parse_color_state_group(cur)
    return None if group is None else ColorStateRemark(group)


# Order matters only where two patterns could claim the same token; the more specific one comes first.
_PARSERS: tuple[Parser, ...] = (
    _station_type,
    _peak_wind,
    _wind_shift,
    _tower_surface_visibility,
    _vis_remark,
    _lightning,
    _weather_timing,
    _ceiling,
    _pressure_rapid,
    _sea_level_pressure,
    _hourly_precipitation,
    _period_precipitation,
    _daily_precipitation,
    _precise_temperature,
    _six_hour_maximum,
    _six_hour_minimum,
    _daily_extremes,
    _pressure_tendency,
    _sensor_status,
    _maintenance,
    _snow_depth,
    _snow_increase,
    _cloud_types,
    _hail_size,
    _density_altitude,
    _station_pressure,
    _runway_wind,
    _color_state,
    _cloud_opacity,
)


def parse_remarks(cur: Cursor, ctx: Context) -> list[Remark]:
    """Decode every remark from the cursor to the end of the tokens, tagging them.

    A token the known patterns do not claim becomes part of a ``FreeText`` remark and is tagged ``REMARK``; the
    report terminator is tagged ``TERMINATOR``. Never raises: a parser that fails is skipped for that position.
    """
    remarks: list[Remark] = []
    pending: list[Token] = []

    def flush() -> None:
        if pending:
            remarks.append(FreeText(" ".join(token.text for token in pending)))
            pending.clear()

    while (token := cur.peek()) is not None:
        if token.kind is SemanticKind.TERMINATOR:
            cur.take(SemanticKind.TERMINATOR)
            continue
        decoded: Remark | None = None
        for parser in _PARSERS:
            mark = cur.mark()
            try:
                decoded = parser(cur, ctx)
            except Exception:
                decoded = None
            if decoded is not None:
                break
            cur.reset(mark)
        if decoded is not None:
            flush()
            remarks.append(decoded)
        else:
            pending.append(cur.take(SemanticKind.REMARK))
    flush()
    return remarks
