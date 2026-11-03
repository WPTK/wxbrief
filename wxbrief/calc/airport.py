"""Offline airport facts by ICAO id, read from the bundled station database (no second dataset)."""

from __future__ import annotations

from dataclasses import dataclass

from wxbrief.data.stations import bundled

FEET_PER_METRE = 1 / 0.3048


@dataclass(frozen=True, slots=True)
class Airport:
    icao: str
    name: str
    lat: float
    lon: float
    elevation_m: float | None
    tz: str | None  # IANA zone name

    @property
    def elevation_ft(self) -> float | None:
        return None if self.elevation_m is None else self.elevation_m * FEET_PER_METRE


def lookup_airport(icao: str) -> Airport | None:
    """The station with exactly this ICAO id (case and surrounding blanks ignored), else ``None``.

    IATA and FAA codes are not accepted here: ``DEN`` is not an ICAO id. Use ``StationDB.get`` for that.
    """
    key = icao.strip().upper()
    station = bundled().get(key) if key else None
    if station is None or station.icao != key:
        return None
    return Airport(station.icao, station.name, station.lat, station.lon, station.elevation_m, station.tz)
