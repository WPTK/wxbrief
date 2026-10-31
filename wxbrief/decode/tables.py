"""Code tables: report codes to model enums, and model enums to catalog keys.

Ported from the weather-phenomena and international references. Nothing here holds English words: the ``*_KEYS``
tables point into the translation catalog, which is where the words live.
"""

from __future__ import annotations

from wxbrief.decode.model import (
    BrakingAction,
    CloudType,
    ColorCode,
    Descriptor,
    Flag,
    FlightCategory,
    Intensity,
    LightningFrequency,
    LightningType,
    Modifier,
    Phenomenon,
    ReportType,
    RunwayDeposit,
    RunwayDepthKind,
    RunwayExtent,
    RvrTrend,
    SensorKind,
    SkyCondition,
    TrendTimeKind,
)
from wxbrief.i18n.keys import K

# --- codes found in reports -> enums (used by the group parsers) -------------------------------------------------

DESCRIPTOR_CODES: dict[str, Descriptor] = {member.value: member for member in Descriptor}
PHENOMENON_CODES: dict[str, Phenomenon] = {member.value: member for member in Phenomenon}
MODIFIER_CODES: dict[str, Modifier] = {member.value: member for member in Modifier}
SKY_COVER_CODES: dict[str, SkyCondition] = {member.value: member for member in SkyCondition}
CLOUD_TYPE_CODES: dict[str, CloudType] = {member.value: member for member in CloudType}
RVR_TREND_CODES: dict[str, RvrTrend] = {member.value: member for member in RvrTrend}

# Sky reports that carry no layer (no amount/height).
CLEAR_SKY_CODES: frozenset[SkyCondition] = frozenset(
    {SkyCondition.SKC, SkyCondition.CLR, SkyCondition.NSC, SkyCondition.NCD}
)

# --- enums -> catalog keys (used by the renderers) ---------------------------------------------------------------

REPORT_TYPE_KEYS: dict[ReportType, str] = {
    ReportType.METAR: K.REPORT_METAR,
    ReportType.SPECI: K.REPORT_SPECI,
}

MODIFIER_KEYS: dict[Modifier, str] = {
    Modifier.AUTO: K.MODIFIER_AUTO,
    Modifier.COR: K.MODIFIER_COR,
    Modifier.CCA: K.MODIFIER_CCA,
    Modifier.CCB: K.MODIFIER_CCB,
    Modifier.CCC: K.MODIFIER_CCC,
    Modifier.RTD: K.MODIFIER_RTD,
    Modifier.NIL: K.MODIFIER_NIL,
    Modifier.AMD: K.MODIFIER_AMD,
    Modifier.CNL: K.MODIFIER_CNL,
}

# Moderate intensity is the unmarked default and has no word.
INTENSITY_KEYS: dict[Intensity, str | None] = {
    Intensity.LIGHT: K.WX_INTENSITY_LIGHT,
    Intensity.MODERATE: None,
    Intensity.HEAVY: K.WX_INTENSITY_HEAVY,
}

# A descriptor on its own ("TS", "VCSH") versus in front of a phenomenon ("TSRA", "SHSN").
DESCRIPTOR_ALONE_KEYS: dict[Descriptor, str] = {
    Descriptor.MI: K.WX_DESCRIPTOR_MI,
    Descriptor.PR: K.WX_DESCRIPTOR_PR,
    Descriptor.BC: K.WX_DESCRIPTOR_BC,
    Descriptor.DR: K.WX_DESCRIPTOR_DR,
    Descriptor.BL: K.WX_DESCRIPTOR_BL,
    Descriptor.SH: K.WX_DESCRIPTOR_SH,
    Descriptor.TS: K.WX_DESCRIPTOR_TS,
    Descriptor.FZ: K.WX_DESCRIPTOR_FZ,
}

DESCRIPTOR_WITH_KEYS: dict[Descriptor, str] = {
    Descriptor.MI: K.WX_DESCRIPTOR_WITH_MI,
    Descriptor.PR: K.WX_DESCRIPTOR_WITH_PR,
    Descriptor.BC: K.WX_DESCRIPTOR_WITH_BC,
    Descriptor.DR: K.WX_DESCRIPTOR_WITH_DR,
    Descriptor.BL: K.WX_DESCRIPTOR_WITH_BL,
    Descriptor.SH: K.WX_DESCRIPTOR_WITH_SH,
    Descriptor.TS: K.WX_DESCRIPTOR_WITH_TS,
    Descriptor.FZ: K.WX_DESCRIPTOR_WITH_FZ,
}

PHENOMENON_KEYS: dict[Phenomenon, str] = {
    Phenomenon.DZ: K.WX_PHENOMENON_DZ,
    Phenomenon.RA: K.WX_PHENOMENON_RA,
    Phenomenon.SN: K.WX_PHENOMENON_SN,
    Phenomenon.SG: K.WX_PHENOMENON_SG,
    Phenomenon.IC: K.WX_PHENOMENON_IC,
    Phenomenon.PL: K.WX_PHENOMENON_PL,
    Phenomenon.GR: K.WX_PHENOMENON_GR,
    Phenomenon.GS: K.WX_PHENOMENON_GS,
    Phenomenon.UP: K.WX_PHENOMENON_UP,
    Phenomenon.BR: K.WX_PHENOMENON_BR,
    Phenomenon.FG: K.WX_PHENOMENON_FG,
    Phenomenon.FU: K.WX_PHENOMENON_FU,
    Phenomenon.VA: K.WX_PHENOMENON_VA,
    Phenomenon.DU: K.WX_PHENOMENON_DU,
    Phenomenon.SA: K.WX_PHENOMENON_SA,
    Phenomenon.HZ: K.WX_PHENOMENON_HZ,
    Phenomenon.PY: K.WX_PHENOMENON_PY,
    Phenomenon.PO: K.WX_PHENOMENON_PO,
    Phenomenon.SQ: K.WX_PHENOMENON_SQ,
    Phenomenon.FC: K.WX_PHENOMENON_FC,
    Phenomenon.SS: K.WX_PHENOMENON_SS,
    Phenomenon.DS: K.WX_PHENOMENON_DS,
}

# Amount words for layers and clear-sky reports; VV has its own sentence and is not listed here.
SKY_COVER_KEYS: dict[SkyCondition, str] = {
    SkyCondition.FEW: K.SKY_COVER_FEW,
    SkyCondition.SCT: K.SKY_COVER_SCT,
    SkyCondition.BKN: K.SKY_COVER_BKN,
    SkyCondition.OVC: K.SKY_COVER_OVC,
    SkyCondition.SKC: K.SKY_COVER_SKC,
    SkyCondition.CLR: K.SKY_COVER_CLR,
    SkyCondition.NSC: K.SKY_COVER_NSC,
    SkyCondition.NCD: K.SKY_COVER_NCD,
    SkyCondition.UNKNOWN: K.SKY_COVER_UNKNOWN,
}

CLOUD_TYPE_KEYS: dict[CloudType, str] = {
    CloudType.CB: K.SKY_TYPE_CB,
    CloudType.TCU: K.SKY_TYPE_TCU,
    CloudType.UNKNOWN: K.SKY_TYPE_UNKNOWN,
}

RVR_TREND_KEYS: dict[RvrTrend, str] = {
    RvrTrend.UP: K.RVR_TREND_UP,
    RvrTrend.DOWN: K.RVR_TREND_DOWN,
    RvrTrend.NO_CHANGE: K.RVR_TREND_NO_CHANGE,
}

COMPASS_KEYS: dict[str, str] = {
    "N": K.COMPASS_N,
    "NNE": K.COMPASS_NNE,
    "NE": K.COMPASS_NE,
    "ENE": K.COMPASS_ENE,
    "E": K.COMPASS_E,
    "ESE": K.COMPASS_ESE,
    "SE": K.COMPASS_SE,
    "SSE": K.COMPASS_SSE,
    "S": K.COMPASS_S,
    "SSW": K.COMPASS_SSW,
    "SW": K.COMPASS_SW,
    "WSW": K.COMPASS_WSW,
    "W": K.COMPASS_W,
    "WNW": K.COMPASS_WNW,
    "NW": K.COMPASS_NW,
    "NNW": K.COMPASS_NNW,
}

# Index into COMPASS_POINTS is round(degrees / 22.5) % 16.
COMPASS_POINTS: tuple[str, ...] = tuple(COMPASS_KEYS)

FLIGHT_CATEGORY_KEYS: dict[FlightCategory, str] = {
    FlightCategory.VFR: K.FCAT_VFR,
    FlightCategory.MVFR: K.FCAT_MVFR,
    FlightCategory.IFR: K.FCAT_IFR,
    FlightCategory.LIFR: K.FCAT_LIFR,
}

FLAG_KEYS: dict[Flag, str] = {
    Flag.CB: K.FLAG_CB,
    Flag.TCU: K.FLAG_TCU,
    Flag.LOW_CEILING: K.FLAG_LOW_CEILING,
    Flag.LOW_VISIBILITY: K.FLAG_LOW_VISIBILITY,
    Flag.GUSTS: K.FLAG_GUSTS,
    Flag.WIND_SHEAR: K.FLAG_WIND_SHEAR,
    Flag.FREEZING_PRECIP: K.FLAG_FREEZING_PRECIP,
    Flag.THUNDERSTORM: K.FLAG_THUNDERSTORM,
    Flag.CORRECTED: K.FLAG_CORRECTED,
    Flag.AUTOMATED: K.FLAG_AUTOMATED,
    Flag.SPECIAL_REPORT: K.FLAG_SPECIAL_REPORT,
}


def compass_point(degrees: float) -> str:
    """The 16-point compass abbreviation (``"ENE"``) nearest to a bearing in degrees."""
    return COMPASS_POINTS[round((degrees % 360) / 22.5) % 16]

FLAG_KEYS.update(
    {
        Flag.COLOR_BELOW_GRN: K.FLAG_COLOR_BELOW_GRN,
        Flag.RAPID_PRESSURE_CHANGE: K.FLAG_RAPID_PRESSURE_CHANGE,
        Flag.RUNWAY_CONTAMINATED: K.FLAG_RUNWAY_CONTAMINATED,
        Flag.MAINTENANCE: K.FLAG_MAINTENANCE,
        Flag.VOLCANIC_ASH: K.FLAG_VOLCANIC_ASH,
        Flag.MISSING_DATA: K.FLAG_MISSING_DATA,
    }
)

# --- tail groups -----------------------------------------------------------------------------------------------

COLOR_NAME_KEYS: dict[ColorCode, str] = {
    ColorCode.BLU: K.COLOR_NAME_BLU,
    ColorCode.WHT: K.COLOR_NAME_WHT,
    ColorCode.GRN: K.COLOR_NAME_GRN,
    ColorCode.YLO1: K.COLOR_NAME_YLO1,
    ColorCode.YLO2: K.COLOR_NAME_YLO2,
    ColorCode.YLO: K.COLOR_NAME_YLO,
    ColorCode.AMB: K.COLOR_NAME_AMB,
    ColorCode.RED: K.COLOR_NAME_RED,
}

TREND_TIME_KEYS: dict[TrendTimeKind, str] = {
    TrendTimeKind.FROM: K.TREND_TIME_FM,
    TrendTimeKind.UNTIL: K.TREND_TIME_TL,
    TrendTimeKind.AT: K.TREND_TIME_AT,
}

RUNWAY_DEPOSIT_KEYS: dict[RunwayDeposit, str] = {
    RunwayDeposit.CLEAR_DRY: K.RWY_DEPOSIT_CLEAR_DRY,
    RunwayDeposit.DAMP: K.RWY_DEPOSIT_DAMP,
    RunwayDeposit.WET: K.RWY_DEPOSIT_WET,
    RunwayDeposit.FROST: K.RWY_DEPOSIT_FROST,
    RunwayDeposit.DRY_SNOW: K.RWY_DEPOSIT_DRY_SNOW,
    RunwayDeposit.WET_SNOW: K.RWY_DEPOSIT_WET_SNOW,
    RunwayDeposit.SLUSH: K.RWY_DEPOSIT_SLUSH,
    RunwayDeposit.ICE: K.RWY_DEPOSIT_ICE,
    RunwayDeposit.COMPACTED_SNOW: K.RWY_DEPOSIT_COMPACTED_SNOW,
    RunwayDeposit.FROZEN_RUTS: K.RWY_DEPOSIT_FROZEN_RUTS,
}

RUNWAY_EXTENT_KEYS: dict[RunwayExtent, str] = {
    RunwayExtent.NONE: K.RWY_EXTENT_NONE,
    RunwayExtent.UP_TO_10: K.RWY_EXTENT_UP_TO_10,
    RunwayExtent.FROM_11_TO_25: K.RWY_EXTENT_FROM_11_TO_25,
    RunwayExtent.FROM_26_TO_50: K.RWY_EXTENT_FROM_26_TO_50,
    RunwayExtent.FROM_51_TO_100: K.RWY_EXTENT_FROM_51_TO_100,
    RunwayExtent.OTHER: K.RWY_EXTENT_OTHER,
}

RUNWAY_DEPTH_KEYS: dict[RunwayDepthKind, str] = {
    RunwayDepthKind.MILLIMETERS: K.RWY_DEPTH_MILLIMETERS,
    RunwayDepthKind.LESS_THAN_1: K.RWY_DEPTH_LESS_THAN_1,
    RunwayDepthKind.AT_LEAST: K.RWY_DEPTH_AT_LEAST,
    RunwayDepthKind.NOT_OPERATIONAL: K.RWY_DEPTH_NOT_OPERATIONAL,
    RunwayDepthKind.NOT_SIGNIFICANT: K.RWY_DEPTH_NOT_SIGNIFICANT,
    RunwayDepthKind.RESERVED: K.RWY_DEPTH_RESERVED,
}

BRAKING_ACTION_KEYS: dict[BrakingAction, str] = {
    BrakingAction.POOR: K.RWY_ACTION_POOR,
    BrakingAction.MEDIUM_POOR: K.RWY_ACTION_MEDIUM_POOR,
    BrakingAction.MEDIUM: K.RWY_ACTION_MEDIUM,
    BrakingAction.MEDIUM_GOOD: K.RWY_ACTION_MEDIUM_GOOD,
    BrakingAction.GOOD: K.RWY_ACTION_GOOD,
}

# State of the sea, WMO code table 3700.
SEA_STATE_KEYS: dict[int, str] = {
    0: K.SEA_NAME_0,
    1: K.SEA_NAME_1,
    2: K.SEA_NAME_2,
    3: K.SEA_NAME_3,
    4: K.SEA_NAME_4,
    5: K.SEA_NAME_5,
    6: K.SEA_NAME_6,
    7: K.SEA_NAME_7,
    8: K.SEA_NAME_8,
    9: K.SEA_NAME_9,
}

# --- remarks ---------------------------------------------------------------------------------------------------

SENSOR_KEYS: dict[SensorKind, str] = {
    SensorKind.RVR: K.REMARK_SENSOR_RVR,
    SensorKind.PRESENT_WEATHER: K.REMARK_SENSOR_PRESENT_WEATHER,
    SensorKind.PRECIPITATION: K.REMARK_SENSOR_PRECIPITATION,
    SensorKind.FREEZING_RAIN: K.REMARK_SENSOR_FREEZING_RAIN,
    SensorKind.THUNDERSTORM: K.REMARK_SENSOR_THUNDERSTORM,
    SensorKind.VISIBILITY: K.REMARK_SENSOR_VISIBILITY,
    SensorKind.CEILING: K.REMARK_SENSOR_CEILING,
}

LIGHTNING_FREQUENCY_KEYS: dict[LightningFrequency, str] = {
    LightningFrequency.OCCASIONAL: K.REMARK_FREQUENCY_OCCASIONAL,
    LightningFrequency.FREQUENT: K.REMARK_FREQUENCY_FREQUENT,
    LightningFrequency.CONTINUOUS: K.REMARK_FREQUENCY_CONTINUOUS,
}

LIGHTNING_TYPE_KEYS: dict[LightningType, str] = {
    LightningType.IN_CLOUD: K.REMARK_LIGHTNING_TYPE_IN_CLOUD,
    LightningType.CLOUD_TO_CLOUD: K.REMARK_LIGHTNING_TYPE_CLOUD_TO_CLOUD,
    LightningType.CLOUD_TO_GROUND: K.REMARK_LIGHTNING_TYPE_CLOUD_TO_GROUND,
    LightningType.CLOUD_TO_AIR: K.REMARK_LIGHTNING_TYPE_CLOUD_TO_AIR,
}

# Character of the 3-hour pressure change (WMO code table 0200): 0-3 net higher, 4 same, 5-8 net lower.
TENDENCY_NAME_KEYS: dict[int, str] = {
    0: K.REMARK_TENDENCY_NAME_0,
    1: K.REMARK_TENDENCY_NAME_1,
    2: K.REMARK_TENDENCY_NAME_2,
    3: K.REMARK_TENDENCY_NAME_3,
    4: K.REMARK_TENDENCY_NAME_4,
    5: K.REMARK_TENDENCY_NAME_5,
    6: K.REMARK_TENDENCY_NAME_6,
    7: K.REMARK_TENDENCY_NAME_7,
    8: K.REMARK_TENDENCY_NAME_8,
}

# Cloud type codes of the 8/CLCMCH group (WMO code tables 0513, 0515 and 0509).
CLOUD_LOW_KEYS: dict[int, str] = {
    0: K.REMARK_CLOUD_LOW_0,
    1: K.REMARK_CLOUD_LOW_1,
    2: K.REMARK_CLOUD_LOW_2,
    3: K.REMARK_CLOUD_LOW_3,
    4: K.REMARK_CLOUD_LOW_4,
    5: K.REMARK_CLOUD_LOW_5,
    6: K.REMARK_CLOUD_LOW_6,
    7: K.REMARK_CLOUD_LOW_7,
    8: K.REMARK_CLOUD_LOW_8,
    9: K.REMARK_CLOUD_LOW_9,
}
CLOUD_MIDDLE_KEYS: dict[int, str] = {
    0: K.REMARK_CLOUD_MIDDLE_0,
    1: K.REMARK_CLOUD_MIDDLE_1,
    2: K.REMARK_CLOUD_MIDDLE_2,
    3: K.REMARK_CLOUD_MIDDLE_3,
    4: K.REMARK_CLOUD_MIDDLE_4,
    5: K.REMARK_CLOUD_MIDDLE_5,
    6: K.REMARK_CLOUD_MIDDLE_6,
    7: K.REMARK_CLOUD_MIDDLE_7,
    8: K.REMARK_CLOUD_MIDDLE_8,
    9: K.REMARK_CLOUD_MIDDLE_9,
}
CLOUD_HIGH_KEYS: dict[int, str] = {
    0: K.REMARK_CLOUD_HIGH_0,
    1: K.REMARK_CLOUD_HIGH_1,
    2: K.REMARK_CLOUD_HIGH_2,
    3: K.REMARK_CLOUD_HIGH_3,
    4: K.REMARK_CLOUD_HIGH_4,
    5: K.REMARK_CLOUD_HIGH_5,
    6: K.REMARK_CLOUD_HIGH_6,
    7: K.REMARK_CLOUD_HIGH_7,
    8: K.REMARK_CLOUD_HIGH_8,
    9: K.REMARK_CLOUD_HIGH_9,
}

# Cloud abbreviations of the Canadian opacity remark.
OPACITY_CLOUD_KEYS: dict[str, str] = {
    "CU": K.REMARK_CLOUD_CU,
    "TCU": K.REMARK_CLOUD_TCU,
    "CB": K.REMARK_CLOUD_CB,
    "SC": K.REMARK_CLOUD_SC,
    "ST": K.REMARK_CLOUD_ST,
    "SF": K.REMARK_CLOUD_SF,
    "CF": K.REMARK_CLOUD_CF,
    "AC": K.REMARK_CLOUD_AC,
    "ACC": K.REMARK_CLOUD_ACC,
    "AS": K.REMARK_CLOUD_AS,
    "NS": K.REMARK_CLOUD_NS,
    "CI": K.REMARK_CLOUD_CI,
    "CC": K.REMARK_CLOUD_CC,
    "CS": K.REMARK_CLOUD_CS,
}

# Words of plain-language remarks that the catalog can say in words; anything else is shown as written.
FREE_TEXT_WORD_KEYS: dict[str, str] = {
    "N": K.REMARK_WORD_N,
    "NE": K.REMARK_WORD_NE,
    "E": K.REMARK_WORD_E,
    "SE": K.REMARK_WORD_SE,
    "S": K.REMARK_WORD_S,
    "SW": K.REMARK_WORD_SW,
    "W": K.REMARK_WORD_W,
    "NW": K.REMARK_WORD_NW,
    "AND": K.REMARK_WORD_AND,
    "TO": K.REMARK_WORD_TO,
    "DSNT": K.REMARK_WORD_DSNT,
    "VC": K.REMARK_WORD_VC,
    "OHD": K.REMARK_WORD_OHD,
    "OVHD": K.REMARK_WORD_OVHD,
    "OVR": K.REMARK_WORD_OVR,
    "ALQDS": K.REMARK_WORD_ALQDS,
    "MOV": K.REMARK_WORD_MOV,
    "MOVG": K.REMARK_WORD_MOVG,
    "CB": K.REMARK_WORD_CB,
    "TCU": K.REMARK_WORD_TCU,
    "CVCTV": K.REMARK_WORD_CVCTV,
    "CLD": K.REMARK_WORD_CLD,
    "EMBD": K.REMARK_WORD_EMBD,
    "OBSC": K.REMARK_WORD_OBSC,
    "OBST": K.REMARK_WORD_OBST,
    "MTNS": K.REMARK_WORD_MTNS,
    "MT": K.REMARK_WORD_MT,
    "HZY": K.REMARK_WORD_HZY,
    "VIRGA": K.REMARK_WORD_VIRGA,
    "FROPA": K.REMARK_WORD_FROPA,
    "TORNADO": K.REMARK_WORD_TORNADO,
    "FUNNEL": K.REMARK_WORD_FUNNEL,
    "WATERSPOUT": K.REMARK_WORD_WATERSPOUT,
    "ACFT": K.REMARK_WORD_ACFT,
    "MSHP": K.REMARK_WORD_MSHP,
    "FIRST": K.REMARK_WORD_FIRST,
    "LAST": K.REMARK_WORD_LAST,
    "VCSH": K.REMARK_WORD_VCSH,
    "SHRA": K.REMARK_WORD_SHRA,
    "CLN": K.REMARK_WORD_CLN,
    "AIR": K.REMARK_WORD_AIR,
    "ALL": K.REMARK_WORD_ALL,
    "WNDS": K.REMARK_WORD_WNDS,
    "GRID": K.REMARK_WORD_GRID,
    "LTG": K.REMARK_WORD_LTG,
    "RWY": K.REMARK_WORD_RWY,
    "TWR": K.REMARK_WORD_TWR,
    "SFC": K.REMARK_WORD_SFC,
    "VIS": K.REMARK_WORD_VIS,
}
