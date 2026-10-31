"""Sentences built by ``render/phrases.py`` and the measurement formatters behind them."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from wxbrief.decode.metar import parse_metar
from wxbrief.decode.model import CeilingStatus, Flag, FlightCategory, Metar
from wxbrief.decode.units import (
    Distance,
    DistanceUnit,
    Pressure,
    PressureUnit,
    Speed,
    SpeedUnit,
    Temperature,
    TemperatureUnit,
    UnitsMode,
)
from wxbrief.i18n import Translator, lower_first
from wxbrief.render import measure, phrases
from wxbrief.render.jsonout import to_dict

T = Translator.load("en")
US, METRIC, MIXED = UnitsMode.US, UnitsMode.METRIC, UnitsMode.MIXED
REF = datetime(2026, 10, 13, 15, 0, tzinfo=UTC)


def decode(body: str) -> Metar:
    return parse_metar(f"METAR KXYZ 131453Z {body}", REF)


# --- measure --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("speed", "units", "expected"),
    [
        (Speed(7, SpeedUnit.KT), MIXED, "7 kt (13 km/h)"),
        (Speed(7, SpeedUnit.KT), US, "7 kt"),
        (Speed(7, SpeedUnit.KT), METRIC, "13 km/h (7 kt)"),
        (Speed(12, SpeedUnit.MPS), MIXED, "12 m/s (23 kt)"),
        (Speed(12, SpeedUnit.MPS), US, "23 kt (12 m/s)"),
        (Speed(12, SpeedUnit.MPS), METRIC, "12 m/s"),
        (Speed(36, SpeedUnit.KMH), MIXED, "36 km/h (19 kt)"),
    ],
)
def test_format_speed(speed: Speed, units: UnitsMode, expected: str) -> None:
    assert measure.format_speed(speed, units) == expected


@pytest.mark.parametrize(
    ("distance", "units", "expected"),
    [
        (Distance(0.75, DistanceUnit.SM), MIXED, "3/4 SM (1.2 km)"),
        (Distance(1.5, DistanceUnit.SM), US, "1 1/2 SM"),
        (Distance(10, DistanceUnit.SM), METRIC, "16.1 km (10 SM)"),
        (Distance(0.25, DistanceUnit.SM), MIXED, "1/4 SM (400 m)"),
        (Distance(6, DistanceUnit.SM), MIXED, "6 SM (9.7 km)"),
        (Distance(1200, DistanceUnit.M), MIXED, "1.2 km (3/4 SM)"),
        (Distance(800, DistanceUnit.M), MIXED, "800 m (1/2 SM)"),
        (Distance(800, DistanceUnit.M), US, "1/2 SM (800 m)"),
        (Distance(800, DistanceUnit.M), METRIC, "800 m"),
        (Distance(10, DistanceUnit.KM), MIXED, "10 km (6.2 SM)"),
        (Distance(50, DistanceUnit.M), MIXED, "50 m (1/16 SM)"),
        (Distance(0, DistanceUnit.SM), US, "0 SM"),
        # a converted figure is never rounded across a flight-category limit (1 and 3 SM)
        (Distance(1600, DistanceUnit.M), MIXED, "1.6 km (15/16 SM)"),
        (Distance(4800, DistanceUnit.M), MIXED, "4.8 km (2.9 SM)"),
        (Distance(8000, DistanceUnit.M), MIXED, "8 km (5 SM)"),
        (Distance(1700, DistanceUnit.M), MIXED, "1.7 km (1.1 SM)"),
    ],
)
def test_format_visibility(distance: Distance, units: UnitsMode, expected: str) -> None:
    assert measure.format_visibility(distance, units) == expected


@pytest.mark.parametrize(
    ("distance", "units", "expected"),
    [
        (Distance(300, DistanceUnit.FT), MIXED, "300 ft (91 m)"),
        (Distance(25000, DistanceUnit.FT), US, "25,000 ft"),
        (Distance(25000, DistanceUnit.FT), METRIC, "7,620 m (25,000 ft)"),
        (Distance(600, DistanceUnit.M), MIXED, "600 m (1,970 ft)"),
        (Distance(6000, DistanceUnit.FT), MIXED, "6,000 ft (1,829 m)"),
    ],
)
def test_format_short_distance(distance: Distance, units: UnitsMode, expected: str) -> None:
    assert measure.format_short_distance(distance, units) == expected


@pytest.mark.parametrize(
    ("pressure", "units", "expected"),
    [
        (Pressure(30.01, PressureUnit.INHG), MIXED, "30.01 inHg (1016 hPa)"),
        (Pressure(30.01, PressureUnit.INHG), US, "30.01 inHg"),
        (Pressure(30.01, PressureUnit.INHG), METRIC, "1016 hPa (30.01 inHg)"),
        (Pressure(1013, PressureUnit.HPA), MIXED, "1013 hPa (29.91 inHg)"),
        (Pressure(1013, PressureUnit.HPA), US, "29.91 inHg (1013 hPa)"),
        (Pressure(1013, PressureUnit.HPA), METRIC, "1013 hPa"),
    ],
)
def test_format_pressure(pressure: Pressure, units: UnitsMode, expected: str) -> None:
    assert measure.format_pressure(pressure, units) == expected


@pytest.mark.parametrize(
    ("temperature", "units", "expected"),
    [
        (Temperature(9), MIXED, "9 °C (48 °F)"),
        (Temperature(9), US, "48 °F (9 °C)"),
        (Temperature(9), METRIC, "9 °C"),
        (Temperature(-5), MIXED, "-5 °C (23 °F)"),
        (Temperature(68, TemperatureUnit.F), MIXED, "68 °F (20 °C)"),
    ],
)
def test_format_temperature(temperature: Temperature, units: UnitsMode, expected: str) -> None:
    assert measure.format_temperature(temperature, units) == expected


def test_number_helpers() -> None:
    assert measure.format_int(3000) == "3,000"
    assert measure.format_decimal(10.0) == "10"
    assert measure.format_decimal(1.25) == "1.2"
    assert measure.format_decimal(0.0) == "0"
    assert measure.format_miles(0.75, exact=True) == "3/4"
    assert measure.format_miles(2.25, exact=True) == "2 1/4"
    assert measure.format_miles(1.0, exact=True) == "1"
    assert measure.format_miles(1.9, exact=False) == "1.9"
    assert measure.format_miles(12.4, exact=False) == "12"


# --- wind -----------------------------------------------------------------------------------------------------


def wind_of(token: str, variation: str = "", units: UnitsMode = US) -> str:
    m = decode(f"{token} {variation} 10SM CLR 09/08 A3001")
    assert m.wind is not None
    return phrases.describe_wind(T, m.wind, units, m.wind_variation)


def test_describe_wind() -> None:
    assert wind_of("06007KT") == "From 060° (ENE) at 7 kt"
    assert wind_of("00000KT") == "Calm"
    assert wind_of("VRB03KT") == "Variable direction at 3 kt"
    assert wind_of("27015G25KT") == "From 270° (W) at 15 kt, gusting to 25 kt"
    assert wind_of("21012G20KT", "180V240") == (
        "From 210° (SSW) at 12 kt, gusting to 20 kt; direction varies between 180° and 240°"
    )
    assert wind_of("36010KT") == "From 360° (N) at 10 kt"
    assert wind_of("12012MPS", units=MIXED) == "From 120° (ESE) at 12 m/s (23 kt)"
    assert wind_of("/////KT") == "Not reported"
    assert wind_of("///05KT") == "Direction not reported, 5 kt"
    assert wind_of("270P49MPS", units=METRIC) == "From 270° (W) at more than 49 m/s"


# --- visibility -----------------------------------------------------------------------------------------------


def vis_of(body: str, units: UnitsMode = MIXED) -> str:
    m = decode(f"06007KT {body} CLR 09/08 Q1013")
    assert m.visibility is not None
    return phrases.describe_visibility(T, m.visibility, units)


def test_describe_visibility() -> None:
    assert vis_of("3/4SM") == "3/4 SM (1.2 km)"
    assert vis_of("1 1/2SM", US) == "1 1/2 SM"
    assert vis_of("M1/4SM", US) == "less than 1/4 SM"
    assert vis_of("P6SM") == "more than 6 SM (9.7 km)"
    assert vis_of("CAVOK") == (
        "CAVOK: visibility at least 10 km (6.2 SM), no cloud below 5,000 ft (1,524 m), no significant weather"
    )
    assert (
        vis_of("CAVOK", US)
        == "CAVOK: visibility at least 6.2 SM (10 km), no cloud below 5,000 ft, no significant weather"
    )
    assert (
        vis_of("CAVOK", METRIC)
        == "CAVOK: visibility at least 10 km, no cloud below 1,524 m (5,000 ft), no significant weather"
    )
    assert vis_of("9999") == "at least 10 km (6.2 SM)"
    assert vis_of("9999", METRIC) == "at least 10 km"
    assert vis_of("0000", METRIC) == "less than 50 m"
    assert vis_of("1200", METRIC) == "1.2 km"
    assert vis_of("6000 2000W") == "6 km (3.7 SM); lowest 2 km (1.2 SM) toward W"
    assert vis_of("0350 0300") == "350 m (3/16 SM); lowest 300 m (3/16 SM)"
    assert vis_of("9999NDV") == "at least 10 km (6.2 SM), no directional variation"
    assert vis_of("////") == "Not reported"


# --- RVR ------------------------------------------------------------------------------------------------------


def rvr_of(group: str, units: UnitsMode = MIXED) -> str:
    m = decode(f"06007KT 1/2SM {group} FG VV002 09/08 A3001")
    assert m.rvr
    return phrases.describe_rvr(T, m.rvr[0], units)


def test_describe_rvr() -> None:
    assert rvr_of("R35L/P6000FT") == "Runway 35L: more than 6,000 ft (1,829 m)"
    assert rvr_of("R21/2000VP6000FT", US) == "Runway 21: varying between 2,000 ft and more than 6,000 ft"
    assert rvr_of("R12/1000U", METRIC) == "Runway 12: 1,000 m, increasing"
    assert rvr_of("R12/0600D", METRIC) == "Runway 12: 600 m, decreasing"
    assert rvr_of("R12/0600N", METRIC) == "Runway 12: 600 m, no change"
    assert rvr_of("R12/M0050", METRIC) == "Runway 12: less than 50 m"
    assert rvr_of("R12/////", METRIC) == "Runway 12: not reported"


# --- weather --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("groups", "expected"),
    [
        ("BR", "Mist"),
        ("-RA", "Light rain"),
        ("+TSRA", "Thunderstorm with heavy rain"),
        ("-TSRA", "Thunderstorm with light rain"),
        ("+TSRAGR", "Thunderstorm with heavy rain and hail"),
        ("+TSGR", "Thunderstorm with heavy hail"),
        ("+SHRA", "Heavy rain showers"),
        ("-SHSN", "Light snow showers"),
        ("VCFG", "Fog in the vicinity"),
        ("VCTS", "Thunderstorm in the vicinity"),
        ("VCSH", "Showers in the vicinity"),
        ("TS", "Thunderstorm"),
        ("FZRA", "Freezing rain"),
        ("FZFG", "Freezing fog"),
        ("BLSN", "Blowing snow"),
        ("DRSN", "Low drifting snow"),
        ("BCFG", "Patches of fog"),
        ("MIFG", "Shallow fog"),
        ("PRFG", "Partial fog"),
        ("RASN", "Rain and snow"),
        ("-RA BR", "Light rain and mist"),
        ("+RA BR HZ", "Heavy rain, mist, and haze"),
        ("+FC", "Tornado or waterspout"),
        ("SQ", "Squalls"),
        ("NSW", "No significant weather"),
        ("//", "Not observed"),
    ],
)
def test_describe_weather(groups: str, expected: str) -> None:
    m = decode(f"06007KT 3SM {groups} OVC010 09/08 A3001")
    assert m.warnings == ()
    assert phrases.describe_weather(T, m.weather) == expected


# --- sky ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("layer", "units", "expected"),
    [
        ("FEW030", US, "Few clouds at 3,000 ft"),
        ("SCT060CB", US, "Scattered clouds at 6,000 ft, cumulonimbus"),
        ("BKN025TCU", MIXED, "Broken clouds at 2,500 ft (762 m), towering cumulus"),
        ("OVC003", MIXED, "Overcast at 300 ft (91 m)"),
        ("OVC003", METRIC, "Overcast at 91 m (300 ft)"),
        ("VV002", US, "Sky obscured, vertical visibility 200 ft"),
        ("VV///", US, "Sky obscured, vertical visibility not determined"),
        ("SKC", US, "Sky clear"),
        ("CLR", US, "Clear below 12,000 ft"),
        ("NSC", US, "No significant cloud"),
        ("NCD", US, "No cloud detected"),
        ("BKN///", US, "Broken clouds, height not determined"),
        ("//////", US, "Cloud amount not determined"),
        ("///015CB", US, "Cloud amount not determined at 1,500 ft, cumulonimbus"),
        ("BKN015///", US, "Broken clouds at 1,500 ft, cloud type not determined"),
    ],
)
def test_describe_cloud_layer(layer: str, units: UnitsMode, expected: str) -> None:
    m = decode(f"06007KT 10SM {layer} 09/08 A3001")
    assert m.warnings == ()
    assert phrases.describe_cloud_layer(T, m.sky[0], units) == expected


def test_describe_sky_and_ceiling() -> None:
    m = decode("06007KT 10SM FEW010 BKN030 09/08 A3001")
    assert phrases.describe_sky(T, m.sky, US) == "Few clouds at 1,000 ft; Broken clouds at 3,000 ft"
    assert phrases.describe_ceiling(T, m, US) == "3,000 ft"
    assert phrases.describe_ceiling(T, decode("06007KT 10SM FEW010 09/08 A3001"), US) == "None"


@pytest.mark.parametrize("sky", ["VV///", "BKN///", "FEW010 OVC///"])
def test_a_ceiling_of_unknown_height_is_not_called_none(sky: str) -> None:
    m = decode(f"05010KT 10SM {sky} 10/10 A3001")
    assert m.ceiling is None
    assert m.ceiling_status is CeilingStatus.UNKNOWN
    assert phrases.describe_ceiling(T, m, US) == "not determined"
    assert phrases.summary_line(T, m, US).endswith(
        "ceiling not determined, visibility 10 SM, wind from 050° (NE) at 10 kt."
    )
    assert to_dict(m)["ceiling_status"] == "UNKNOWN"


def test_ceiling_status_for_known_and_absent_ceilings() -> None:
    assert decode("06007KT 10SM BKN030 09/08 A3001").ceiling_status is CeilingStatus.HEIGHT
    assert decode("06007KT 10SM SCT030 09/08 A3001").ceiling_status is CeilingStatus.NONE
    assert decode("06007KT CAVOK 09/08 Q1013").ceiling_status is CeilingStatus.NONE
    assert decode("06007KT 10SM 09/08 A3001").ceiling_status is None


# --- temperature, pressure, misc ------------------------------------------------------------------------------


def test_describe_temperature_pressure_and_humidity() -> None:
    assert phrases.describe_temperature(T, Temperature(9), MIXED) == "9 °C (48 °F)"
    assert phrases.describe_temperature(T, None, MIXED) == "Not reported"
    assert phrases.describe_pressure(T, Pressure(1013, PressureUnit.HPA), MIXED) == "1013 hPa (29.91 inHg)"
    assert phrases.describe_pressure(T, None, MIXED) == "Not reported"
    assert phrases.describe_humidity(T, 93.5) == "94%"


def test_describe_time_and_labels() -> None:
    assert phrases.describe_time(T, datetime(2026, 10, 13, 14, 53, tzinfo=UTC)) == "2026-10-13 14:53 UTC"
    assert phrases.describe_time(T, None) == "Not available"
    assert phrases.describe_flight_category(T, FlightCategory.LIFR) == "LIFR (low instrument flight rules)"
    assert phrases.describe_flag(T, Flag.LOW_CEILING) == "Low ceiling"


def test_case_helpers() -> None:
    assert phrases.upper_first("light rain") == "Light rain"
    assert phrases.upper_first("") == ""
    assert lower_first("Light rain") == "light rain"
    assert lower_first("CAVOK: fine") == "CAVOK: fine"
    assert lower_first("10 km") == "10 km"
    assert lower_first("A") == "a"


def test_join_list() -> None:
    assert phrases.join_list(T, []) == ""
    assert phrases.join_list(T, ["a"]) == "a"
    assert phrases.join_list(T, ["a", "b"]) == "a and b"
    assert phrases.join_list(T, ["a", "b", "c"]) == "a, b, and c"


def test_describe_warning() -> None:
    m = parse_metar("METAR KDEN FOO", REF)
    assert phrases.describe_warning(T, m.warnings[0]) == "Unrecognized group: FOO"
    from wxbrief.decode.model import ParseWarning

    assert phrases.describe_warning(T, ParseWarning("something_new", 0, 1, "X")) == "something_new: X"


# --- summary --------------------------------------------------------------------------------------------------


def test_summary_line_for_the_cobol_sample() -> None:
    m = parse_metar("METAR KDEN 131453Z 06007KT 3/4SM R35L/P6000FT BR OVC003 09/08 A3001 RMK AO2 SFC", REF)
    assert phrases.summary_line(T, m, US) == (
        "KDEN is reporting LIFR (low instrument flight rules): mist, ceiling 300 ft, "
        "visibility 3/4 SM, wind from 060° (ENE) at 7 kt."
    )


def test_summary_line_for_cavok() -> None:
    m = parse_metar("METAR EGLL 311050Z 24010KT CAVOK 12/08 Q1013", REF)
    assert phrases.summary_line(T, m, METRIC) == (
        "EGLL is reporting VFR (visual flight rules): ceiling and visibility OK, wind from 240° (WSW) at 19 km/h (10 kt)."
    )


def test_summary_line_without_station_or_category() -> None:
    assert (
        phrases.summary_line(T, parse_metar("06007KT", REF), US) == "This report shows: wind from 060° (ENE) at 7 kt."
    )
    assert phrases.summary_line(T, parse_metar("06007KT 10SM CLR", REF), US).startswith("This report shows VFR (visual")
    assert phrases.summary_line(T, parse_metar("METAR KDEN 131453Z 06007KT", REF), US) == (
        "KDEN is reporting: wind from 060° (ENE) at 7 kt."
    )


def test_summary_line_when_nothing_decodes() -> None:
    assert phrases.summary_line(T, parse_metar("hello", REF), US) == "No conditions could be decoded."
