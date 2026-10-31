"""Solar elevation from latitude, longitude and time: offline, standard library only (NOAA general solar position)."""

from __future__ import annotations

import math
from datetime import UTC, datetime

# The sun's centre at -0.833 degrees is the horizon as sunrise and sunset tables define it (refraction + disc radius).
HORIZON_DEG = -0.833


def solar_elevation(lat: float, lon: float, moment: datetime) -> float:
    """Elevation of the sun's centre above the horizon in degrees; a naive ``moment`` is taken as UTC."""
    utc = moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)
    day_of_year = utc.timetuple().tm_yday
    hours = utc.hour + utc.minute / 60 + utc.second / 3600
    year_len = 366 if utc.year % 4 == 0 and (utc.year % 100 != 0 or utc.year % 400 == 0) else 365
    gamma = 2 * math.pi / year_len * (day_of_year - 1 + (hours - 12) / 24)
    eqtime = 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma)
        - 0.040849 * math.sin(2 * gamma)
    )
    decl = (
        0.006918
        - 0.399912 * math.cos(gamma)
        + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2 * gamma)
        + 0.000907 * math.sin(2 * gamma)
        - 0.002697 * math.cos(3 * gamma)
        + 0.00148 * math.sin(3 * gamma)
    )
    true_solar_minutes = hours * 60 + eqtime + 4 * lon
    hour_angle = math.radians(true_solar_minutes / 4 - 180)
    phi = math.radians(lat)
    sin_elevation = math.sin(phi) * math.sin(decl) + math.cos(phi) * math.cos(decl) * math.cos(hour_angle)
    return math.degrees(math.asin(max(-1.0, min(1.0, sin_elevation))))


def is_daylight(lat: float, lon: float, moment: datetime | None) -> bool | None:
    """True while the sun is above the horizon; None when the observation time is unknown."""
    if moment is None:
        return None
    return solar_elevation(lat, lon, moment) > HORIZON_DEG
