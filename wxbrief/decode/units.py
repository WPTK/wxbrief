"""Measured quantities that remember the unit they were reported in (stdlib only).

Each quantity is a frozen dataclass holding the reported ``value`` and ``unit``; conversions are read-only
properties, so the model never loses what the report actually said.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# Conversion factors. Statute miles use 1609.34 m so that a 9999 m report lands on 6.2 SM, matching the reference
# decoder and the AWC flight category.
METERS_PER_STATUTE_MILE = 1609.34
METERS_PER_FOOT = 0.3048
KNOTS_PER_MPS = 3600.0 / 1852.0
KMH_PER_KNOT = 1.852
MPH_PER_KNOT = 1852.0 / 1609.344
HPA_PER_INHG = 33.8639


class UnitsMode(Enum):
    """How a renderer presents measurements.

    ``US`` and ``METRIC`` force that system and keep the reported value in parentheses when it differs;
    ``MIXED`` shows the reported value first and the other system in parentheses.
    """

    US = "us"
    METRIC = "metric"
    MIXED = "mixed"


class SpeedUnit(Enum):
    KT = "KT"
    MPS = "MPS"
    KMH = "KMH"


class DistanceUnit(Enum):
    M = "M"
    SM = "SM"
    FT = "FT"
    KM = "KM"


class PressureUnit(Enum):
    HPA = "HPA"
    INHG = "INHG"


class TemperatureUnit(Enum):
    C = "C"
    F = "F"


@dataclass(frozen=True)
class Speed:
    """Wind speed as reported (knots, metres per second or kilometres per hour)."""

    value: float
    unit: SpeedUnit = SpeedUnit.KT

    @property
    def knots(self) -> float:
        match self.unit:
            case SpeedUnit.KT:
                return float(self.value)
            case SpeedUnit.MPS:
                return self.value * KNOTS_PER_MPS
            case SpeedUnit.KMH:
                return self.value / KMH_PER_KNOT

    @property
    def mps(self) -> float:
        return self.knots / KNOTS_PER_MPS

    @property
    def kmh(self) -> float:
        return self.knots * KMH_PER_KNOT

    @property
    def mph(self) -> float:
        return self.knots * MPH_PER_KNOT


@dataclass(frozen=True)
class Distance:
    """A length as reported (visibility, RVR or cloud height)."""

    value: float
    unit: DistanceUnit

    @property
    def meters(self) -> float:
        match self.unit:
            case DistanceUnit.M:
                return float(self.value)
            case DistanceUnit.SM:
                return self.value * METERS_PER_STATUTE_MILE
            case DistanceUnit.FT:
                return self.value * METERS_PER_FOOT
            case DistanceUnit.KM:
                return self.value * 1000.0

    @property
    def kilometers(self) -> float:
        return self.meters / 1000.0

    @property
    def statute_miles(self) -> float:
        return self.meters / METERS_PER_STATUTE_MILE

    @property
    def feet(self) -> float:
        return self.meters / METERS_PER_FOOT


@dataclass(frozen=True)
class Pressure:
    """Altimeter setting or QNH as reported."""

    value: float
    unit: PressureUnit

    @property
    def hpa(self) -> float:
        if self.unit is PressureUnit.HPA:
            return float(self.value)
        return self.value * HPA_PER_INHG

    @property
    def inhg(self) -> float:
        if self.unit is PressureUnit.INHG:
            return float(self.value)
        return self.value / HPA_PER_INHG


@dataclass(frozen=True)
class Temperature:
    """Air temperature or dew point as reported."""

    value: float
    unit: TemperatureUnit = TemperatureUnit.C

    @property
    def celsius(self) -> float:
        if self.unit is TemperatureUnit.C:
            return float(self.value)
        return (self.value - 32.0) * 5.0 / 9.0

    @property
    def fahrenheit(self) -> float:
        if self.unit is TemperatureUnit.F:
            return float(self.value)
        return self.value * 9.0 / 5.0 + 32.0
