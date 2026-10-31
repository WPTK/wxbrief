"""Unit conversions."""

from __future__ import annotations

import pytest

from wxbrief.decode.units import (
    Distance,
    DistanceUnit,
    Pressure,
    PressureUnit,
    Speed,
    SpeedUnit,
    Temperature,
    TemperatureUnit,
)


def test_speed_conversions() -> None:
    assert Speed(10, SpeedUnit.KT).knots == 10
    assert Speed(10, SpeedUnit.MPS).knots == pytest.approx(19.438, abs=1e-3)
    assert Speed(36, SpeedUnit.KMH).knots == pytest.approx(19.438, abs=1e-3)
    assert Speed(10, SpeedUnit.KT).kmh == pytest.approx(18.52)
    assert Speed(10, SpeedUnit.KT).mps == pytest.approx(5.144, abs=1e-3)
    assert Speed(10, SpeedUnit.KT).mph == pytest.approx(11.508, abs=1e-3)


def test_distance_conversions() -> None:
    assert Distance(1, DistanceUnit.SM).meters == pytest.approx(1609.34)
    assert Distance(9999, DistanceUnit.M).statute_miles == pytest.approx(6.2133, abs=1e-3)
    assert Distance(10, DistanceUnit.KM).meters == 10000
    assert Distance(1000, DistanceUnit.FT).meters == pytest.approx(304.8)
    assert Distance(304.8, DistanceUnit.M).feet == pytest.approx(1000)
    assert Distance(2500, DistanceUnit.M).kilometers == 2.5


def test_same_unit_conversions_are_exact() -> None:
    """Flight-category thresholds compare against these, so a round trip must not drift."""
    assert Distance(7000, DistanceUnit.FT).feet == 7000
    assert Distance(3, DistanceUnit.SM).statute_miles == 3
    assert Distance(10, DistanceUnit.KM).kilometers == 10
    assert Distance(1200, DistanceUnit.M).meters == 1200


def test_pressure_conversions() -> None:
    assert Pressure(1013.25, PressureUnit.HPA).inhg == pytest.approx(29.92, abs=1e-2)
    assert Pressure(30.01, PressureUnit.INHG).hpa == pytest.approx(1016.2, abs=0.1)
    assert Pressure(1013, PressureUnit.HPA).hpa == 1013
    assert Pressure(29.92, PressureUnit.INHG).inhg == 29.92


def test_temperature_conversions() -> None:
    assert Temperature(0).fahrenheit == 32
    assert Temperature(100).fahrenheit == 212
    assert Temperature(-40).fahrenheit == -40
    assert Temperature(32, TemperatureUnit.F).celsius == 0
    assert Temperature(15, TemperatureUnit.C).celsius == 15
    assert Temperature(59, TemperatureUnit.F).fahrenheit == 59
