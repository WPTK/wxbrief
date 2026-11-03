"""Pure calculations a pilot works out from a METAR: airport facts, altitudes, dew point spread, runway wind.

No UI, no network and no state; every function takes plain numbers and returns ``None`` when an input is missing.
"""

from __future__ import annotations

from wxbrief.calc.airport import Airport, lookup_airport
from wxbrief.calc.altitude import density_altitude_ft, pressure_altitude_ft
from wxbrief.calc.spread import Spread, parse_t_group, temperature_spread
from wxbrief.calc.wind import WindComponents, runway_heading, wind_components

__all__ = [
    "Airport",
    "Spread",
    "WindComponents",
    "density_altitude_ft",
    "lookup_airport",
    "parse_t_group",
    "pressure_altitude_ft",
    "runway_heading",
    "temperature_spread",
    "wind_components",
]
