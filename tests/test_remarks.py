"""Remarks: every variant decoded from its coded form, the groups that must stay free text, and the token kinds."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from wxbrief.decode.metar import parse_metar
from wxbrief.decode.model import (
    AltimeterSetting,
    AutomatedStationType,
    CloudOpacity,
    CloudTypes,
    ColorCode,
    ColorForecast,
    ColorState,
    ColorStateGroup,
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
    Phenomenon,
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
    TrendKind,
    VariableCeiling,
    VariableVisibility,
    WeatherTiming,
    Wind,
    WindAtHeight,
    WindShift,
    WindVariation,
)
from wxbrief.decode.remarks import Context, parse_remarks, synoptic_hour
from wxbrief.decode.tokens import Cursor, tokenize
from wxbrief.decode.units import (
    Distance,
    DistanceUnit,
    Pressure,
    PressureUnit,
    Speed,
    SpeedUnit,
    Temperature,
)

SIX_HOUR = datetime(2026, 10, 31, 11, 56, tzinfo=UTC)  # the 12Z synoptic report
THREE_HOUR = datetime(2026, 10, 31, 14, 53, tzinfo=UTC)  # the 15Z one
ORDINARY = datetime(2026, 10, 31, 9, 53, tzinfo=UTC)  # 10Z: neither

SM = DistanceUnit.SM
FT = DistanceUnit.FT


def decode(text: str, observed: datetime | None = SIX_HOUR) -> list[Remark]:
    return parse_remarks(Cursor(tokenize(text)), Context(observed))


def celsius(value: float) -> Temperature:
    return Temperature(value)


def segment(
    *events: tuple[bool, int, int | None],
    phenomena: tuple[Phenomenon, ...] = (),
    descriptor: Descriptor | None = None,
    intensity: Intensity = Intensity.MODERATE,
) -> TimingSegment:
    return TimingSegment(
        intensity, descriptor, phenomena, tuple(TimingEvent(began, RemarkTime(minute, hour)) for began, minute, hour in events)
    )


RA, DZ, SN = Phenomenon.RA, Phenomenon.DZ, Phenomenon.SN

# Every remark variant appears at least once below (test_every_variant_is_covered checks).
CASES: list[tuple[str, list[Remark]]] = [
    ("AO1", [AutomatedStationType(False)]),
    ("AO2", [AutomatedStationType(True)]),
    # peak wind
    ("PK WND 20032/25", [PeakWind(200, Speed(32, SpeedUnit.KT), RemarkTime(25))]),
    ("PK WND 28045/1547", [PeakWind(280, Speed(45, SpeedUnit.KT), RemarkTime(47, 15))]),
    ("PK WND 280125/0905", [PeakWind(280, Speed(125, SpeedUnit.KT), RemarkTime(5, 9))]),
    # wind shift
    ("WSHFT 1715", [WindShift(RemarkTime(15, 17))]),
    ("WSHFT 30", [WindShift(RemarkTime(30))]),
    ("WSHFT 30 FROPA", [WindShift(RemarkTime(30), frontal_passage=True)]),
    # tower and surface visibility
    ("TWR VIS 2", [TowerVisibility(Distance(2, SM))]),
    ("TWR VIS 1/2", [TowerVisibility(Distance(0.5, SM))]),
    ("TWR VIS 1 1/2", [TowerVisibility(Distance(1.5, SM))]),
    ("SFC VIS 3/4", [SurfaceVisibility(Distance(0.75, SM))]),
    # variable and sector visibility
    ("VIS 3/4V1 1/2", [VariableVisibility(Distance(0.75, SM), Distance(1.5, SM))]),
    ("VIS 2V4", [VariableVisibility(Distance(2, SM), Distance(4, SM))]),
    ("VIS 1/2V2", [VariableVisibility(Distance(0.5, SM), Distance(2, SM))]),
    ("VIS 1 1/2V3", [VariableVisibility(Distance(1.5, SM), Distance(3, SM))]),
    ("VIS NE 2 1/2", [SectorVisibility(Distance(2.5, SM), "NE")]),
    ("VIS 3/4 RWY11", [SectorVisibility(Distance(0.75, SM), "RWY11")]),
    # lightning
    ("FRQ LTG CG NE", [Lightning(LightningFrequency.FREQUENT, (LightningType.CLOUD_TO_GROUND,), ("NE",))]),
    ("LTG DSNT SW", [Lightning(None, (), ("DSNT", "SW"))]),
    (
        "OCNL LTGICCG OHD",
        [Lightning(LightningFrequency.OCCASIONAL, (LightningType.IN_CLOUD, LightningType.CLOUD_TO_GROUND), ("OHD",))],
    ),
    ("CONS LTG", [Lightning(LightningFrequency.CONTINUOUS)]),
    (
        "LTGICCCCGCA",
        [
            Lightning(
                None,
                (
                    LightningType.IN_CLOUD,
                    LightningType.CLOUD_TO_CLOUD,
                    LightningType.CLOUD_TO_GROUND,
                    LightningType.CLOUD_TO_AIR,
                ),
            )
        ],
    ),
    ("LTG CG DSNT NE-E AND NW", [Lightning(None, (LightningType.CLOUD_TO_GROUND,), ("DSNT", "NE-E", "AND", "NW"))]),
    # precipitation and thunderstorm timing
    ("RAB07E45", [WeatherTiming((segment((True, 7, None), (False, 45, None), phenomena=(RA,)),))]),
    ("RAE45", [WeatherTiming((segment((False, 45, None), phenomena=(RA,)),))]),
    (
        "TSB0159E30",
        [WeatherTiming((segment((True, 59, 1), (False, 30, None), descriptor=Descriptor.TS),))],
    ),
    ("SHRAB25", [WeatherTiming((segment((True, 25, None), phenomena=(RA,), descriptor=Descriptor.SH),))]),
    (
        "DZB04E37RAB37",
        [
            WeatherTiming(
                (
                    segment((True, 4, None), (False, 37, None), phenomena=(DZ,)),
                    segment((True, 37, None), phenomena=(RA,)),
                )
            )
        ],
    ),
    (
        "RAE0755RAB22E31",
        [
            WeatherTiming(
                (
                    segment((False, 55, 7), phenomena=(RA,)),
                    segment((True, 22, None), (False, 31, None), phenomena=(RA,)),
                )
            )
        ],
    ),
    ("-SNB10", [WeatherTiming((segment((True, 10, None), phenomena=(SN,), intensity=Intensity.LIGHT),))]),
    (
        "FZRAB1530E1630",
        [WeatherTiming((segment((True, 30, 15), (False, 30, 16), phenomena=(RA,), descriptor=Descriptor.FZ),))],
    ),
    # ceilings
    ("CIG 013V017", [VariableCeiling(Distance(1300, FT), Distance(1700, FT))]),
    ("CIG 017 RWY11", [SecondaryCeiling(Distance(1700, FT), "RWY11")]),
    ("CIG 009 NE", [SecondaryCeiling(Distance(900, FT), "NE")]),
    # pressure
    ("PRESRR", [PressureRapidChange(rising=True)]),
    ("PRESFR", [PressureRapidChange(rising=False)]),
    ("SLP177", [SeaLevelPressure(Pressure(1017.7, PressureUnit.HPA))]),
    ("SLP045", [SeaLevelPressure(Pressure(1004.5, PressureUnit.HPA))]),
    ("SLP232", [SeaLevelPressure(Pressure(1023.2, PressureUnit.HPA))]),
    ("SLP882", [SeaLevelPressure(Pressure(988.2, PressureUnit.HPA))]),
    ("SLP125", [SeaLevelPressure(Pressure(1012.5, PressureUnit.HPA))]),
    ("SLP500", [SeaLevelPressure(Pressure(950.0, PressureUnit.HPA))]),  # 5 is the first digit read as 9xx
    ("SLP499", [SeaLevelPressure(Pressure(1049.9, PressureUnit.HPA))]),
    ("SLP000", [SeaLevelPressure(Pressure(1000.0, PressureUnit.HPA))]),
    ("SLPNO", [SeaLevelPressure(None)]),
    # precipitation amounts
    ("P0003", [HourlyPrecipitation(0.03)]),
    ("P0000", [HourlyPrecipitation(0.0, trace=True)]),
    ("P////", [HourlyPrecipitation(None)]),
    ("60009", [PeriodPrecipitation(0.09, 6)]),
    ("60000", [PeriodPrecipitation(0.0, 6, trace=True)]),
    ("6////", [PeriodPrecipitation(None, 6)]),
    ("70015", [DailyPrecipitation(0.15)]),
    ("7////", [DailyPrecipitation(None)]),
    # temperatures
    ("T02330200", [PreciseTemperature(celsius(23.3), celsius(20.0))]),
    ("T10171028", [PreciseTemperature(celsius(-1.7), celsius(-2.8))]),
    ("T00000000", [PreciseTemperature(celsius(0.0), celsius(0.0))]),
    ("T0233", [PreciseTemperature(celsius(23.3), None)]),
    ("10233", [MaxTemperature6Hour(celsius(23.3))]),
    ("10066", [MaxTemperature6Hour(celsius(6.6))]),
    ("11012", [MaxTemperature6Hour(celsius(-1.2))]),
    ("1////", [MaxTemperature6Hour(None)]),
    ("20189", [MinTemperature6Hour(celsius(18.9))]),
    ("21012", [MinTemperature6Hour(celsius(-1.2))]),
    ("2////", [MinTemperature6Hour(None)]),
    ("400461006", [DailyTemperatureExtremes(celsius(4.6), celsius(-0.6))]),
    ("402220150", [DailyTemperatureExtremes(celsius(22.2), celsius(15.0))]),
    # 3-hour tendency
    ("53011", [PressureTendency(3, TendencyDirection.HIGHER, 1.1)]),
    ("53008", [PressureTendency(3, TendencyDirection.HIGHER, 0.8)]),
    ("58033", [PressureTendency(8, TendencyDirection.LOWER, 3.3)]),
    ("52032", [PressureTendency(2, TendencyDirection.HIGHER, 3.2)]),
    ("54000", [PressureTendency(4, TendencyDirection.SAME, 0.0)]),
    ("50001", [PressureTendency(0, TendencyDirection.HIGHER, 0.1)]),
    ("56002", [PressureTendency(6, TendencyDirection.LOWER, 0.2)]),
    # sensors and maintenance
    ("RVRNO", [SensorStatus(SensorKind.RVR)]),
    ("PWINO", [SensorStatus(SensorKind.PRESENT_WEATHER)]),
    ("PNO", [SensorStatus(SensorKind.PRECIPITATION)]),
    ("FZRANO", [SensorStatus(SensorKind.FREEZING_RAIN)]),
    ("TSNO", [SensorStatus(SensorKind.THUNDERSTORM)]),
    ("VISNO RWY11", [SensorStatus(SensorKind.VISIBILITY, "RWY11")]),
    ("CHINO", [SensorStatus(SensorKind.CEILING)]),
    ("CHINO NE", [SensorStatus(SensorKind.CEILING, "NE")]),
    ("$", [MaintenanceIndicator()]),
    # snow, cloud types, hail, density altitude
    ("4/012", [SnowDepth(12.0)]),
    ("4////", [SnowDepth(None)]),
    ("SNINCR 2/10", [SnowIncrease(2.0, 10.0)]),
    ("8/208", [CloudTypes(2, 0, 8)]),
    ("8/1//", [CloudTypes(1, None, None)]),
    ("GR 1 3/4", [HailSize(1.75)]),
    ("GR 1/4", [HailSize(0.25)]),
    ("GR LESS THAN 1/4", [HailSize(0.25, less_than=True)]),
    ("GR 2", [HailSize(2.0)]),
    ("DENSITY ALT 2500FT", [DensityAltitude(Distance(2500, FT))]),
    ("DENSITY ALTITUDE 1800FT", [DensityAltitude(Distance(1800, FT))]),
    # Canadian cloud opacity
    ("SC5AC2", [CloudOpacity((OpacityLayer("SC", 5), OpacityLayer("AC", 2)))]),
    ("SC1SC5SC2", [CloudOpacity((OpacityLayer("SC", 1), OpacityLayer("SC", 5), OpacityLayer("SC", 2)))]),
    ("AC1 AC TR", [CloudOpacity((OpacityLayer("AC", 1), OpacityLayer("AC", None, trace=True)))]),
    ("ST3AC2AC1", [CloudOpacity((OpacityLayer("ST", 3), OpacityLayer("AC", 2), OpacityLayer("AC", 1)))]),
    ("ACC3TCU2", [CloudOpacity((OpacityLayer("ACC", 3), OpacityLayer("TCU", 2)))]),
    # altimeter and station pressure
    ("A3007", [AltimeterSetting(Pressure(30.07, PressureUnit.INHG))]),
    ("A30.06", [AltimeterSetting(Pressure(30.06, PressureUnit.INHG))]),
    ("QFE756/1008", [StationPressure(StationPressureKind.QFE, 756, 1008)]),
    ("QFE740/0987", [StationPressure(StationPressureKind.QFE, 740, 987)]),
    ("QFE992", [StationPressure(StationPressureKind.QFE, None, 992)]),
    ("QFE763", [StationPressure(StationPressureKind.QFE, 763, None)]),
    ("QNH766", [StationPressure(StationPressureKind.QNH, 766, None)]),
    # runway winds
    ("RWY17L 02008KT", [RunwayWind("17L", Wind(20, Speed(8, SpeedUnit.KT)))]),
    ("R06/31003MPS", [RunwayWind("06", Wind(310, Speed(3, SpeedUnit.MPS)))]),
    ("RWY18C 01003KT 310V110", [RunwayWind("18C", Wind(10, Speed(3, SpeedUnit.KT)), WindVariation(310, 110))]),
    ("RWY36R VRB02KT", [RunwayWind("36R", Wind(None, Speed(2, SpeedUnit.KT), variable=True))]),
    ("WIND 2600FT 19040KT", [WindAtHeight(Distance(2600, FT), Wind(190, Speed(40, SpeedUnit.KT)))]),
    ("WIND 1400FT 21024G35KT", [WindAtHeight(Distance(1400, FT), Wind(210, Speed(24, SpeedUnit.KT), Speed(35, SpeedUnit.KT)))]),
    # colour states in the remarks
    (
        "RED BECMG AMB",
        [
            ColorStateRemark(
                ColorStateGroup(
                    ColorState(ColorCode.RED), (ColorForecast(ColorState(ColorCode.AMB), TrendKind.BECMG),)
                )
            )
        ],
    ),
    (
        "YLO1 YLO1",
        [ColorStateRemark(ColorStateGroup(ColorState(ColorCode.YLO1), (ColorForecast(ColorState(ColorCode.YLO1)),)))],
    ),
    # free text, alone and between coded groups
    ("CB DSNT NW", [FreeText("CB DSNT NW")]),
    ("TORNADO B25 N MOV E", [FreeText("TORNADO B25 N MOV E")]),
    ("AO2 VIRGA SLP100", [AutomatedStationType(True), FreeText("VIRGA"), SeaLevelPressure(Pressure(1010.0, PressureUnit.HPA))]),
    ("OBST OBSC", [FreeText("OBST OBSC")]),
    ("", []),
]


@pytest.mark.parametrize(("text", "expected"), CASES, ids=[case[0] or "empty" for case in CASES])
def test_remark_groups(text: str, expected: list[Remark]) -> None:
    assert decode(text) == expected


def all_variants() -> set[type[Remark]]:
    found: set[type[Remark]] = set()
    pending = list(Remark.__subclasses__())
    while pending:
        cls = pending.pop()
        found.add(cls)
        pending.extend(cls.__subclasses__())
    return found


def test_every_variant_is_covered() -> None:
    covered = {type(remark) for _, expected in CASES for remark in expected}
    assert all_variants() - covered == set()
    assert len(all_variants()) >= 30


# --- the groups that depend on the report time ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("observed", "hours"),
    [
        (datetime(2026, 10, 31, 11, 56, tzinfo=UTC), 6),  # a :56 report is the next hour's: 12Z
        (datetime(2026, 10, 31, 12, 0, tzinfo=UTC), 6),
        (datetime(2026, 10, 31, 17, 53, tzinfo=UTC), 6),  # 18Z
        (datetime(2026, 10, 31, 23, 56, tzinfo=UTC), 6),  # 00Z of the next day
        (datetime(2026, 10, 31, 14, 53, tzinfo=UTC), 3),  # 15Z
        (datetime(2026, 10, 31, 2, 56, tzinfo=UTC), 3),  # 03Z
        (datetime(2026, 10, 31, 8, 53, tzinfo=UTC), 3),  # 09Z
        (datetime(2026, 10, 31, 9, 53, tzinfo=UTC), None),  # 10Z
        (datetime(2026, 10, 31, 12, 40, tzinfo=UTC), None),  # the nearest hour is 13Z
        (None, None),
    ],
)
def test_the_period_of_the_6_group_follows_the_report_time(observed: datetime | None, hours: int | None) -> None:
    assert decode("60009", observed) == [PeriodPrecipitation(0.09, hours)]


def test_synoptic_hour() -> None:
    assert synoptic_hour(datetime(2026, 10, 31, 11, 56, tzinfo=UTC)) == 12
    assert synoptic_hour(datetime(2026, 10, 31, 23, 45, tzinfo=UTC)) == 0
    assert synoptic_hour(datetime(2026, 10, 31, 6, 29, tzinfo=UTC)) == 6
    assert synoptic_hour(None) is None


# --- what must not decode --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "PK WND 99945/25",  # direction over 360
        "PK WND",
        "WSHFT 2575",  # not a time
        "WSHFT",
        "TWR VIS",
        "SFC VIS X",
        "VIS",
        "VIS 2",  # a bare visibility says nothing about where
        "VIS 3/0V4",
        "FRQ",
        "LTGXX",
        "RAB2530",  # hour 25
        "RAB",
        "SHB10",  # a descriptor alone is no precipitation
        "CIG 017",
        "CIG",
        "SLP17",
        "SLP1777",
        "59000",  # tendency characters run 0-8
        "T0233X",
        "T2233",
        "4/12",
        "8/20",
        "GR",
        "GR X",
        "DENSITY ALT",
        "DENSITY ALT SOON",
        "SC",
        "SC9X",
        "QFE",
        "RWY17L",
        "RWY17L 99",
        "WIND 2600FT",
        "WIND SOON 19040KT",
        "RMK",
    ],
)
def test_malformed_groups_stay_free_text(text: str) -> None:
    result = decode(text)
    assert result == [FreeText(text)]


def test_consecutive_unknown_tokens_form_one_free_text() -> None:
    assert decode("FOO BAR AO2 BAZ") == [FreeText("FOO BAR"), AutomatedStationType(True), FreeText("BAZ")]


def test_the_terminator_is_not_part_of_a_remark() -> None:
    cur = Cursor(tokenize("AO2 FOO ="))
    remarks = parse_remarks(cur, Context(SIX_HOUR))
    assert remarks == [AutomatedStationType(True), FreeText("FOO")]
    assert cur.at_end
    assert [tok.kind for tok in cur.tagged()][-1] is SemanticKind.TERMINATOR


def test_lowercase_input_is_decoded() -> None:
    assert decode("pk wnd 20032/25 slp177") == [
        PeakWind(200, Speed(32, SpeedUnit.KT), RemarkTime(25)),
        SeaLevelPressure(Pressure(1017.7, PressureUnit.HPA)),
    ]


# --- tagging ---------------------------------------------------------------------------------------------------


def test_tokens_are_tagged_by_what_they_are() -> None:
    cur = Cursor(tokenize("AO2 PK WND 20032/25 SLP177 T02330200 CIG 013V017 RAB07E45 TWR VIS 2 PRESRR $ OBST"))
    parse_remarks(cur, Context(SIX_HOUR))
    kinds = [tok.kind.name for tok in cur.tagged()]
    assert kinds == [
        "REMARK",  # AO2
        "WIND",
        "WIND",
        "WIND",
        "PRESSURE",  # SLP
        "TEMPERATURE",  # T-group
        "SKY",
        "SKY",  # CIG
        "WEATHER",  # RAB07E45
        "VISIBILITY",
        "VISIBILITY",
        "VISIBILITY",  # TWR VIS 2
        "PRESSURE",  # PRESRR
        "REMARK",  # $
        "REMARK",  # OBST
    ]


def test_remarks_of_selects_a_variant() -> None:
    metar = parse_metar("METAR KDEN 311153Z 18006KT 10SM CLR 08/06 A3004 RMK AO2 SLP135 60009 T00830061 $", SIX_HOUR)
    assert [r.pressure for r in metar.remarks_of(SeaLevelPressure)] == [Pressure(1013.5, PressureUnit.HPA)]
    assert metar.remarks_of(PeriodPrecipitation) == (PeriodPrecipitation(0.09, 6),)
    assert metar.remarks_of(Lightning) == ()


def test_a_colour_state_in_the_remarks_marks_the_report_military_and_fills_color_state() -> None:
    metar = parse_metar("METAR EGWU 310820Z 12005KT 3500 BR BKN006 10/09 Q1031 NOSIG RMK YLO1 YLO1", SIX_HOUR)
    assert metar.military
    assert metar.color_state == ColorStateGroup(ColorState(ColorCode.YLO1), (ColorForecast(ColorState(ColorCode.YLO1)),))
    assert metar.remarks == (ColorStateRemark(metar.color_state),)
    assert metar.warnings == ()


def test_a_remarks_failure_cannot_escape(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(cur: Cursor, ctx: Context) -> list[Remark]:
        raise RuntimeError("boom")

    monkeypatch.setattr("wxbrief.decode.metar.parse_remarks", boom)
    metar = parse_metar("METAR KDEN 311153Z 18006KT 10SM CLR 08/06 A3004 RMK AO2 SLP135", SIX_HOUR)
    assert metar.remarks == ()
    assert [warning.code for warning in metar.warnings] == ["parser_error"]
    assert all(tok.kind is SemanticKind.REMARK for tok in metar.tokens[-3:])  # nothing lost
