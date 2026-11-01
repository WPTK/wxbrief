"""Discord code blocks: the METAR and TAF layouts of the metar-taf-decode notes.

The message is a plain code block (monospace, no Discord markup). ``discord_block`` returns exactly what is pasted into
Discord, a block fenced with three backticks; ``render_discord`` wraps that in an outer fence of four backticks, which
keeps the inner triple backticks visible and selectable in a chat that renders markdown (copy everything inside the
outer fence, backticks included). Only lines that exist in the report appear.

METAR::

    [emoji] KJAX — JACKSONVILLE INTL AIRPORT
    Obs: 22:56 UTC (112256Z)  — AUTO

    Wind: 170° @ 5 kt (S)
    Visibility: 10 SM
    Temperature: 75.0°F (23.9°C) | Dewpoint: 68.0°F (20.0°C)
    Altimeter: 30.03 inHg

    Clouds: Few clouds at 3,000 ft
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    Pressure: 1017.0 mb (falling -0.8 mb/3hr)

TAF: a header, a divider, then one block per period headed ``BASE``, ``FROM``, ``BECMG``, ``TEMPO``, ``PROB30`` ...
with the elements that period states, its flight category in brackets.

The header emoji follows the dominant condition (``Metar.condition``: thunderstorm, snow, rain, obscuration, overcast,
broken, partly cloudy, clear). Times are UTC; the station's local time and airport name arrive with the station
database (``station_name`` and ``daylight`` are the hooks). Temperatures follow ``units``.
"""

from __future__ import annotations

from datetime import datetime

from wxbrief.decode.derived import refine_clear
from wxbrief.decode.model import (
    ChangeType,
    Condition,
    ForecastElements,
    MaxTemperature6Hour,
    Metar,
    MinTemperature6Hour,
    Modifier,
    PeakWind,
    PreciseTemperature,
    PressureTendency,
    SeaLevelPressure,
    SemanticKind,
    Taf,
    TafPeriod,
    TendencyDirection,
    Wind,
    WindVariation,
)
from wxbrief.decode.tables import COMPASS_KEYS, DISCORD_HEADING_KEYS, compass_point
from wxbrief.decode.units import Temperature, UnitsMode
from wxbrief.i18n import Translator
from wxbrief.i18n.keys import K
from wxbrief.render import phrases
from wxbrief.render.measure import format_speed, format_temperature
from wxbrief.render.plain import warning_lines

DIVIDER = "━" * 32
INNER_FENCE = "```"
OUTER_FENCE = "````"
MESSAGE_LIMIT = 2000  # characters in one Discord message
# What is left for the lines of one block once both fences and their line breaks are counted (the outer fence is
# included so a block still fits when it is shown inside one).
BODY_LIMIT = MESSAGE_LIMIT - 2 * (len(OUTER_FENCE) + 1) - 2 * (len(INNER_FENCE) + 1)
CAUTION = "⚠️"
TAF_EMOJI = "\U0001f4cb"
NO_CONDITION_EMOJI = "\U0001f321️"

CONDITION_EMOJI: dict[Condition, str] = {
    Condition.TORNADO: "\U0001f32a️",
    Condition.THUNDERSTORM: "⛈️",
    Condition.SQUALL: "\U0001f4a8",
    Condition.SNOW: "\U0001f328️",
    Condition.RAIN: "\U0001f327️",
    Condition.OBSCURATION: "\U0001f32b️",
    Condition.OVERCAST: "☁️",
    Condition.BROKEN: "\U0001f325️",
    Condition.PARTLY_CLOUDY: "\U0001f324️",
    Condition.CLEAR: "☀️",
    Condition.CLEAR_DAY: "☀️",
    Condition.CLEAR_NIGHT: "\U0001f319",
}

def condition_emoji(condition: Condition | None, daylight: bool | None = None) -> str:
    """The header emoji; a clear sky is a sun or a moon once it is known whether the sun is up (a sun until then)."""
    if condition is None:
        return NO_CONDITION_EMOJI
    if daylight is not None:
        condition = refine_clear(condition, daylight) or condition
    return CONDITION_EMOJI[condition]


# --- shared pieces -----------------------------------------------------------------------------------------------


def _temperature(t: Translator, value: Temperature, units: UnitsMode, *, precise: bool = False) -> str:
    """``75.9°F``: the degree sign sits against the number in this layout."""
    return format_temperature(value, units, t.numbers, precise=precise).replace(" °", "°")


def _clock(moment: datetime) -> str:
    return moment.strftime("%H:%M")


def _group(moment: datetime) -> str:
    """``DD/HHMMZ``: the day and time the way a TAF writes them."""
    return f"{moment:%d}/{moment:%H%M}Z"


def _title(emoji: str, station: str | None, name: str | None) -> str:
    text = f"{emoji} {station or ''}".rstrip()
    return f"{text} — {name.upper()}" if name else text


def _wind(t: Translator, wind: Wind, units: UnitsMode, variation: WindVariation | None = None) -> str:
    if wind.speed is None:
        return t.t(K.WIND_NOT_REPORTED)
    if wind.calm:
        return t.t(K.WIND_CALM)
    speed = format_speed(wind.speed, units, t.numbers)
    gust = format_speed(wind.gust, units, t.numbers) if wind.gust is not None else None
    if wind.gust_above and gust is not None:
        gust = t.t(K.COMMON_MORE_THAN, value=gust)
    if wind.speed_above:
        speed = t.t(K.COMMON_MORE_THAN, value=speed)
    if wind.variable:
        key = K.DISCORD_WIND_VARIABLE_GUST if gust else K.DISCORD_WIND_VARIABLE
        text = t.t(key, speed=speed, gust=gust)
    elif wind.direction is None:
        key = K.DISCORD_WIND_NO_DIRECTION_GUST if gust else K.DISCORD_WIND_NO_DIRECTION
        text = t.t(key, speed=speed, gust=gust)
    else:
        compass = t.t(COMPASS_KEYS[compass_point(wind.direction)])
        key = K.DISCORD_WIND_STEADY_GUST if gust else K.DISCORD_WIND_STEADY
        text = t.t(key, direction=f"{wind.direction:03d}", speed=speed, gust=gust, compass=compass)
    if variation is not None:
        start, end = f"{variation.start:03d}", f"{variation.end:03d}"
        text = t.t(K.DISCORD_WIND_VARIATION, base=text, from_deg=start, to_deg=end)
    return text


def _layers(t: Translator, elements: ForecastElements, units: UnitsMode) -> str:
    return "; ".join(phrases.describe_cloud_layer(t, layer, units) for layer in elements.sky)


def _elements_lines(t: Translator, elements: ForecastElements, units: UnitsMode) -> list[str]:
    """The lines for the elements a TAF period (or a trend) states: wind, visibility in weather, clouds, extras."""
    lines: list[str] = []
    if elements.wind is not None:
        lines.append(t.t(K.DISCORD_WIND, value=_wind(t, elements.wind, units)))
    weather = t.lower_first(phrases.describe_weather(t, elements.weather)) if elements.weather else ""
    if elements.visibility is not None:
        if elements.visibility.cavok:
            value = t.t(K.DISCORD_CAVOK)
        else:
            value = phrases.describe_visibility(t, elements.visibility, units)
            if weather:
                value = t.t(K.DISCORD_VISIBILITY_IN, visibility=value, weather=weather)
        lines.append(t.t(K.DISCORD_VISIBILITY, value=value))
    elif weather:
        lines.append(t.t(K.DISCORD_WEATHER, value=weather))
    if elements.sky:
        lines.append(t.t(K.DISCORD_CLOUDS, value=_layers(t, elements, units)))
    if elements.color_state is not None:
        lines.append(t.t(K.DISCORD_COLOR_STATE, value=phrases.describe_color_code(t, elements.color_state)))
    if elements.wind_shear is not None:
        value = phrases.describe_wind_shear_layer(t, elements.wind_shear, units)
        lines.append(t.t(K.DISCORD_WIND_SHEAR, value=value))
    if elements.altimeter is not None:
        lines.append(t.t(K.DISCORD_ALTIMETER, value=phrases.describe_pressure(t, elements.altimeter, units)))
    lines.extend(t.t(K.DISCORD_ICING, value=phrases.describe_icing(t, item, units)) for item in elements.icing)
    for item in elements.turbulence:
        lines.append(t.t(K.DISCORD_TURBULENCE, value=phrases.describe_turbulence(t, item, units)))
    return lines


# --- METAR -----------------------------------------------------------------------------------------------------


def _metar_notes(t: Translator, metar: Metar) -> str:
    notes: list[str] = []
    if Modifier.AUTO in metar.modifiers:
        notes.append(t.t(K.DISCORD_AUTO))
    if {Modifier.COR, Modifier.CCA, Modifier.CCB, Modifier.CCC} & set(metar.modifiers):
        notes.append(f"{CAUTION} {t.t(K.DISCORD_CORRECTED)}")
    if Modifier.NIL in metar.modifiers:
        notes.append(t.t(K.DISCORD_NIL))
    return "".join(f"  — {note}" for note in notes)


def _first_time_group(report: Metar | Taf) -> str | None:
    """The report's own ``DDHHMMZ`` text."""
    for token in report.tokens:
        if token.kind is SemanticKind.TIME and token.text.endswith("Z"):
            return token.text
    return None


def _tendency(t: Translator, remark: PressureTendency) -> str:
    if remark.direction is TendencyDirection.SAME or remark.change_hpa == 0:
        return t.t(K.DISCORD_TENDENCY_STEADY)
    if remark.direction is TendencyDirection.HIGHER:
        return t.t(K.DISCORD_TENDENCY_RISING, change="+" + t.numbers.fixed(remark.change_hpa, 1))
    return t.t(K.DISCORD_TENDENCY_FALLING, change="-" + t.numbers.fixed(remark.change_hpa, 1))


def _metar_lines(
    metar: Metar, t: Translator, units: UnitsMode, station_name: str | None, daylight: bool | None
) -> list[str]:
    lines = [_title(condition_emoji(metar.condition, daylight), metar.station, station_name)]
    group = _first_time_group(metar)
    if metar.observed is not None and group is not None:
        obs = t.t(K.DISCORD_OBS, time=t.t(K.TIME_UTC, value=_clock(metar.observed)), group=group)
        lines.append(obs + _metar_notes(t, metar))
    elif _metar_notes(t, metar):
        lines.append(_metar_notes(t, metar).removeprefix("  — "))
    lines.append("")

    body: list[str] = []
    if metar.wind is not None:
        body.append(t.t(K.DISCORD_WIND, value=_wind(t, metar.wind, units, metar.wind_variation)))
    weather = [g for g in metar.weather if not g.nsw and not g.not_observed]
    weather_text = t.lower_first(phrases.describe_weather(t, weather)) if weather else ""
    if metar.visibility is not None:
        if metar.visibility.cavok:
            value = t.t(K.DISCORD_CAVOK)
        else:
            value = phrases.describe_visibility(t, metar.visibility, units)
            if weather_text:
                value = t.t(K.DISCORD_VISIBILITY_IN, visibility=value, weather=weather_text)
        body.append(t.t(K.DISCORD_VISIBILITY, value=value))
    elif weather_text:
        body.append(t.t(K.DISCORD_WEATHER, value=weather_text))
    body.extend(t.t(K.DISCORD_RVR, value=phrases.describe_rvr(t, item, units)) for item in metar.rvr)

    precise = metar.remarks_of(PreciseTemperature)
    temperature = precise[0].temperature if precise else metar.temperature
    dewpoint = precise[0].dewpoint if precise and precise[0].dewpoint is not None else metar.dewpoint
    exact = bool(precise)
    if temperature is not None and dewpoint is not None:
        body.append(
            t.t(
                K.DISCORD_TEMPERATURE_DEWPOINT,
                temperature=_temperature(t, temperature, units, precise=exact),
                dewpoint=_temperature(t, dewpoint, units, precise=exact),
            )
        )
    elif temperature is not None:
        body.append(t.t(K.DISCORD_TEMPERATURE, value=_temperature(t, temperature, units, precise=exact)))
    elif dewpoint is not None:
        body.append(t.t(K.DISCORD_DEWPOINT, value=_temperature(t, dewpoint, units, precise=exact)))
    if metar.altimeter is not None:
        body.append(t.t(K.DISCORD_ALTIMETER, value=phrases.describe_pressure(t, metar.altimeter, units)))
    lines.extend(body)

    extras: list[str] = []
    if metar.sky and not (metar.visibility is not None and metar.visibility.cavok):
        clouds = "; ".join(phrases.describe_cloud_layer(t, layer, units) for layer in metar.sky)
        extras.append(t.t(K.DISCORD_CLOUDS, value=clouds))
    if metar.color_state is not None:
        extras.append(t.t(K.DISCORD_COLOR_STATE, value=phrases.describe_color_state(t, metar.color_state)))
    if metar.wind_shear:
        extras.append(t.t(K.DISCORD_WIND_SHEAR, value=phrases.describe_wind_shear(t, metar.wind_shear)))
    extras.extend(
        t.t(K.DISCORD_RUNWAY_STATE, value=phrases.describe_runway_state(t, state, units))
        for state in metar.runway_states
    )
    extras.extend(
        t.t(K.DISCORD_RECENT_WEATHER, value=phrases.describe_recent_weather(t, recent))
        for recent in metar.recent_weather
    )
    if metar.sea_state is not None:
        extras.append(t.t(K.DISCORD_SEA_STATE, value=phrases.describe_sea_state(t, metar.sea_state, units)))
    if extras:
        lines.append("")
        lines.extend(extras)

    tail: list[str] = []
    slp = metar.remarks_of(SeaLevelPressure)
    if slp and slp[0].pressure is not None:
        value = f"{t.numbers.fixed(slp[0].pressure.hpa, 1)} mb"
        tendency = metar.remarks_of(PressureTendency)
        if tendency:
            value = t.t(K.DISCORD_PRESSURE_WITH_TENDENCY, value=value, tendency=_tendency(t, tendency[0]))
        tail.append(t.t(K.DISCORD_PRESSURE, value=value))
    maxima = metar.remarks_of(MaxTemperature6Hour)
    minima = metar.remarks_of(MinTemperature6Hour)
    high = maxima[0].temperature if maxima else None
    low = minima[0].temperature if minima else None
    if high is not None and low is not None:
        highest, lowest = _temperature(t, high, units, precise=True), _temperature(t, low, units, precise=True)
        tail.append(t.t(K.DISCORD_MAX_MIN_6H, maximum=highest, minimum=lowest))
    elif high is not None:
        tail.append(t.t(K.DISCORD_MAX_6H, value=_temperature(t, high, units, precise=True)))
    elif low is not None:
        tail.append(t.t(K.DISCORD_MIN_6H, value=_temperature(t, low, units, precise=True)))
    for peak in metar.remarks_of(PeakWind):
        hour = f"{peak.time.hour:02d}" if peak.time.hour is not None else ""
        when = f"{hour}:{peak.time.minute:02d}"
        tail.append(
            t.t(
                K.DISCORD_PEAK_WIND,
                direction=f"{peak.direction:03d}",
                speed=format_speed(peak.speed, units, t.numbers),
                time=when,
            )
        )
    for trend in metar.trends:
        tail.append(
            t.t(
                K.DISCORD_TREND,
                code=trend.kind.value,
                text=t.lower_first(phrases.describe_trend(t, trend, units)),
            )
        )
    if tail:
        lines.append(DIVIDER)
        lines.extend(tail)
    return _tidy(lines)


# --- TAF -------------------------------------------------------------------------------------------------------


def _window(period: TafPeriod) -> str:
    """``31/2000Z -> 2200Z`` (the day is repeated only when the window crosses midnight)."""
    end = period.becoming_end if period.change is ChangeType.BECMG else period.end
    if period.start is None:
        return ""
    start = _group(period.start)
    if period.change in (ChangeType.BASE, ChangeType.FM) or end is None:
        return start
    finish = _clock(end).replace(":", "") + "Z" if end.date() == period.start.date() else _group(end)
    return f"{start} → {finish}"


def _heading(t: Translator, period: TafPeriod) -> str:
    when = _window(period)
    probability = period.probability if period.probability is not None else ""
    text = t.t(DISCORD_HEADING_KEYS[period.change], when=when, probability=probability).replace("  ", " ").rstrip()
    if period.flight_category is not None:
        text += f"  [{period.flight_category.value}]"
    return text


def _taf_lines(taf: Taf, t: Translator, units: UnitsMode, station_name: str | None) -> list[str]:
    lines = [_title(TAF_EMOJI, taf.station, station_name)]
    group = _first_time_group(taf)
    notes = ""
    if taf.amended:
        notes += f"  — {t.t(K.DISCORD_AMENDED)}"
    if {Modifier.COR, Modifier.CCA, Modifier.CCB, Modifier.CCC} & set(taf.modifiers):
        notes += f"  — {CAUTION} {t.t(K.DISCORD_CORRECTED)}"
    if taf.cancelled:
        notes += f"  — {CAUTION} {t.t(K.DISCORD_CANCELLED)}"
    if taf.nil:
        notes += f"  — {t.t(K.DISCORD_NIL)}"
    if taf.issue_time is not None and group is not None:
        issued = t.t(K.DISCORD_ISSUED, time=t.t(K.TIME_UTC, value=_clock(taf.issue_time)), group=group)
        lines.append(issued + notes)
    elif notes:
        lines.append(notes.removeprefix("  — "))
    if taf.valid_from is not None:
        end = _group(taf.valid_to) if taf.valid_to is not None else "?"
        lines.append(t.t(K.DISCORD_VALID, span=f"{_group(taf.valid_from)} → {end}"))

    lines.append("")
    lines.append(DIVIDER)
    if not taf.periods:
        lines.append(t.t(K.DISCORD_NO_FORECAST))
    for index, period in enumerate(taf.periods):
        if index:
            lines.append("")
        lines.append(_heading(t, period))
        lines.extend(_elements_lines(t, period.elements, units))

    closing: list[str] = []
    if taf.temperatures:
        parts = [
            t.t(
                K.DISCORD_TEMPERATURE_MAX if item.kind.value == "MAX" else K.DISCORD_TEMPERATURE_MIN,
                value=_temperature(t, item.temperature, units),
                time=_group(item.time) if item.time is not None else f"{item.day:02d}/{item.hour:02d}00Z",
            )
            for item in taf.temperatures
        ]
        closing.append(t.t(K.DISCORD_TEMPERATURES, parts=" | ".join(parts)))
    if taf.remarks:
        closing.append(t.t(K.DISCORD_REMARKS, text=taf.remarks))
    if closing:
        lines.append("")
        lines.extend(closing)
    return _tidy(lines)


def _tidy(lines: list[str]) -> list[str]:
    """Drop doubled blank lines and any blank line at the end."""
    tidy: list[str] = []
    for line in lines:
        if not line and (not tidy or not tidy[-1]):
            continue
        tidy.append(line)
    while tidy and not tidy[-1]:
        tidy.pop()
    return tidy


# --- entry points ----------------------------------------------------------------------------------------------


def discord_block(
    report: Metar | Taf,
    t: Translator,
    units: UnitsMode = UnitsMode.US,
    *,
    station_name: str | None = None,
    daylight: bool | None = None,
) -> str:
    """The code block to paste into Discord (three backticks, the layout, three backticks).

    A report whose layout does not fit a 2000-character message comes out as several blocks, split between lines and
    separated by a blank line, each of which fits (also inside the outer fence ``render_discord`` adds).
    """
    return "\n\n".join(_blocks(report, t, units, station_name, daylight))


def _blocks(
    report: Metar | Taf, t: Translator, units: UnitsMode, station_name: str | None, daylight: bool | None
) -> list[str]:
    if isinstance(report, Taf):
        lines = _taf_lines(report, t, units, station_name)
    else:
        lines = _metar_lines(report, t, units, station_name, daylight)
    warnings = warning_lines(report, t)  # the decoder's note of every group it could not read
    if warnings:
        lines = [*lines, "", *warnings]
    # Report text can hold a backtick, which would close the fence early.
    lines = [piece for line in lines for piece in _wrap(line.replace("`", "'"), BODY_LIMIT)]
    chunks: list[list[str]] = [[]]
    size = 0
    for line in lines:
        if chunks[-1] and size + 1 + _units(line) > BODY_LIMIT:
            chunks.append([])
            size = 0
        size += _units(line) + (1 if chunks[-1] else 0)
        chunks[-1].append(line)
    for chunk in chunks:
        while chunk and not chunk[0]:  # a blank line left at a split is not wanted at the top of a block
            chunk.pop(0)
        while chunk and not chunk[-1]:
            chunk.pop()
    return [f"{INNER_FENCE}\n" + "\n".join(chunk) + f"\n{INNER_FENCE}" for chunk in chunks if chunk]


def block_count(text: str) -> int:
    """How many fenced blocks ``discord_block`` made ``text`` of (each is a message of its own)."""
    return text.count(INNER_FENCE) // 2


def _units(text: str) -> int:
    """Length in UTF-16 code units, which is how Discord counts the 2000 characters (an emoji can be two)."""
    return len(text.encode("utf-16-le")) // 2


_JOINERS = ("\u200d", "\ufe0f", "\ufe0e")  # a cut before one of these, or after a ZWJ, would split an emoji


def _wrap(line: str, limit: int) -> list[str]:
    """``line`` in pieces of at most ``limit`` UTF-16 units, cut at a space where there is one."""
    pieces: list[str] = []
    while _units(line) > limit:
        end = min(len(line), limit)  # a character is at least one unit, so the fit is at or before here
        while _units(line[:end]) > limit:
            end -= 1
        cut = line.rfind(" ", 0, end + 1)
        if cut <= 0:
            cut = end
            while cut > 1 and (line[cut] in _JOINERS or line[cut - 1] == "\u200d"):
                cut -= 1
        pieces.append(line[:cut])
        line = line[cut:].lstrip(" ")
    pieces.append(line)
    return pieces


def render_discord(
    report: Metar | Taf,
    t: Translator,
    units: UnitsMode = UnitsMode.US,
    *,
    station_name: str | None = None,
    daylight: bool | None = None,
    outer_fence: bool = True,
) -> str:
    """``discord_block`` inside an outer four-backtick fence, so the inner fence survives being shown in a chat."""
    blocks = _blocks(report, t, units, station_name, daylight)
    if not outer_fence:
        return "\n\n".join(blocks)
    return "\n\n".join(f"{OUTER_FENCE}\n{block}\n{OUTER_FENCE}" for block in blocks)

