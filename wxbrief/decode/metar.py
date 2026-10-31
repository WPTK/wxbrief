"""METAR/SPECI parser: an ordered section state machine with tolerant fallthrough.

The driver walks the tokens once. Sections have a fixed order (type, station, time, wind, wind variation, visibility,
then RVR/weather/sky in any order, temperature, pressure, then the tail groups), and a token is offered to the
current section and every later one, so a missing group is skipped rather than fatal. A small allowlist (modifiers
such as ``AUTO`` and ``COR``) may match earlier than the current section. A token nothing accepts becomes an
``UNKNOWN`` token plus a ``ParseWarning`` and parsing carries on with the next one.

``parse_metar`` never raises: each group parser runs inside a guard, and an outer guard turns any remaining failure
into an all-``UNKNOWN`` result with a warning. Every non-blank character of the input ends up in exactly one token.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import IntEnum

from wxbrief.decode.derived import derive
from wxbrief.decode.detect import detect_flavor
from wxbrief.decode.groups.header import parse_modifier, parse_station, parse_time, parse_type
from wxbrief.decode.groups.pressure import parse_pressure
from wxbrief.decode.groups.rvr import parse_rvr
from wxbrief.decode.groups.sky import parse_sky
from wxbrief.decode.groups.tail import parse_tail_group
from wxbrief.decode.groups.tempdew import parse_tempdew
from wxbrief.decode.groups.visibility import parse_visibility
from wxbrief.decode.groups.weather import parse_weather
from wxbrief.decode.groups.wind import parse_wind, parse_wind_variation
from wxbrief.decode.model import (
    RVR,
    CloudLayer,
    ColorStateGroup,
    ColorStateRemark,
    Flavor,
    Metar,
    Modifier,
    ParseWarning,
    RecentWeather,
    Remark,
    ReportType,
    RunwayState,
    SeaState,
    SemanticKind,
    Trend,
    Visibility,
    WeatherGroup,
    Wind,
    WindShearRunway,
    WindVariation,
)
from wxbrief.decode.remarks import Context, parse_remarks
from wxbrief.decode.times import resolve_day_time
from wxbrief.decode.tokens import Cursor, Token, tokenize
from wxbrief.decode.units import Pressure, Temperature

WARN_UNKNOWN_TOKEN = "unknown_token"
WARN_PARSER_ERROR = "parser_error"
WARN_UNSUPPORTED_REPORT = "unsupported_report"


class _Section(IntEnum):
    TYPE = 0
    STATION = 1
    TIME = 2
    WIND = 3
    WIND_VARIATION = 4
    VISIBILITY = 5
    BODY = 6  # RVR, weather and sky groups, in any order and repeatable
    TEMPDEW = 7
    PRESSURE = 8  # repeatable: some reports give both QNH and an altimeter setting
    TAIL = 9  # trends, colour states, runway state, recent weather, wind shear, sea state


@dataclass
class _Draft:
    """Mutable state collected while walking the tokens."""

    reference: datetime
    flavor: Flavor
    warnings: list[ParseWarning] = field(default_factory=list)
    report_type: ReportType = ReportType.METAR
    station: str | None = None
    observed: datetime | None = None
    modifiers: list[Modifier] = field(default_factory=list)
    wind: Wind | None = None
    wind_variation: WindVariation | None = None
    visibility: Visibility | None = None
    rvr: list[RVR] = field(default_factory=list)
    weather: list[WeatherGroup] = field(default_factory=list)
    sky: list[CloudLayer] = field(default_factory=list)
    temperature: Temperature | None = None
    dewpoint: Temperature | None = None
    altimeters: list[Pressure] = field(default_factory=list)
    tail_index: int | None = None
    trends: list[Trend] = field(default_factory=list)
    color_state: ColorStateGroup | None = None
    runway_states: list[RunwayState] = field(default_factory=list)
    recent_weather: list[RecentWeather] = field(default_factory=list)
    wind_shear: list[WindShearRunway] = field(default_factory=list)
    sea_state: SeaState | None = None
    remarks: list[Remark] = field(default_factory=list)

    def warn(self, code: str, token: Token) -> None:
        self.warnings.append(ParseWarning(code, token.start, token.end, token.text))


Runner = Callable[[Cursor, _Draft], bool]


@dataclass(frozen=True)
class _Step:
    section: _Section
    run: Runner
    advance_to: _Section
    loose: bool = False  # may match even after the driver has moved past ``section`` (up to the pressure)


def _run_type(cur: Cursor, draft: _Draft) -> bool:
    result = parse_type(cur)
    if result is None:
        return False
    draft.report_type = result
    return True


def _run_station(cur: Cursor, draft: _Draft) -> bool:
    result = parse_station(cur)
    if result is None:
        return False
    draft.station = result
    return True


def _run_time(cur: Cursor, draft: _Draft) -> bool:
    token = cur.peek()
    result = parse_time(cur)
    if result is None or token is None:
        return False
    moment, warning = resolve_day_time(*result, draft.reference)
    if moment is None and warning is not None:
        draft.warn(warning, token)
    draft.observed = moment
    return True


def _run_modifier(cur: Cursor, draft: _Draft) -> bool:
    result = parse_modifier(cur)
    if result is None:
        return False
    draft.modifiers.append(result)
    return True


def _run_wind(cur: Cursor, draft: _Draft) -> bool:
    result = parse_wind(cur)
    if result is None:
        return False
    draft.wind = result
    return True


def _run_wind_variation(cur: Cursor, draft: _Draft) -> bool:
    result = parse_wind_variation(cur)
    if result is None:
        return False
    draft.wind_variation = result
    return True


def _run_visibility(cur: Cursor, draft: _Draft) -> bool:
    result = parse_visibility(cur)
    if result is None:
        return False
    draft.visibility = result
    return True


def _run_rvr(cur: Cursor, draft: _Draft) -> bool:
    result = parse_rvr(cur)
    if result is None:
        return False
    draft.rvr.append(result)
    return True


def _run_weather(cur: Cursor, draft: _Draft) -> bool:
    result = parse_weather(cur)
    if result is None:
        return False
    draft.weather.append(result)
    return True


def _run_sky(cur: Cursor, draft: _Draft) -> bool:
    result = parse_sky(cur)
    if result is None:
        return False
    draft.sky.append(result)
    return True


def _run_tempdew(cur: Cursor, draft: _Draft) -> bool:
    result = parse_tempdew(cur)
    if result is None:
        return False
    draft.temperature = result.temperature
    draft.dewpoint = result.dewpoint
    return True


def _run_pressure(cur: Cursor, draft: _Draft) -> bool:
    result = parse_pressure(cur)
    if result is None:
        return False
    if result.value is not None:
        draft.altimeters.append(result.value)
    return True


def _run_tail(cur: Cursor, draft: _Draft) -> bool:
    start = cur.pos
    result = parse_tail_group(cur, draft.flavor, draft.observed)
    if result is None:
        return False
    if draft.tail_index is None:
        draft.tail_index = start
    if result.trend is not None:
        draft.trends.append(result.trend)
    if result.color_state is not None and draft.color_state is None:
        draft.color_state = result.color_state
    if result.runway_state is not None:
        draft.runway_states.append(result.runway_state)
    if result.recent_weather is not None:
        draft.recent_weather.append(result.recent_weather)
    draft.wind_shear.extend(result.wind_shear)
    if result.sea_state is not None and draft.sea_state is None:
        draft.sea_state = result.sea_state
    # A group parser leaves a token it cannot place inside the group as UNKNOWN; report each one.
    for index in range(start, cur.pos):
        if cur.kind_at(index) is SemanticKind.UNKNOWN:
            draft.warn(WARN_UNKNOWN_TOKEN, cur.token_at(index))
    return True


_STEPS: tuple[_Step, ...] = (
    _Step(_Section.TYPE, _run_type, _Section.STATION),
    _Step(_Section.STATION, _run_station, _Section.TIME),
    _Step(_Section.TIME, _run_time, _Section.WIND),
    _Step(_Section.WIND, _run_modifier, _Section.WIND, loose=True),  # a modifier never moves the position
    _Step(_Section.WIND, _run_wind, _Section.WIND_VARIATION),
    _Step(_Section.WIND_VARIATION, _run_wind_variation, _Section.VISIBILITY),
    _Step(_Section.VISIBILITY, _run_visibility, _Section.BODY),
    _Step(_Section.BODY, _run_rvr, _Section.BODY),
    _Step(_Section.BODY, _run_weather, _Section.BODY),
    _Step(_Section.BODY, _run_sky, _Section.BODY),
    _Step(_Section.TEMPDEW, _run_tempdew, _Section.PRESSURE),
    _Step(_Section.PRESSURE, _run_pressure, _Section.PRESSURE),
    _Step(_Section.TAIL, _run_tail, _Section.TAIL),
)


def _candidates(position: _Section) -> list[_Step]:
    """Steps to offer the next token: the current section, later ones, and the loose earlier ones."""
    return [step for step in _STEPS if step.section >= position or (step.loose and position <= _Section.PRESSURE)]


def _guarded(step: _Step, cur: Cursor, draft: _Draft) -> bool:
    """Run one group parser; any failure rewinds the cursor and counts as no match."""
    mark = cur.mark()
    token = cur.peek()
    try:
        if step.run(cur, draft):
            return True
    except Exception:
        if token is not None:
            draft.warn(WARN_PARSER_ERROR, token)
    cur.reset(mark)
    return False


def _decode_remarks(cur: Cursor, draft: _Draft, rmk: Token) -> None:
    """Decode everything after ``RMK``; if that fails, the rest stays plain ``REMARK`` tokens and a warning."""
    try:
        draft.remarks = parse_remarks(cur, Context(draft.observed))
    except Exception:
        draft.remarks = []
        draft.warn(WARN_PARSER_ERROR, rmk)
    while (rest := cur.peek()) is not None:
        cur.take(SemanticKind.TERMINATOR if rest.kind is SemanticKind.TERMINATOR else SemanticKind.REMARK)
    if draft.color_state is None:
        for remark in draft.remarks:
            if isinstance(remark, ColorStateRemark):
                draft.color_state = remark.group
                break


def _remarks_text(raw: str, tokens: tuple[Token, ...], remarks_index: int) -> str:
    body = [tok for tok in tokens[remarks_index + 1 :] if tok.kind is not SemanticKind.TERMINATOR]
    if not body:
        return ""
    return raw[body[0].start : body[-1].end]


def _parse(raw: str, reference: datetime | None) -> Metar:
    if reference is None:
        reference = datetime.now(UTC)
    elif reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)

    tokens = tokenize(raw)
    detection = detect_flavor(tokens)
    draft = _Draft(reference=reference, flavor=detection.flavor)
    cur = Cursor(tokens)

    if tokens and tokens[0].text == "TAF":
        draft.warn(WARN_UNSUPPORTED_REPORT, tokens[0])
        while not cur.at_end:
            cur.take(SemanticKind.UNKNOWN)
        return Metar(raw=raw, tokens=cur.tagged(), flavor=detection.flavor, warnings=tuple(draft.warnings))

    position = _Section.TYPE
    remarks_index: int | None = None
    while not cur.at_end:
        token = cur.peek()
        if token is None:
            break
        if token.kind is SemanticKind.TERMINATOR:
            cur.take(SemanticKind.TERMINATOR)
            continue
        if token.text == "RMK":
            remarks_index = cur.pos
            cur.take(SemanticKind.REMARK)
            _decode_remarks(cur, draft, token)
            break
        for step in _candidates(position):
            if _guarded(step, cur, draft):
                if not step.loose:
                    position = step.advance_to
                break
        else:
            draft.warn(WARN_UNKNOWN_TOKEN, token)
            cur.take(SemanticKind.UNKNOWN)

    tagged = cur.tagged()
    metar = Metar(
        raw=raw,
        tokens=tagged,
        report_type=draft.report_type,
        station=draft.station,
        observed=draft.observed,
        modifiers=tuple(draft.modifiers),
        wind=draft.wind,
        wind_variation=draft.wind_variation,
        visibility=draft.visibility,
        rvr=tuple(draft.rvr),
        weather=tuple(draft.weather),
        sky=tuple(draft.sky),
        temperature=draft.temperature,
        dewpoint=draft.dewpoint,
        altimeters=tuple(draft.altimeters),
        tail_index=draft.tail_index,
        remarks_index=remarks_index,
        remarks_raw=_remarks_text(raw, tagged, remarks_index) if remarks_index is not None else None,
        trends=tuple(draft.trends),
        color_state=draft.color_state,
        runway_states=tuple(draft.runway_states),
        recent_weather=tuple(draft.recent_weather),
        wind_shear=tuple(draft.wind_shear),
        sea_state=draft.sea_state,
        remarks=tuple(draft.remarks),
        flavor=detection.flavor,
        military=detection.military,
        warnings=tuple(draft.warnings),
    )
    return derive(metar)


def _failsafe(raw: str) -> Metar:
    """The result when the parser itself fails: every token unknown, one warning, nothing lost."""
    tokens = tuple(tokenize(raw))
    warning = ParseWarning(WARN_PARSER_ERROR, 0, len(raw), raw)
    return Metar(raw=raw, tokens=tokens, warnings=(warning,))


def parse_metar(raw: str, reference: datetime | None = None) -> Metar:
    """Decode one METAR or SPECI.

    ``reference`` is the moment used to resolve the day-of-month timestamp (``DDHHMMZ``) to a real date: the report's
    receipt time, a date chosen by the user, or now when omitted. Never raises.
    """
    try:
        return _parse(raw, reference)
    except Exception:
        return _failsafe(raw)
