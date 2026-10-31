"""Language-neutral model of a decoded METAR/SPECI body.

Everything here is a frozen dataclass or an enum holding codes, numbers and aware datetimes. There are no English
words in this package: ``tables.py`` maps the enums to catalog keys and ``render/phrases.py`` turns keys into text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
    COLOR_BELOW_GRN = "COLOR_BELOW_GRN"
    RAPID_PRESSURE_CHANGE = "RAPID_PRESSURE_CHANGE"
    RUNWAY_CONTAMINATED = "RUNWAY_CONTAMINATED"
    MAINTENANCE = "MAINTENANCE"
    VOLCANIC_ASH = "VOLCANIC_ASH"
    MISSING_DATA = "MISSING_DATA"


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


# --- trends, colour states and the other groups between the pressure and RMK ------------------------------------


class TrendKind(Enum):
    NOSIG = "NOSIG"
    BECMG = "BECMG"
    TEMPO = "TEMPO"


class TrendTimeKind(Enum):
    FROM = "FM"
    UNTIL = "TL"
    AT = "AT"


@dataclass(frozen=True)
class TrendTime:
    """A time qualifier of a trend: ``FM1130`` (from), ``TL1230`` (until), ``AT1200`` (at).

    ``hour`` and ``minute`` are as written (hour 24 is kept). ``moment`` is the time resolved against the
    observation: the occurrence nearest to it, or ``None`` when the report has no valid time group.
    """

    kind: TrendTimeKind
    hour: int
    minute: int
    moment: datetime | None = None


class ColorCode(Enum):
    """NATO colour states from best to worst. ``YLO`` is the single yellow of older tables."""

    BLU = "BLU"
    WHT = "WHT"
    GRN = "GRN"
    YLO1 = "YLO1"
    YLO2 = "YLO2"
    YLO = "YLO"
    AMB = "AMB"
    RED = "RED"


@dataclass(frozen=True)
class ColorState:
    """One colour-state code.

    ``code`` is ``None`` for a bare ``BLACK`` and for ``///``; ``black`` is the closed-for-other-reasons prefix
    (``BLACKRED``); ``plus`` is the ``+`` suffix some air forces add (``BLU+``); ``not_reported`` is ``///``, which
    automatic military stations send in the colour-state position when they cannot determine a state.
    """

    code: ColorCode | None
    black: bool = False
    plus: bool = False
    not_reported: bool = False


@dataclass(frozen=True)
class ColorForecast:
    """A colour state that follows the current one: expected as is (``change`` is ``None``), ``BECMG`` or ``TEMPO``."""

    state: ColorState
    change: TrendKind | None = None


@dataclass(frozen=True)
class ColorStateGroup:
    """The colour-state group of a military report: the current state, then the forecast states in order.

    ``current`` is ``None`` when the group starts with a trend keyword (``TEMPO YLO``).
    """

    current: ColorState | None
    forecast: tuple[ColorForecast, ...] = ()


@dataclass(frozen=True)
class ForecastElements:
    """The elements a trend (or, later, a TAF period) states. Anything left empty is unchanged."""

    wind: Wind | None = None
    visibility: Visibility | None = None
    weather: tuple[WeatherGroup, ...] = ()
    sky: tuple[CloudLayer, ...] = ()
    color_state: ColorState | None = None

    @property
    def is_empty(self) -> bool:
        return not (self.wind or self.visibility or self.weather or self.sky or self.color_state)


@dataclass(frozen=True)
class Trend:
    """A landing forecast: ``NOSIG``, or ``BECMG``/``TEMPO`` with its time qualifiers and changed elements."""

    kind: TrendKind
    times: tuple[TrendTime, ...] = ()
    elements: ForecastElements = field(default_factory=ForecastElements)


class RunwayDeposit(Enum):
    """Type of deposit in a runway state group (first character)."""

    CLEAR_DRY = "0"
    DAMP = "1"
    WET = "2"
    FROST = "3"
    DRY_SNOW = "4"
    WET_SNOW = "5"
    SLUSH = "6"
    ICE = "7"
    COMPACTED_SNOW = "8"
    FROZEN_RUTS = "9"


class RunwayExtent(Enum):
    """Extent of contamination (second character); ``OTHER`` is a code the tables reserve."""

    NONE = "0"
    UP_TO_10 = "1"
    FROM_11_TO_25 = "2"
    FROM_26_TO_50 = "5"
    FROM_51_TO_100 = "9"
    OTHER = "?"


class RunwayDepthKind(Enum):
    MILLIMETERS = "MM"
    LESS_THAN_1 = "LESS_THAN_1"
    AT_LEAST = "AT_LEAST"  # 98: 40 cm or more
    NOT_OPERATIONAL = "NOT_OPERATIONAL"  # 99: runway closed by the deposit, depth not reported
    NOT_SIGNIFICANT = "NOT_SIGNIFICANT"  # //: operational, depth not significant or not measurable
    RESERVED = "RESERVED"  # 91


@dataclass(frozen=True)
class RunwayDepth:
    kind: RunwayDepthKind
    mm: int | None = None


class BrakingAction(Enum):
    POOR = "POOR"
    MEDIUM_POOR = "MEDIUM_POOR"
    MEDIUM = "MEDIUM"
    MEDIUM_GOOD = "MEDIUM_GOOD"
    GOOD = "GOOD"


@dataclass(frozen=True)
class RunwayBraking:
    """Friction: a coefficient (0.00 to 0.90), a braking-action estimate (91 to 95) or ``unreliable`` (99)."""

    coefficient: float | None = None
    action: BrakingAction | None = None
    unreliable: bool = False


@dataclass(frozen=True)
class RunwayState:
    """A runway state (contamination) group.

    ``runway`` is the designator (``24L``); ``all_runways`` is designator 88, ``repeated`` designator 99 (no new
    information), ``snoclo`` the aerodrome-closed-by-snow code, ``cleared`` the ``CLRD`` form. Each of ``deposit``,
    ``extent``, ``depth`` and ``braking`` is ``None`` when the report marks it not reported (``/``).
    """

    runway: str | None = None
    all_runways: bool = False
    repeated: bool = False
    snoclo: bool = False
    cleared: bool = False
    deposit: RunwayDeposit | None = None
    extent: RunwayExtent | None = None
    depth: RunwayDepth | None = None
    braking: RunwayBraking | None = None


@dataclass(frozen=True)
class RecentWeather:
    """Weather since the last report that has ended (``RERA``, ``RETSRA``): the weather group without its ``RE``."""

    weather: WeatherGroup


@dataclass(frozen=True)
class WindShearRunway:
    """A runway with reported wind shear (``WS R24L``), or all runways (``WS ALL RWY``)."""

    runway: str | None = None
    all_runways: bool = False


@dataclass(frozen=True)
class SeaState:
    """Sea-surface temperature and either a state-of-sea code (0 to 9) or a significant wave height."""

    temperature: Temperature | None = None
    state: int | None = None
    wave_height_m: float | None = None


# --- remarks ---------------------------------------------------------------------------------------------------


class Remark:
    """Base class of everything decoded after ``RMK``. Variants are frozen dataclasses below."""


@dataclass(frozen=True)
class RemarkTime:
    """A time in a remark: minutes past the hour of the report, or a full ``hour:minute`` in UTC."""

    minute: int
    hour: int | None = None


@dataclass(frozen=True)
class AutomatedStationType(Remark):
    """``AO1`` (no precipitation discriminator) or ``AO2`` (with one)."""

    precipitation_discriminator: bool


@dataclass(frozen=True)
class PeakWind(Remark):
    """``PK WND 28045/1547``."""

    direction: int
    speed: Speed
    time: RemarkTime


@dataclass(frozen=True)
class WindShift(Remark):
    """``WSHFT 1715`` or ``WSHFT 30 FROPA``."""

    time: RemarkTime
    frontal_passage: bool = False


@dataclass(frozen=True)
class TowerVisibility(Remark):
    """``TWR VIS 2``: visibility from the control tower."""

    distance: Distance


@dataclass(frozen=True)
class SurfaceVisibility(Remark):
    """``SFC VIS 3/4``: surface visibility."""

    distance: Distance


@dataclass(frozen=True)
class VariableVisibility(Remark):
    """``VIS 3/4V1 1/2``: prevailing visibility varying between two values."""

    low: Distance
    high: Distance


@dataclass(frozen=True)
class SectorVisibility(Remark):
    """``VIS NE 2 1/2`` or ``VIS 3/4 RWY11``: visibility in a sector or at a runway."""

    distance: Distance
    location: str


class LightningFrequency(Enum):
    OCCASIONAL = "OCNL"
    FREQUENT = "FRQ"
    CONTINUOUS = "CONS"


class LightningType(Enum):
    IN_CLOUD = "IC"
    CLOUD_TO_CLOUD = "CC"
    CLOUD_TO_GROUND = "CG"
    CLOUD_TO_AIR = "CA"


@dataclass(frozen=True)
class Lightning(Remark):
    """``FRQ LTG CG NE``, ``LTGICCG OHD``, ``LTG DSNT SW``. ``location`` holds the trailing location words."""

    frequency: LightningFrequency | None = None
    types: tuple[LightningType, ...] = ()
    location: tuple[str, ...] = ()


@dataclass(frozen=True)
class TimingEvent:
    began: bool
    time: RemarkTime


@dataclass(frozen=True)
class TimingSegment:
    """One weather type of a timing remark with its begin/end events."""

    intensity: Intensity
    descriptor: Descriptor | None
    phenomena: tuple[Phenomenon, ...]
    events: tuple[TimingEvent, ...]


@dataclass(frozen=True)
class WeatherTiming(Remark):
    """Begin and end times of precipitation or a thunderstorm: ``RAB07E45``, ``TSB0159E30``, ``DZB04E37RAB37``."""

    segments: tuple[TimingSegment, ...]


@dataclass(frozen=True)
class VariableCeiling(Remark):
    """``CIG 013V017``."""

    low: Distance
    high: Distance


@dataclass(frozen=True)
class SecondaryCeiling(Remark):
    """``CIG 017 RWY11``: ceiling at a second sensor."""

    height: Distance
    location: str


@dataclass(frozen=True)
class PressureRapidChange(Remark):
    """``PRESRR`` (rising rapidly) or ``PRESFR`` (falling rapidly)."""

    rising: bool


@dataclass(frozen=True)
class SeaLevelPressure(Remark):
    """``SLP177``; ``pressure`` is ``None`` for ``SLPNO`` (not available)."""

    pressure: Pressure | None


@dataclass(frozen=True)
class HourlyPrecipitation(Remark):
    """``P0003``: liquid-equivalent precipitation since the last report, in inches; ``None`` when missing."""

    inches: float | None
    trace: bool = False


@dataclass(frozen=True)
class PeriodPrecipitation(Remark):
    """``60009``: 3- or 6-hour precipitation.

    ``hours`` follows the synoptic hour of the report (``None`` if it is neither a 3- nor a 6-hour report time).
    """

    inches: float | None
    hours: int | None
    trace: bool = False


@dataclass(frozen=True)
class DailyPrecipitation(Remark):
    """``70015``: 24-hour precipitation in inches."""

    inches: float | None
    trace: bool = False


@dataclass(frozen=True)
class PreciseTemperature(Remark):
    """``T02330200``: temperature and dew point in tenths of a degree Celsius."""

    temperature: Temperature
    dewpoint: Temperature | None


@dataclass(frozen=True)
class MaxTemperature6Hour(Remark):
    """``10233``: 6-hour maximum temperature (the leading ``1`` marks a maximum, not a duration)."""

    temperature: Temperature | None


@dataclass(frozen=True)
class MinTemperature6Hour(Remark):
    """``20189``: 6-hour minimum temperature (the leading ``2`` marks a minimum, not a duration)."""

    temperature: Temperature | None


@dataclass(frozen=True)
class DailyTemperatureExtremes(Remark):
    """``400461006``: 24-hour maximum and minimum temperature."""

    maximum: Temperature | None
    minimum: Temperature | None


class TendencyDirection(Enum):
    HIGHER = "HIGHER"
    SAME = "SAME"
    LOWER = "LOWER"


@dataclass(frozen=True)
class PressureTendency(Remark):
    """``53011``: character of the 3-hour pressure change (0 to 8), its net direction and size in hPa."""

    character: int
    direction: TendencyDirection
    change_hpa: float


class SensorKind(Enum):
    RVR = "RVRNO"
    PRESENT_WEATHER = "PWINO"
    PRECIPITATION = "PNO"
    FREEZING_RAIN = "FZRANO"
    THUNDERSTORM = "TSNO"
    VISIBILITY = "VISNO"
    CEILING = "CHINO"


@dataclass(frozen=True)
class SensorStatus(Remark):
    """A sensor reported as not operating (``RVRNO``, ``PWINO``, ``VISNO RWY11`` ...)."""

    sensor: SensorKind
    location: str | None = None


@dataclass(frozen=True)
class MaintenanceIndicator(Remark):
    """``$``: the automated system needs maintenance."""


@dataclass(frozen=True)
class SnowDepth(Remark):
    """``4/012``: snow depth on the ground in inches."""

    inches: float | None


@dataclass(frozen=True)
class SnowIncrease(Remark):
    """``SNINCR 2/10``: snow increase in the past hour and total depth, in inches."""

    last_hour_inches: float
    total_inches: float


@dataclass(frozen=True)
class CloudTypes(Remark):
    """``8/CLCMCH``: low, middle and high cloud type codes (0 to 9; ``None`` for ``/``)."""

    low: int | None
    middle: int | None
    high: int | None


@dataclass(frozen=True)
class HailSize(Remark):
    """``GR 1 3/4``: largest hailstone in inches."""

    inches: float
    less_than: bool = False


@dataclass(frozen=True)
class DensityAltitude(Remark):
    """``DENSITY ALT 2500FT``."""

    altitude: Distance


@dataclass(frozen=True)
class OpacityLayer:
    """A cloud layer of a Canadian opacity remark: ``SC5`` is stratocumulus covering 5 eighths."""

    cloud: str
    eighths: int | None = None
    trace: bool = False


@dataclass(frozen=True)
class CloudOpacity(Remark):
    """Canadian cloud layers by type and eighths of sky, lowest first (``SC5AC2``, ``AC TR``)."""

    layers: tuple[OpacityLayer, ...]


class StationPressureKind(Enum):
    QFE = "QFE"
    QNH = "QNH"


@dataclass(frozen=True)
class StationPressure(Remark):
    """``QFE756/1008``, ``QNH766``: pressure in mm of mercury and/or hectopascals (Russian reports)."""

    kind: StationPressureKind
    mmhg: int | None = None
    hpa: int | None = None


@dataclass(frozen=True)
class AltimeterSetting(Remark):
    """``A3007`` or ``A30.06`` in the remarks: an altimeter setting some Asian stations add to ICAO reports."""

    pressure: Pressure


@dataclass(frozen=True)
class RunwayWind(Remark):
    """``RWY17L 02008KT`` or ``R06/31003MPS``: wind measured at one runway."""

    runway: str
    wind: Wind
    variation: WindVariation | None = None


@dataclass(frozen=True)
class WindAtHeight(Remark):
    """``WIND 2600FT 19040KT``: wind measured at a height above the aerodrome (Norwegian reports)."""

    height: Distance
    wind: Wind


@dataclass(frozen=True)
class ColorStateRemark(Remark):
    """A colour-state group given in the remarks (UK military: ``RMK YLO1 YLO1``, ``RMK RED BECMG AMB``)."""

    group: ColorStateGroup


@dataclass(frozen=True)
class FreeText(Remark):
    """Plain-language remark text that is not a coded group. Consecutive such tokens form one remark."""

    text: str


@dataclass(frozen=True)
class Metar:
    """A decoded METAR or SPECI.

    ``tokens`` holds every non-blank part of ``raw`` exactly once. ``tail_index`` points at the first token of
    the groups between the pressure and ``RMK`` (trends, colour states, runway state ...), ``remarks_index`` at
    the ``RMK`` token; both index into ``tokens``. The tail groups are decoded into ``trends``, ``color_state``,
    ``runway_states``, ``recent_weather``, ``wind_shear`` and ``sea_state``; the groups after ``RMK`` into
    ``remarks`` (``remarks_raw`` keeps the verbatim text).
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
    trends: tuple[Trend, ...] = ()
    color_state: ColorStateGroup | None = None
    computed_color_state: ColorCode | None = None
    runway_states: tuple[RunwayState, ...] = ()
    recent_weather: tuple[RecentWeather, ...] = ()
    wind_shear: tuple[WindShearRunway, ...] = ()
    sea_state: SeaState | None = None
    remarks: tuple[Remark, ...] = ()
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

    def remarks_of[R: Remark](self, kind: type[R]) -> tuple[R, ...]:
        """The remarks of one variant, in report order (``metar.remarks_of(SeaLevelPressure)``)."""
        return tuple(remark for remark in self.remarks if isinstance(remark, kind))

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
