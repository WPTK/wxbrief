"""Pressure altitude and density altitude.

Both use the ICAO standard atmosphere (sea level 1013.25 hPa and 15 C, lapse 6.5 C per km), the same model an
altimeter is calibrated to. Source: ICAO Doc 7488; FAA Pilot's Handbook of Aeronautical Knowledge, ch. 11
(Aircraft Performance). The Magnus vapour pressure fit is the one ``decode.derived.relative_humidity`` uses.
"""

from __future__ import annotations

import math
from typing import Literal

HPA_PER_INHG = 33.8639
STD_PRESSURE_HPA = 1013.25
STD_TEMP_K = 288.15
LAPSE_K_PER_M = 0.0065
FEET_PER_METRE = 1 / 0.3048
# Barometric exponent g / (R * lapse) = 5.255876 (reciprocal 0.190263) and the altitude at which ISA pressure would
# reach zero, T0 / lapse = 44330.77 m = 145442.16 ft. One set of constants for both directions keeps DA == PA at ISA.
_BARO_EXP = 5.255876
_PRESSURE_EXP = 1 / _BARO_EXP
_ISA_TOP_FT = STD_TEMP_K / LAPSE_K_PER_M * FEET_PER_METRE
_RD = 287.058  # specific gas constant of dry air, J/(kg K)
_RHO0 = STD_PRESSURE_HPA * 100 / (_RD * STD_TEMP_K)  # ISA sea level density, 1.2250 kg/m3
_DENSITY_EXP = 1 / 4.255876  # ISA density ratio = (1 - h / top) ** 4.255876


def _hpa(altimeter: float, unit: Literal["inHg", "hPa"]) -> float:
    return altimeter * HPA_PER_INHG if unit == "inHg" else altimeter


def pressure_altitude_ft(
    elevation_ft: float | None, altimeter: float | None, unit: Literal["inHg", "hPa"] = "inHg"
) -> float | None:
    """Altitude on the standard-pressure datum: field elevation plus the height of the altimeter-setting offset.

    ``PA = elevation + 145442.16 * (1 - (setting_hPa / 1013.25) ** 0.190263)``. The textbook
    ``elevation + (29.92 - setting_inHg) * 1000`` is a rounder rule; the true rate is about 910 ft per inHg
    at sea level.
    """
    if elevation_ft is None or altimeter is None or altimeter <= 0:
        return None
    ratio = _hpa(altimeter, unit) / STD_PRESSURE_HPA
    return float(elevation_ft + _ISA_TOP_FT * (1 - ratio**_PRESSURE_EXP))


def _vapour_pressure_hpa(dewpoint_c: float) -> float:
    """Partial pressure of water vapour at the dew point (Magnus-Tetens, a=17.625, b=243.04)."""
    return 6.1094 * math.exp(17.625 * dewpoint_c / (243.04 + dewpoint_c))


def density_altitude_ft(
    elevation_ft: float | None,
    altimeter: float | None,
    temperature_c: float | None,
    dewpoint_c: float | None = None,
    unit: Literal["inHg", "hPa"] = "inHg",
) -> float | None:
    """The altitude in the standard atmosphere that has the air density found at the field.

    Station pressure comes from the pressure altitude, air density from the ideal gas law ``rho = p / (Rd * Tv)``
    with the virtual temperature ``Tv = T / (1 - (e / p) * (1 - 0.622))`` when a dew point is given (humid air is less
    dense), and ``DA = 145442.16 * (1 - (rho / 1.225) ** 0.234969)`` ft. Without a dew point the air is taken as dry.
    """
    pa = pressure_altitude_ft(elevation_ft, altimeter, unit)
    if pa is None or temperature_c is None or not math.isfinite(temperature_c):
        return None
    if pa >= _ISA_TOP_FT * 0.99:
        return None  # the formula leaves the troposphere's validity long before this
    pressure = STD_PRESSURE_HPA * (1 - pa / _ISA_TOP_FT) ** _BARO_EXP
    kelvin = temperature_c + 273.15
    if dewpoint_c is not None and math.isfinite(dewpoint_c):
        kelvin /= 1 - _vapour_pressure_hpa(min(dewpoint_c, temperature_c)) / pressure * (1 - 0.622)
    density = pressure * 100 / (_RD * kelvin)
    return float(_ISA_TOP_FT * (1 - (density / _RHO0) ** _DENSITY_EXP))
