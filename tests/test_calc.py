"""Pure calculations: airport lookup, pressure and density altitude, dew point spread, runway wind."""

from __future__ import annotations

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from wxbrief.calc import (
    density_altitude_ft,
    lookup_airport,
    parse_t_group,
    pressure_altitude_ft,
    runway_heading,
    temperature_spread,
    wind_components,
)

# --- airport lookup ---------------------------------------------------------------------------------------------


def test_lookup_known_airport_has_coordinates_elevation_and_zone():
    kden = lookup_airport(" kden ")
    assert kden is not None
    assert kden.icao == "KDEN"
    assert kden.tz == "America/Denver"
    assert kden.elevation_m == 1656
    assert kden.elevation_ft == pytest.approx(5433.1, abs=0.1)  # 1656 m / 0.3048 = 5433.07 ft
    assert 39 < kden.lat < 40 and -105 < kden.lon < -104


@pytest.mark.parametrize("code", ["XXXX", "", "  ", "DEN", "JFK"])
def test_lookup_unknown_or_non_icao_gives_none(code):
    assert lookup_airport(code) is None


# --- pressure and density altitude ------------------------------------------------------------------------------


def test_pressure_altitude_at_standard_setting_is_field_elevation():
    assert pressure_altitude_ft(5000, 1013.25, "hPa") == pytest.approx(5000, abs=1e-6)
    assert pressure_altitude_ft(0, 29.92126) == pytest.approx(0, abs=0.1)  # 29.92126 inHg * 33.8639 = 1013.25 hPa


def test_pressure_altitude_low_and_high_settings():
    # 29.42 inHg = 996.28 hPa; ratio 0.98329, ln = -0.016851, * 0.190263 = -0.003206, exp = 0.996799;
    # 145442.16 * (1 - 0.996799) = +466 ft.
    assert pressure_altitude_ft(0, 29.42) == pytest.approx(466, abs=2)
    # 30.92 inHg = 1047.1 hPa gives -911 ft: a high setting lowers pressure altitude (ISA is ~910 ft per inHg).
    assert pressure_altitude_ft(0, 30.92) == pytest.approx(-911, abs=2)


def test_density_altitude_isa_day_equals_pressure_altitude():
    assert density_altitude_ft(0, 1013.25, 15, unit="hPa") == pytest.approx(0, abs=0.01)
    # ISA at 5000 ft PA: 15 - 1.9812 * 5 = 5.094 C.
    assert density_altitude_ft(5000, 1013.25, 5.094, unit="hPa") == pytest.approx(5000, abs=1)


def test_density_altitude_hot_day_dry():
    # Sea level, 30 C: 288.15 / 303.15 = 0.95052; 0.95052 ** 0.234969 = 0.98814; (1 - 0.98814) * 145442 = 1725 ft.
    # The 120 ft per C rule of thumb gives 120 * 15 = 1800 ft.
    assert density_altitude_ft(0, 1013.25, 30, unit="hPa") == pytest.approx(1725, abs=3)


def test_humidity_raises_density_altitude():
    dry = density_altitude_ft(0, 1013.25, 30, unit="hPa")
    humid = density_altitude_ft(0, 1013.25, 30, 30, unit="hPa")
    assert dry is not None and humid is not None
    # e at 30 C = 42.4 hPa; Tv = 303.15 / (1 - 0.0418 * 0.378) = 308.0 K, about 4.9 K warmer: roughly +540 ft.
    assert humid - dry == pytest.approx(537, abs=15)


def test_density_altitude_denver_summer_afternoon():
    # KDEN 5433 ft, 30.02 inHg (1016.6 hPa), 32 C. PA = 5433 - 91 = 5342 ft (ratio 1.003308, exponent 0.190263).
    # Station pressure 1013.25 * (1 - 5342/145442) ** 5.255876 = 832.3 hPa; T = 305.15 K;
    # rho = 83230 / (287.058 * 305.15) = 0.9501 kg/m3, ratio 0.7756; 0.7756 ** 0.234969 = 0.94205;
    # DA = 145442 * (1 - 0.94205) = 8428 ft. (The 120 ft per C rule would say about 8650.)
    assert density_altitude_ft(5433.07, 30.02, 32) == pytest.approx(8427, abs=10)


def test_altitudes_none_on_missing_input():
    assert pressure_altitude_ft(None, 29.92) is None
    assert pressure_altitude_ft(100, None) is None
    assert pressure_altitude_ft(100, 0) is None
    assert density_altitude_ft(100, 29.92, None) is None
    assert density_altitude_ft(None, 29.92, 15) is None
    assert density_altitude_ft(100, 29.92, math.nan) is None


@given(
    elevation=st.floats(-1000, 14000),
    inhg=st.floats(28.0, 31.0),
    warmer=st.floats(0.01, 40),
    dew_gap=st.floats(0, 30) | st.none(),
)
def test_density_altitude_at_least_pressure_altitude_when_warmer_than_isa(elevation, inhg, warmer, dew_gap):
    pa = pressure_altitude_ft(elevation, inhg)
    assert pa is not None
    isa_c = 15 - 1.9812 * pa / 1000  # lapse 6.5 C/km = 1.9812 C per 1000 ft
    temp = isa_c + warmer
    dew = None if dew_gap is None else temp - dew_gap
    da = density_altitude_ft(elevation, inhg, temp, dew)
    assert da is not None and da >= pa - 1e-6


@given(elevation=st.floats(-1000, 14000), inhg=st.floats(28.0, 31.0), temp=st.floats(-40, 45))
def test_density_altitude_rises_with_temperature(elevation, inhg, temp):
    cold = density_altitude_ft(elevation, inhg, temp)
    warm = density_altitude_ft(elevation, inhg, temp + 1)
    assert cold is not None and warm is not None and warm > cold


@given(inhg=st.floats(28.0, 31.0))
def test_hpa_and_inhg_agree(inhg):
    a = pressure_altitude_ft(100, inhg, "inHg")
    b = pressure_altitude_ft(100, inhg * 33.8639, "hPa")
    assert a == pytest.approx(b)


# --- temperature / dew point spread -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("temp", "dew", "spread", "alert"),
    [
        (15, 10, 5.0, False),
        (12.3, 10.8, 1.5, True),  # 12.3 - 10.8 = 1.5
        (10, 7, 3.0, True),  # exactly 3 alerts
        (10.4, 7.3, 3.1, False),  # 10.4 - 7.3 = 3.1000000000000014 in floats; rounding to tenths keeps it clean
        (-2, -2, 0.0, True),
        (5, 6, -1.0, True),  # dew point above air: bad data, still an alert
    ],
)
def test_spread_and_alert(temp, dew, spread, alert):
    result = temperature_spread(temp, dew)
    assert result is not None
    assert result.spread_c == pytest.approx(spread)
    assert result.alert is alert


@pytest.mark.parametrize(("temp", "dew"), [(None, 5), (5, None), (None, None), (math.nan, 5), (5, math.inf)])
def test_spread_none_when_a_value_is_missing(temp, dew):
    assert temperature_spread(temp, dew) is None


@pytest.mark.parametrize(
    ("group", "expected"),
    [
        ("T01230108", (12.3, 10.8)),
        ("T10251031", (-2.5, -3.1)),  # sign digit 1 means negative
        ("T00001000", (0.0, -0.0)),
        ("T0123", (12.3, None)),  # no dew point reported
        (" t01230108 ", (12.3, 10.8)),
    ],
)
def test_parse_t_group(group, expected):
    assert parse_t_group(group) == expected


@pytest.mark.parametrize("group", ["", "T", "T2123", "T012301", "A3001", "T01230108X", "T0123010"])
def test_parse_t_group_rejects_other_text(group):
    assert parse_t_group(group) is None


def test_t_group_feeds_spread():
    temp, dew = parse_t_group("T01230108") or (None, None)
    result = temperature_spread(temp, dew)
    assert result is not None and result.spread_c == 1.5 and result.alert


# --- runway wind ------------------------------------------------------------------------------------------------


def test_direct_headwind_and_direct_crosswind():
    straight = wind_components(270, 20, 270)
    assert straight is not None
    assert straight.headwind == pytest.approx(20) and straight.crosswind == pytest.approx(0, abs=1e-9)
    side = wind_components(360, 20, 270)  # from 90 degrees clockwise of the runway: from the right
    assert side is not None
    assert side.headwind == pytest.approx(0, abs=1e-9) and side.crosswind == pytest.approx(20)


def test_tailwind_and_left_crosswind_signs():
    tail = wind_components(90, 10, 270)
    assert tail is not None and tail.headwind == pytest.approx(-10)
    left = wind_components(180, 10, 270)
    assert left is not None and left.crosswind == pytest.approx(-10)


def test_thirty_degrees_off_with_gust():
    # 300 at 20 G30 on runway 27: angle 30; 20*cos30 = 17.32, 20*sin30 = 10; gust 30*cos30 = 25.98, 30*sin30 = 15.
    wc = wind_components(300, 20, 270, gust=30)
    assert wc is not None
    assert wc.headwind == pytest.approx(17.3205, abs=1e-3) and wc.crosswind == pytest.approx(10)
    assert wc.gust_headwind == pytest.approx(25.9808, abs=1e-3) and wc.gust_crosswind == pytest.approx(15)


def test_runway_across_north():
    # Wind 350 on runway 04 (40): angle -50; 10*cos(-50) = 6.43 headwind, 10*sin(-50) = -7.66 (from the left).
    wc = wind_components(350, 10, 40)
    assert wc is not None
    assert wc.headwind == pytest.approx(6.4279, abs=1e-3) and wc.crosswind == pytest.approx(-7.6604, abs=1e-3)


def test_calm_is_zero_whatever_the_direction():
    assert wind_components(None, 0, 270) == wind_components(0, 0, 270)
    calm = wind_components(None, 0, 270, variable=True)
    assert calm is not None and calm.headwind == 0 and calm.crosswind == 0 and calm.gust_headwind is None


@pytest.mark.parametrize(("direction", "speed", "variable"), [(None, 5, False), (200, 5, True), (None, None, False)])
def test_unknown_direction_or_speed_gives_none(direction, speed, variable):
    assert wind_components(direction, speed, 270, variable=variable) is None


def test_gust_below_speed_is_ignored():
    wc = wind_components(270, 20, 270, gust=10)
    assert wc is not None and wc.gust_headwind is None


@pytest.mark.parametrize(
    ("designator", "heading"),
    [
        ("27L", 270),
        ("09", 90),
        ("36", 360),
        ("01R", 10),
        (" 18c ", 180),
        ("00", None),
        ("37", None),
        ("27X", None),
        ("", None),
    ],
)
def test_runway_heading(designator, heading):
    assert runway_heading(designator) == heading


angles = st.floats(0, 360, exclude_max=True)
speeds = st.floats(0, 200)


@given(direction=angles, speed=speeds, runway=angles)
def test_components_recombine_to_the_speed(direction, speed, runway):
    wc = wind_components(direction, speed, runway)
    assert wc is not None
    assert wc.crosswind**2 + wc.headwind**2 == pytest.approx(speed**2, rel=1e-9, abs=1e-9)


@given(direction=angles, speed=st.floats(0.1, 200), runway=angles, gust_extra=st.floats(0, 50))
def test_gust_components_recombine_to_the_gust(direction, speed, runway, gust_extra):
    wc = wind_components(direction, speed, runway, gust=speed + gust_extra)
    assert wc is not None
    assert wc.gust_crosswind is not None and wc.gust_headwind is not None
    assert wc.gust_crosswind**2 + wc.gust_headwind**2 == pytest.approx((speed + gust_extra) ** 2, rel=1e-9)


@given(offset=st.floats(0, 180), speed=speeds, runway=angles)
def test_mirrored_wind_flips_crosswind_and_keeps_headwind(offset, speed, runway):
    right = wind_components((runway + offset) % 360, speed, runway)
    left = wind_components((runway - offset) % 360, speed, runway)
    assert right is not None and left is not None
    assert right.crosswind == pytest.approx(-left.crosswind, abs=1e-9)
    assert right.headwind == pytest.approx(left.headwind, abs=1e-9)


@given(direction=angles, speed=speeds, runway=angles)
def test_reversing_the_runway_negates_both_components(direction, speed, runway):
    forward = wind_components(direction, speed, runway)
    reverse = wind_components(direction, speed, (runway + 180) % 360)
    assert forward is not None and reverse is not None
    assert forward.headwind == pytest.approx(-reverse.headwind, abs=1e-9)
    assert forward.crosswind == pytest.approx(-reverse.crosswind, abs=1e-9)
