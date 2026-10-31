"""Each METAR body group parser, on its own."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from wxbrief.decode.groups.header import parse_modifier, parse_station, parse_time, parse_type
from wxbrief.decode.groups.pressure import parse_pressure
from wxbrief.decode.groups.rvr import parse_rvr
from wxbrief.decode.groups.sky import parse_sky
from wxbrief.decode.groups.tempdew import parse_tempdew
from wxbrief.decode.groups.visibility import parse_visibility
from wxbrief.decode.groups.weather import parse_weather
from wxbrief.decode.groups.wind import parse_wind, parse_wind_variation
from wxbrief.decode.model import (
    RVR,
    CloudLayer,
    CloudType,
    Descriptor,
    Intensity,
    Modifier,
    Phenomenon,
    ReportType,
    RvrTrend,
    SemanticKind,
    SkyCondition,
    VisPrefix,
)
from wxbrief.decode.tokens import Cursor, tokenize
from wxbrief.decode.units import Distance, DistanceUnit, PressureUnit, Speed, SpeedUnit, TemperatureUnit


def run(parser: Callable[[Cursor], Any], text: str) -> tuple[Any, Cursor]:
    cur = Cursor(tokenize(text))
    return parser(cur), cur


# --- header ----------------------------------------------------------------------------------------------------


def test_type() -> None:
    value, cur = run(parse_type, "SPECI KAUS")
    assert value is ReportType.SPECI
    assert cur.pos == 1
    assert run(parse_type, "KDEN")[0] is None


def test_station() -> None:
    assert run(parse_station, "KDEN 131453Z")[0] == "KDEN"
    assert run(parse_station, "K1G4 131453Z")[0] == "K1G4"
    assert run(parse_station, "kden 131453z")[0] == "KDEN"
    assert run(parse_station, "KDEN")[0] == "KDEN"  # the only token
    for text in ("AUTO 131453Z", "COR 131453Z", "9999 131453Z", "KDENX 131453Z", "DEN 131453Z"):
        value, cur = run(parse_station, text)
        assert value is None
        assert cur.pos == 0


def test_station_needs_a_time_or_a_report_type_to_be_believed() -> None:
    assert run(parse_station, "THIS IS NOT A REPORT")[0] is None
    assert run(parse_station, "THIS 131453Z")[0] == "THIS"
    cur = Cursor(tokenize("METAR KDEN FOO"))
    assert parse_type(cur) is ReportType.METAR
    assert parse_station(cur) == "KDEN"


def test_time() -> None:
    value, cur = run(parse_time, "131453Z")
    assert value == (13, 14, 53)
    assert cur.tagged()[0].kind is SemanticKind.TIME
    assert run(parse_time, "131453")[0] is None
    assert run(parse_time, "1314Z")[0] is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("AUTO", Modifier.AUTO),
        ("COR", Modifier.COR),
        ("CCA", Modifier.CCA),
        ("NIL", Modifier.NIL),
        ("RTD", Modifier.RTD),
        ("NOPE", None),
    ],
)
def test_modifier(text: str, expected: Modifier | None) -> None:
    assert run(parse_modifier, text)[0] is expected


# --- wind ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "direction", "speed", "gust", "variable", "above"),
    [
        ("06007KT", 60, Speed(7, SpeedUnit.KT), None, False, False),
        ("00000KT", 0, Speed(0, SpeedUnit.KT), None, False, False),
        ("27015G25KT", 270, Speed(15, SpeedUnit.KT), Speed(25, SpeedUnit.KT), False, False),
        ("VRB03KT", None, Speed(3, SpeedUnit.KT), None, True, False),
        ("36010G105KT", 360, Speed(10, SpeedUnit.KT), Speed(105, SpeedUnit.KT), False, False),
        ("12012MPS", 120, Speed(12, SpeedUnit.MPS), None, False, False),
        ("27010G18MPS", 270, Speed(10, SpeedUnit.MPS), Speed(18, SpeedUnit.MPS), False, False),
        ("25020KMH", 250, Speed(20, SpeedUnit.KMH), None, False, False),
        ("270P49MPS", 270, Speed(49, SpeedUnit.MPS), None, False, True),
        ("/////KT", None, None, None, False, False),
        ("///05KT", None, Speed(5, SpeedUnit.KT), None, False, False),
    ],
)
def test_wind(
    text: str, direction: int | None, speed: Speed | None, gust: Speed | None, variable: bool, above: bool
) -> None:
    wind, cur = run(parse_wind, text)
    assert wind is not None
    assert (wind.direction, wind.speed, wind.gust, wind.variable, wind.speed_above) == (
        direction,
        speed,
        gust,
        variable,
        above,
    )
    assert cur.tagged()[0].kind is SemanticKind.WIND


def test_wind_calm_property() -> None:
    wind, _ = run(parse_wind, "00000KT")
    assert wind is not None
    assert wind.calm
    other, _ = run(parse_wind, "06007KT")
    assert other is not None
    assert not other.calm


@pytest.mark.parametrize("text", ["37010KT", "06007", "060KT", "06007KTS", "99999KT", "KT", ""])
def test_wind_rejects(text: str) -> None:
    value, cur = run(parse_wind, text)
    assert value is None
    assert cur.pos == 0


def test_wind_variation() -> None:
    variation, _ = run(parse_wind_variation, "180V240")
    assert variation is not None
    assert (variation.start, variation.end) == (180, 240)
    assert run(parse_wind_variation, "180V370")[0] is None
    assert run(parse_wind_variation, "180240")[0] is None


# --- visibility ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value", "unit", "prefix", "used"),
    [
        ("10SM", 10, DistanceUnit.SM, None, 1),
        ("3/4SM", 0.75, DistanceUnit.SM, None, 1),
        ("1/2SM", 0.5, DistanceUnit.SM, None, 1),
        ("M1/4SM", 0.25, DistanceUnit.SM, VisPrefix.LESS_THAN, 1),
        ("P6SM", 6, DistanceUnit.SM, VisPrefix.GREATER_THAN, 1),
        ("1 1/2SM", 1.5, DistanceUnit.SM, None, 2),
        ("2 1/4SM", 2.25, DistanceUnit.SM, None, 2),
        ("3000", 3000, DistanceUnit.M, None, 1),
        ("0800", 800, DistanceUnit.M, None, 1),
        ("0000", 50, DistanceUnit.M, VisPrefix.LESS_THAN, 1),
        ("10KM", 10, DistanceUnit.KM, None, 1),
    ],
)
def test_visibility(text: str, value: float, unit: DistanceUnit, prefix: VisPrefix | None, used: int) -> None:
    visibility, cur = run(parse_visibility, text)
    assert visibility is not None
    assert visibility.distance == Distance(value, unit)
    assert visibility.prefix is prefix
    assert cur.pos == used
    assert all(t.kind is SemanticKind.VISIBILITY for t in cur.tagged()[:used])


def test_visibility_9999_is_unlimited() -> None:
    visibility, _ = run(parse_visibility, "9999")
    assert visibility is not None
    assert visibility.unlimited
    assert visibility.distance == Distance(10000, DistanceUnit.M)


def test_visibility_cavok_and_missing() -> None:
    cavok, _ = run(parse_visibility, "CAVOK")
    assert cavok is not None
    assert cavok.cavok
    assert cavok.distance is None
    missing, _ = run(parse_visibility, "////")
    assert missing is not None
    assert missing.not_reported


def test_visibility_directional_minimum() -> None:
    visibility, cur = run(parse_visibility, "6000 2000W 1200NW")
    assert visibility is not None
    assert visibility.distance == Distance(6000, DistanceUnit.M)
    assert [(d.distance.value, d.direction) for d in visibility.directional] == [(2000, "W"), (1200, "NW")]
    assert cur.pos == 3


def test_visibility_minimum_without_direction_must_be_lower() -> None:
    lowered, cur = run(parse_visibility, "0350 0300")
    assert lowered is not None
    assert [(d.distance.value, d.direction) for d in lowered.directional] == [(300, None)]
    assert cur.pos == 2
    higher, cur = run(parse_visibility, "3000 5000")
    assert higher is not None
    assert higher.directional == ()
    assert cur.pos == 1


def test_visibility_ndv() -> None:
    attached, _ = run(parse_visibility, "9999NDV")
    assert attached is not None
    assert attached.ndv
    assert attached.unlimited
    separate, cur = run(parse_visibility, "4000 NDV")
    assert separate is not None
    assert separate.ndv
    assert cur.pos == 2


@pytest.mark.parametrize("text", ["1/0SM", "SM", "10", "1 2", "12345", "99SM9", "FG", "1"])
def test_visibility_rejects(text: str) -> None:
    value, cur = run(parse_visibility, text)
    assert value is None
    assert cur.pos == 0


# --- RVR -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "R35L/P6000FT",
            RVR("35L", Distance(6000, DistanceUnit.FT), VisPrefix.GREATER_THAN),
        ),
        (
            "R21/2000VP6000FT",
            RVR("21", Distance(2000, DistanceUnit.FT), None, Distance(6000, DistanceUnit.FT), VisPrefix.GREATER_THAN),
        ),
        ("R28R/1600FT", RVR("28R", Distance(1600, DistanceUnit.FT))),
        ("R12/1000U", RVR("12", Distance(1000, DistanceUnit.M), trend=RvrTrend.UP)),
        ("R01L/0700N", RVR("01L", Distance(700, DistanceUnit.M), trend=RvrTrend.NO_CHANGE)),
        ("R23/1300D", RVR("23", Distance(1300, DistanceUnit.M), trend=RvrTrend.DOWN)),
        ("R25/M0075", RVR("25", Distance(75, DistanceUnit.M), VisPrefix.LESS_THAN)),
        (
            "R16/0400V0800U",
            RVR("16", Distance(400, DistanceUnit.M), None, Distance(800, DistanceUnit.M), trend=RvrTrend.UP),
        ),
        ("R24C/////", RVR("24C", None)),
    ],
)
def test_rvr(text: str, expected: RVR) -> None:
    rvr, cur = run(parse_rvr, text)
    assert rvr == expected
    assert cur.tagged()[0].kind is SemanticKind.RVR


@pytest.mark.parametrize("text", ["R35L", "R35L/", "R35/600", "R06R/CLRD62", "R24L/290255", "35L/6000FT"])
def test_rvr_rejects(text: str) -> None:
    assert run(parse_rvr, text)[0] is None


# --- weather ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "intensity", "descriptor", "phenomena", "vicinity"),
    [
        ("BR", Intensity.MODERATE, None, (Phenomenon.BR,), False),
        ("-RA", Intensity.LIGHT, None, (Phenomenon.RA,), False),
        ("+TSRA", Intensity.HEAVY, Descriptor.TS, (Phenomenon.RA,), False),
        ("+TSRAGR", Intensity.HEAVY, Descriptor.TS, (Phenomenon.RA, Phenomenon.GR), False),
        ("-SHSN", Intensity.LIGHT, Descriptor.SH, (Phenomenon.SN,), False),
        ("VCFG", Intensity.MODERATE, None, (Phenomenon.FG,), True),
        ("VCTS", Intensity.MODERATE, Descriptor.TS, (), True),
        ("VCSH", Intensity.MODERATE, Descriptor.SH, (), True),
        ("TS", Intensity.MODERATE, Descriptor.TS, (), False),
        ("FZRA", Intensity.MODERATE, Descriptor.FZ, (Phenomenon.RA,), False),
        ("FZFG", Intensity.MODERATE, Descriptor.FZ, (Phenomenon.FG,), False),
        ("BLSN", Intensity.MODERATE, Descriptor.BL, (Phenomenon.SN,), False),
        ("MIFG", Intensity.MODERATE, Descriptor.MI, (Phenomenon.FG,), False),
        ("RASN", Intensity.MODERATE, None, (Phenomenon.RA, Phenomenon.SN), False),
        ("+FC", Intensity.HEAVY, None, (Phenomenon.FC,), False),
        ("UP", Intensity.MODERATE, None, (Phenomenon.UP,), False),
    ],
)
def test_weather(
    text: str,
    intensity: Intensity,
    descriptor: Descriptor | None,
    phenomena: tuple[Phenomenon, ...],
    vicinity: bool,
) -> None:
    group, cur = run(parse_weather, text)
    assert group is not None
    assert (group.intensity, group.descriptor, group.phenomena, group.vicinity) == (
        intensity,
        descriptor,
        phenomena,
        vicinity,
    )
    assert cur.tagged()[0].kind is SemanticKind.WEATHER


def test_weather_nsw_and_not_observed() -> None:
    nsw, _ = run(parse_weather, "NSW")
    assert nsw is not None
    assert nsw.nsw
    missing, _ = run(parse_weather, "//")
    assert missing is not None
    assert missing.not_observed


@pytest.mark.parametrize("text", ["SKC", "BKN010", "VC", "-", "BL", "MI", "FZ", "RAX", "R", "OVC003", "A3001", "RERA"])
def test_weather_rejects(text: str) -> None:
    value, cur = run(parse_weather, text)
    assert value is None
    assert cur.pos == 0


# --- sky -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("FEW030", CloudLayer(SkyCondition.FEW, Distance(3000, DistanceUnit.FT))),
        ("BKN250", CloudLayer(SkyCondition.BKN, Distance(25000, DistanceUnit.FT))),
        ("OVC003", CloudLayer(SkyCondition.OVC, Distance(300, DistanceUnit.FT))),
        ("SCT060CB", CloudLayer(SkyCondition.SCT, Distance(6000, DistanceUnit.FT), CloudType.CB)),
        ("FEW047TCU", CloudLayer(SkyCondition.FEW, Distance(4700, DistanceUnit.FT), CloudType.TCU)),
        ("VV002", CloudLayer(SkyCondition.VV, Distance(200, DistanceUnit.FT))),
        ("VV///", CloudLayer(SkyCondition.VV, None)),
        ("SKC", CloudLayer(SkyCondition.SKC)),
        ("CLR", CloudLayer(SkyCondition.CLR)),
        ("NSC", CloudLayer(SkyCondition.NSC)),
        ("NCD", CloudLayer(SkyCondition.NCD)),
        ("BKN///", CloudLayer(SkyCondition.BKN, None)),
        ("//////", CloudLayer(SkyCondition.UNKNOWN, None)),
        ("///015CB", CloudLayer(SkyCondition.UNKNOWN, Distance(1500, DistanceUnit.FT), CloudType.CB)),
        ("BKN015///", CloudLayer(SkyCondition.BKN, Distance(1500, DistanceUnit.FT), CloudType.UNKNOWN)),
    ],
)
def test_sky(text: str, expected: CloudLayer) -> None:
    layer, cur = run(parse_sky, text)
    assert layer == expected
    assert cur.tagged()[0].kind is SemanticKind.SKY


def test_cloud_layer_ceiling_property() -> None:
    assert CloudLayer(SkyCondition.BKN).is_ceiling_layer
    assert CloudLayer(SkyCondition.VV).is_ceiling_layer
    assert not CloudLayer(SkyCondition.SCT).is_ceiling_layer
    assert not CloudLayer(SkyCondition.CLR).is_ceiling_layer


@pytest.mark.parametrize("text", ["FEW", "BKN30", "OVC0030", "CB", "FEWCB", "///CB", "CAVOK"])
def test_sky_rejects(text: str) -> None:
    assert run(parse_sky, text)[0] is None


# --- temperature and dew point ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "temp", "dew"),
    [
        ("09/08", 9, 8),
        ("M05/M10", -5, -10),
        ("12/M00", 12, 0),
        ("00/M02", 0, -2),
        ("15/", 15, None),
        ("///", None, None),
        ("M02/", -2, None),
        ("15///", 15, None),
    ],
)
def test_tempdew(text: str, temp: int | None, dew: int | None) -> None:
    group, cur = run(parse_tempdew, text)
    assert group is not None
    assert (group.temperature.value if group.temperature else None) == temp
    assert (group.dewpoint.value if group.dewpoint else None) == dew
    if group.temperature:
        assert group.temperature.unit is TemperatureUnit.C
    assert cur.tagged()[0].kind is SemanticKind.TEMPERATURE


@pytest.mark.parametrize("text", ["9/8", "15/13/12", "A3001", "1/2SM", "M5/M10", "ab/cd"])
def test_tempdew_rejects(text: str) -> None:
    assert run(parse_tempdew, text)[0] is None


# --- pressure --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value", "unit"),
    [
        ("A3001", 30.01, PressureUnit.INHG),
        ("A2992", 29.92, PressureUnit.INHG),
        ("Q1013", 1013, PressureUnit.HPA),
        ("Q0998", 998, PressureUnit.HPA),
        ("QNH2992INS", 29.92, PressureUnit.INHG),
    ],
)
def test_pressure(text: str, value: float, unit: PressureUnit) -> None:
    group, cur = run(parse_pressure, text)
    assert group is not None
    assert group.value is not None
    assert group.value.value == value
    assert group.value.unit is unit
    assert cur.tagged()[0].kind is SemanticKind.PRESSURE


def test_pressure_not_available() -> None:
    for text in ("Q////", "A////"):
        group, cur = run(parse_pressure, text)
        assert group is not None
        assert group.value is None
        assert cur.pos == 1


@pytest.mark.parametrize("text", ["A30", "Q101", "B3001", "3001", "A30011"])
def test_pressure_rejects(text: str) -> None:
    assert run(parse_pressure, text)[0] is None
