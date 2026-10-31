"""Code tables: report codes to model enums, and model enums to catalog keys.

Ported from the weather-phenomena and international references. Nothing here holds English words: the ``*_KEYS``
tables point into the translation catalog, which is where the words live.
"""

from __future__ import annotations

from wxbrief.decode.model import (
    CloudType,
    Descriptor,
    Flag,
    FlightCategory,
    Intensity,
    Modifier,
    Phenomenon,
    ReportType,
    RvrTrend,
    SkyCondition,
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

# NATO colour-state codes that appear on military reports; decoded in a later session, recognised here.
COLOR_STATE_BASE_CODES: frozenset[str] = frozenset({"BLU", "WHT", "GRN", "YLO", "YLO1", "YLO2", "AMB", "RED"})

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
