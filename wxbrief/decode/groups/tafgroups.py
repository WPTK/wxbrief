"""Groups that only occur in TAFs: windows, change keywords, wind shear, temperatures, QNH, icing and turbulence.

* ``3106/3108`` is a window (``DDHH/DDHH``) and also the form of the valid period; ``FM311500`` (``FMDDHHMM``) starts
  a lasting change; ``PROB30`` is a probability. Old forecasts wrote the valid period as ``DDHHHH`` (``131212``), the
  change windows as ``HHHH`` (``BECMG 1315``) and ``FM`` as ``FMHHMM``; those are recognised too and flagged by the
  caller as legacy.
* ``WS020/30035KT`` is wind shear: the wind above 2,000 ft AGL is 300 degrees at 35 kt.
* ``TX19/3114Z`` and ``TNM02/0105Z`` are the maximum and minimum temperature (``M`` is minus) and the day and hour
  they are expected.
* ``QNH2992INS`` is the forecast pressure in inches of mercury (military TAFs); ``QNH1013`` is hectopascals. A number
  between 2600 and 3200 without ``INS`` is read as inches too (``QNH3009``: the ``INS`` was left off).
* ``LAST NO AMDS AFT 3023 NEXT 0207``, ``AMD NOT SKED``, ``AUTOMATED SENSOR METWATCH 3106 TIL 3113`` and the ``FS30217``
  identifiers close many military TAFs. They are notes rather than forecast groups: tagged ``REMARK`` and kept as text.
* ``620604`` is an icing group (``6 I hhh t``) and ``510708`` a turbulence group (``5 B hhh t``): the intensity code,
  the base in hundreds of feet above ground level and the thickness in thousands of feet (0 means unspecified).

Group parsers here do no date arithmetic: they return the day and hour as written and ``decode/taf.py`` resolves them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from wxbrief.decode.model import (
    IcingGroup,
    IcingIntensity,
    SemanticKind,
    TemperatureExtreme,
    TurbulenceGroup,
    TurbulenceIntensity,
    WindShearLayer,
)
from wxbrief.decode.tokens import Cursor
from wxbrief.decode.units import Distance, DistanceUnit, Pressure, PressureUnit, Speed, SpeedUnit, Temperature

_WINDOW = re.compile(r"^(\d{2})(\d{2})/(\d{2})(\d{2})$")
_LEGACY_VALID = re.compile(r"^(\d{2})(\d{2})(\d{2})$")
_LEGACY_WINDOW = re.compile(r"^(\d{2})(\d{2})$")
_FM = re.compile(r"^FM(\d{2})(\d{2})(\d{2})$")
_LEGACY_FM = re.compile(r"^FM(\d{2})(\d{2})$")
_PROB = re.compile(r"^PROB(\d{2})$")
_WIND_SHEAR = re.compile(
    r"^WS(?P<height>\d{3})/(?P<dir>\d{3}|VRB)(?P<spd>\d{2,3})(?:G(?P<gst>\d{2,3}))?(?P<unit>KT|MPS|KMH)$"
)
_TEMPERATURE = re.compile(r"^T(?P<kind>[XN])(?P<minus>M)?(?P<value>\d{2})/(?P<day>\d{2})(?P<hour>\d{2})Z?$")
_QNH = re.compile(r"^QNH(?P<value>\d{4})(?P<inches>INS)?$")
_ICING = re.compile(r"^6(?P<code>\d)(?P<base>\d{3})(?P<thickness>\d)$")
_TURBULENCE = re.compile(r"^5(?P<code>[\dX])(?P<base>\d{3})(?P<thickness>\d)$")
_UNITS = {"KT": SpeedUnit.KT, "MPS": SpeedUnit.MPS, "KMH": SpeedUnit.KMH}
_NOTE_ID = re.compile(r"^F[SN]\d{5}$")
_NOTE_TIME = re.compile(r"^\d{4}$")
_NOTE_STARTS = frozenset({"LAST", "NEXT", "AUTOMATED"})
_NOTE_WORDS = frozenset(
    {"LAST", "NO", "AMDS", "AFT", "NEXT", "AMD", "NOT", "SKED", "AUTOMATED", "SENSOR", "METWATCH", "TIL"}
)
_NOTE_TIME_AFTER = frozenset({"AFT", "NEXT", "METWATCH", "TIL"})
# Pressures in inches of mercury run from about 27 to 32; hectopascals from 870 to 1085. The ranges do not overlap.
_INHG_RANGE = range(2600, 3201)


@dataclass(frozen=True)
class DayHour:
    """A ``DDHH`` pair as written (hour 24 is kept; the caller resolves it)."""

    day: int
    hour: int


@dataclass(frozen=True)
class DayHourMinute:
    """A ``DDHHMM`` triple as written."""

    day: int
    hour: int
    minute: int


@dataclass(frozen=True)
class RawTemperature:
    """A ``TX``/``TN`` group before its day and hour are resolved to a moment."""

    kind: TemperatureExtreme
    temperature: Temperature
    day: int
    hour: int


# --- windows, change keywords ---------------------------------------------------------------------------------


def window_of(text: str) -> tuple[DayHour, DayHour] | None:
    """``3106/3108`` as ``(DayHour(31, 6), DayHour(31, 8))``; ``None`` if ``text`` is not a window."""
    match = _WINDOW.match(text)
    if match is None:
        return None
    return DayHour(int(match.group(1)), int(match.group(2))), DayHour(int(match.group(3)), int(match.group(4)))


def legacy_valid_of(text: str) -> tuple[int, int, int] | None:
    """The old valid period ``131212`` as ``(day, from_hour, to_hour)``."""
    match = _LEGACY_VALID.match(text)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def legacy_window_of(text: str) -> tuple[int, int] | None:
    """The old change window ``1315`` as ``(from_hour, to_hour)``."""
    match = _LEGACY_WINDOW.match(text)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def fm_of(text: str) -> DayHourMinute | None:
    """``FM311500`` as day 31, 15:00."""
    match = _FM.match(text)
    if match is None:
        return None
    return DayHourMinute(int(match.group(1)), int(match.group(2)), int(match.group(3)))


def legacy_fm_of(text: str) -> tuple[int, int] | None:
    """The old ``FM1800`` as ``(hour, minute)``."""
    match = _LEGACY_FM.match(text)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def probability_of(text: str) -> int | None:
    """``PROB30`` as 30."""
    match = _PROB.match(text)
    return int(match.group(1)) if match is not None else None


CHANGE_KEYWORDS = frozenset({"BECMG", "TEMPO", "INTER"})


def starts_change_group(text: str) -> bool:
    """Whether a token begins a change group: ``FM...``, ``BECMG``, ``TEMPO``, ``INTER`` or ``PROBnn``."""
    if text in CHANGE_KEYWORDS:
        return True
    return fm_of(text) is not None or legacy_fm_of(text) is not None or probability_of(text) is not None


# --- groups inside a forecast ----------------------------------------------------------------------------------


def parse_wind_shear_layer(cur: Cursor) -> WindShearLayer | None:
    """``WS020/30035KT``: tagged ``WIND_SHEAR``."""
    token = cur.peek()
    if token is None:
        return None
    match = _WIND_SHEAR.match(token.text)
    if match is None:
        return None
    direction = None if match.group("dir") == "VRB" else int(match.group("dir"))
    if direction is not None and direction > 360:
        return None
    unit = _UNITS[match.group("unit")]
    gust = Speed(int(match.group("gst")), unit) if match.group("gst") else None
    cur.take(SemanticKind.WIND_SHEAR)
    return WindShearLayer(
        Distance(int(match.group("height")) * 100, DistanceUnit.FT),
        direction,
        Speed(int(match.group("spd")), unit),
        gust,
    )


def parse_taf_temperature(cur: Cursor) -> RawTemperature | None:
    """``TX19/3114Z`` or ``TNM02/0105Z``: tagged ``TEMPERATURE``."""
    token = cur.peek()
    if token is None:
        return None
    match = _TEMPERATURE.match(token.text)
    if match is None:
        return None
    value = int(match.group("value"))
    if match.group("minus"):
        value = -value
    kind = TemperatureExtreme.MAX if match.group("kind") == "X" else TemperatureExtreme.MIN
    cur.take(SemanticKind.TEMPERATURE)
    return RawTemperature(kind, Temperature(value), int(match.group("day")), int(match.group("hour")))


def parse_qnh(cur: Cursor) -> Pressure | None:
    """``QNH2992INS`` (inches of mercury, hundredths) or ``QNH1013`` (hectopascals): tagged ``PRESSURE``."""
    token = cur.peek()
    if token is None:
        return None
    match = _QNH.match(token.text)
    if match is None:
        return None
    value = int(match.group("value"))
    cur.take(SemanticKind.PRESSURE)
    if match.group("inches") or value in _INHG_RANGE:
        return Pressure(value / 100, PressureUnit.INHG)
    return Pressure(float(value), PressureUnit.HPA)


def _layer(base: str, thickness: str) -> tuple[Distance, Distance | None]:
    return (
        Distance(int(base) * 100, DistanceUnit.FT),
        Distance(int(thickness) * 1000, DistanceUnit.FT) if thickness != "0" else None,
    )


def parse_icing(cur: Cursor) -> IcingGroup | None:
    """``620604``: tagged ``HAZARD``."""
    token = cur.peek()
    if token is None:
        return None
    match = _ICING.match(token.text)
    if match is None:
        return None
    base, thickness = _layer(match.group("base"), match.group("thickness"))
    cur.take(SemanticKind.HAZARD)
    return IcingGroup(IcingIntensity(match.group("code")), base, thickness)


def parse_turbulence(cur: Cursor) -> TurbulenceGroup | None:
    """``510708``: tagged ``HAZARD``."""
    token = cur.peek()
    if token is None:
        return None
    match = _TURBULENCE.match(token.text)
    if match is None:
        return None
    base, thickness = _layer(match.group("base"), match.group("thickness"))
    cur.take(SemanticKind.HAZARD)
    return TurbulenceGroup(TurbulenceIntensity(match.group("code")), base, thickness)


def parse_note(cur: Cursor) -> str | None:
    """A military closing note (``LAST NO AMDS AFT 3023 NEXT 0207``, ``AMD NOT SKED``, ``FS30217``): ``REMARK`` tokens.

    Returns the words as written, or ``None`` (nothing consumed) if the cursor is not at one.
    """
    first = cur.peek()
    if first is None:
        return None
    following = cur.peek(1)
    starts = (
        first.text in _NOTE_STARTS
        or _NOTE_ID.match(first.text) is not None
        or (first.text == "AMD" and following is not None and following.text == "NOT")
    )
    if not starts:
        return None
    words: list[str] = []
    while (token := cur.peek()) is not None:
        text = token.text
        is_time = _NOTE_TIME.match(text) is not None and bool(words) and words[-1] in _NOTE_TIME_AFTER
        if not (text in _NOTE_WORDS or _NOTE_ID.match(text) or is_time):
            break
        cur.take(SemanticKind.REMARK)
        words.append(text)
    return " ".join(words)


@dataclass
class PeriodExtras:
    """Collects the TAF-only groups of one forecast period while ``parse_trend_body`` walks it.

    Calling the instance with a cursor is the ``extra`` hook of ``parse_trend_body``: it consumes one TAF-only group
    and returns ``True``, or returns ``False`` for anything else. A second wind shear or QNH group in the same period
    is declined (it stays unknown), like a second wind group. Temperature extremes go to ``temperatures``, which the
    caller shares across periods because they belong to the whole forecast; so do the closing ``notes``.
    """

    temperatures: list[RawTemperature]
    notes: list[str]
    wind_shear: WindShearLayer | None = None
    altimeter: Pressure | None = None
    icing: list[IcingGroup] = field(default_factory=list)
    turbulence: list[TurbulenceGroup] = field(default_factory=list)

    def __call__(self, cur: Cursor) -> bool:
        token = cur.peek()
        if token is None:
            return False
        if self.wind_shear is None and (shear := parse_wind_shear_layer(cur)) is not None:
            self.wind_shear = shear
            return True
        if (temperature := parse_taf_temperature(cur)) is not None:
            self.temperatures.append(temperature)
            return True
        if self.altimeter is None and (pressure := parse_qnh(cur)) is not None:
            self.altimeter = pressure
            return True
        if (icing := parse_icing(cur)) is not None:
            self.icing.append(icing)
            return True
        if (turbulence := parse_turbulence(cur)) is not None:
            self.turbulence.append(turbulence)
            return True
        if (note := parse_note(cur)) is not None:
            self.notes.append(note)
            return True
        return False
