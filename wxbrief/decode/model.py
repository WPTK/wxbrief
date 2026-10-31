"""Language-neutral model of a decoded METAR/SPECI body.

Everything here is a frozen dataclass or an enum holding codes, numbers and aware datetimes. There are no English
words in this package: ``tables.py`` maps the enums to catalog keys and ``render/phrases.py`` turns keys into text.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from wxbrief.decode.units import Distance, Pressure, Speed, Temperature

if TYPE_CHECKING:
    from wxbrief.decode.tokens import Token


class SemanticKind(Enum):
    """What a token is; drives syntax highlighting and tells later passes where each group sits."""

    TYPE = "type"  # METAR, SPECI
    STATION = "station"
    TIME = "time"
    MODIFIER = "modifier"  # AUTO, COR, NIL, CCA ...
    WIND = "wind"
    WIND_VARIATION = "wind_variation"
    VISIBILITY = "visibility"
    RVR = "rvr"
    WEATHER = "weather"
    SKY = "sky"
    TEMPERATURE = "temperature"
    PRESSURE = "pressure"
    RECENT_WEATHER = "recent_weather"  # RERA, RETSRA ...
    WIND_SHEAR = "wind_shear"  # WS ALL RWY, WS R24
    SEA_STATE = "sea_state"  # W15/S3
    RUNWAY_STATE = "runway_state"  # 88290192, R24L/290255, SNOCLO
    TREND = "trend"  # NOSIG, and BECMG/TEMPO with the groups that follow
    COLOR_STATE = "color_state"  # BLU, WHT, GRN, YLO, AMB, RED
    REMARK = "remark"  # RMK and everything after it
    TERMINATOR = "terminator"  # the trailing "="
    UNKNOWN = "unknown"


class ReportType(Enum):
    METAR = "METAR"
    SPECI = "SPECI"


class Modifier(Enum):
    AUTO = "AUTO"
    COR = "COR"
    CCA = "CCA"
    CCB = "CCB"
    CCC = "CCC"
    RTD = "RTD"
    NIL = "NIL"
    AMD = "AMD"
    CNL = "CNL"


class Flavor(Enum):
    """Which reporting convention the tokens follow; never inferred from the station prefix."""

    US = "us"  # statute miles, A#### altimeter
    ICAO = "icao"  # metres, Q#### QNH, CAVOK, trends
    MIXED = "mixed"  # both conventions present
    UNKNOWN = "unknown"


class FlightCategory(Enum):
    VFR = "VFR"
    MVFR = "MVFR"
    IFR = "IFR"
    LIFR = "LIFR"


class Flag(Enum):
    """Operationally significant conditions to call out next to a decode."""

    CB = "CB"
    TCU = "TCU"
    LOW_CEILING = "LOW_CEILING"
    LOW_VISIBILITY = "LOW_VISIBILITY"
    GUSTS = "GUSTS"
    WIND_SHEAR = "WIND_SHEAR"
    FREEZING_PRECIP = "FREEZING_PRECIP"
    THUNDERSTORM = "THUNDERSTORM"
    CORRECTED = "CORRECTED"
    AUTOMATED = "AUTOMATED"
    SPECIAL_REPORT = "SPECIAL_REPORT"


class Condition(Enum):
    """The dominant condition at the field, shown as the header glyph. Listed in priority order.

    Parsing yields ``CLEAR``; a caller that knows the station-local hour refines it to ``CLEAR_DAY`` or
    ``CLEAR_NIGHT`` (see ``derived.refine_clear``).
    """

    THUNDERSTORM = "THUNDERSTORM"
    SNOW = "SNOW"  # snow, frozen or freezing precipitation
    RAIN = "RAIN"  # rain or drizzle
    OBSCURATION = "OBSCURATION"  # fog, mist, haze, smoke, dust, ash
    OVERCAST = "OVERCAST"
    BROKEN = "BROKEN"
    PARTLY_CLOUDY = "PARTLY_CLOUDY"  # few or scattered cloud
    CLEAR = "CLEAR"
    CLEAR_DAY = "CLEAR_DAY"
    CLEAR_NIGHT = "CLEAR_NIGHT"


class VisPrefix(Enum):
    LESS_THAN = "M"
    GREATER_THAN = "P"


class Intensity(Enum):
    LIGHT = "LIGHT"
    MODERATE = "MODERATE"
    HEAVY = "HEAVY"


class Descriptor(Enum):
    MI = "MI"
    PR = "PR"
    BC = "BC"
    DR = "DR"
    BL = "BL"
    SH = "SH"
    TS = "TS"
    FZ = "FZ"


class Phenomenon(Enum):
    DZ = "DZ"
    RA = "RA"
    SN = "SN"
    SG = "SG"
    IC = "IC"
    PL = "PL"
    GR = "GR"
    GS = "GS"
    UP = "UP"
    BR = "BR"
    FG = "FG"
    FU = "FU"
    VA = "VA"
    DU = "DU"
    SA = "SA"
    HZ = "HZ"
    PY = "PY"
    PO = "PO"
    SQ = "SQ"
    FC = "FC"
    SS = "SS"
    DS = "DS"


class SkyCondition(Enum):
    """Sky cover codes: layers with amounts, vertical visibility and the clear-sky reports."""

    FEW = "FEW"
    SCT = "SCT"
    BKN = "BKN"
    OVC = "OVC"
    VV = "VV"
    SKC = "SKC"
    CLR = "CLR"
    NSC = "NSC"
    NCD = "NCD"
    UNKNOWN = "///"  # amount not determinable


class CloudType(Enum):
    CB = "CB"
    TCU = "TCU"
    UNKNOWN = "///"  # type not determinable


class RvrTrend(Enum):
    UP = "U"
    DOWN = "D"
    NO_CHANGE = "N"


@dataclass(frozen=True)
class ParseWarning:
    """Something the parser could not make sense of. ``code`` is a stable id, rendered through the catalog."""

    code: str
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class Wind:
    """Surface wind. ``direction`` is degrees true; ``None`` with ``variable`` False means not reported."""

    direction: int | None
    speed: Speed | None
    gust: Speed | None = None
    variable: bool = False  # VRB
    speed_above: bool = False  # P49MPS / ABV49MPS: the speed is a floor, not a value

    @property
    def calm(self) -> bool:
        return self.speed is not None and self.speed.value == 0


@dataclass(frozen=True)
class WindVariation:
    """Extremes of a varying wind direction (``180V240``), degrees true."""

    start: int
    end: int


@dataclass(frozen=True)
class DirectionalVisibility:
    """A minimum visibility: toward one compass direction (``1200NW``), or with no bearing (``0300``)."""

    distance: Distance
    direction: str | None = None  # N, NE, E, SE, S, SW, W, NW


@dataclass(frozen=True)
class Visibility:
    """Prevailing visibility. CAVOK carries no distance; ``9999`` sets ``unlimited`` (10 km or more)."""

    distance: Distance | None = None
    prefix: VisPrefix | None = None
    cavok: bool = False
    unlimited: bool = False
    ndv: bool = False  # no directional variation (automated stations)
    directional: tuple[DirectionalVisibility, ...] = ()
    not_reported: bool = False


@dataclass(frozen=True)
class RVR:
    """Runway visual range. ``distance`` may be a range start when ``variable_to`` is set."""

    runway: str
    distance: Distance | None
    prefix: VisPrefix | None = None
    variable_to: Distance | None = None
    variable_to_prefix: VisPrefix | None = None
    trend: RvrTrend | None = None


@dataclass(frozen=True)
class WeatherGroup:
    """One present-weather group: intensity, descriptor and phenomena, or NSW."""

    intensity: Intensity = Intensity.MODERATE
    descriptor: Descriptor | None = None
    phenomena: tuple[Phenomenon, ...] = ()
    vicinity: bool = False
    nsw: bool = False
    not_observed: bool = False  # "//": automated station could not report weather


@dataclass(frozen=True)
class CloudLayer:
    """One sky group. ``base`` is height above ground level; ``None`` for clear-sky codes or ``///``."""

    cover: SkyCondition
    base: Distance | None = None
    cloud_type: CloudType | None = None

    @property
    def is_ceiling_layer(self) -> bool:
        """Whether the layer can constitute a ceiling (broken, overcast or vertical visibility)."""
        return self.cover in (SkyCondition.BKN, SkyCondition.OVC, SkyCondition.VV)


@dataclass(frozen=True)
class Metar:
    """A decoded METAR or SPECI.

    ``tokens`` holds every non-blank part of ``raw`` exactly once. ``tail_index`` points at the first token of
    the groups between the pressure and ``RMK`` (trends, colour states, runway state ...), ``remarks_index`` at
    the ``RMK`` token; both index into ``tokens``. Those groups are tagged but not decoded here.
    """

    raw: str
    tokens: tuple[Token, ...]
    report_type: ReportType = ReportType.METAR
    station: str | None = None
    observed: datetime | None = None
    modifiers: tuple[Modifier, ...] = ()
    wind: Wind | None = None
    wind_variation: WindVariation | None = None
    visibility: Visibility | None = None
    rvr: tuple[RVR, ...] = ()
    weather: tuple[WeatherGroup, ...] = ()
    sky: tuple[CloudLayer, ...] = ()
    temperature: Temperature | None = None
    dewpoint: Temperature | None = None
    altimeters: tuple[Pressure, ...] = ()
    tail_index: int | None = None
    remarks_index: int | None = None
    remarks_raw: str | None = None
    flavor: Flavor = Flavor.UNKNOWN
    military: bool = False
    ceiling: Distance | None = None
    flight_category: FlightCategory | None = None
    flags: tuple[Flag, ...] = ()
    condition: Condition | None = None
    relative_humidity: float | None = None
    warnings: tuple[ParseWarning, ...] = ()

    @property
    def altimeter(self) -> Pressure | None:
        """The first pressure group (some reports give both QNH and an altimeter setting)."""
        return self.altimeters[0] if self.altimeters else None

    @property
    def cavok(self) -> bool:
        return self.visibility is not None and self.visibility.cavok

    @property
    def tail_tokens(self) -> tuple[Token, ...]:
        """Tokens of the undecoded tail groups: after the pressure, before ``RMK``, without the terminator."""
        if self.tail_index is None:
            return ()
        stop = self.remarks_index if self.remarks_index is not None else len(self.tokens)
        return tuple(tok for tok in self.tokens[self.tail_index : stop] if tok.kind is not SemanticKind.TERMINATOR)

    @property
    def remarks_tokens(self) -> tuple[Token, ...]:
        """Tokens after ``RMK`` (the ``RMK`` token itself excluded), without the terminator."""
        if self.remarks_index is None:
            return ()
        return tuple(tok for tok in self.tokens[self.remarks_index + 1 :] if tok.kind is not SemanticKind.TERMINATOR)
