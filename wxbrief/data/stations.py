"""The bundled station database and its search."""

from __future__ import annotations

import gzip
import json
import unicodedata
from dataclasses import dataclass
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any

BUNDLED = "stations.json.gz"


@dataclass(frozen=True, slots=True)
class Station:
    icao: str
    iata: str | None
    faa: str | None
    name: str
    lat: float
    lon: float
    elevation_m: float | None
    state: str | None
    country: str | None
    tz: str | None
    types: tuple[str, ...]


def _fold(text: str) -> str:
    """Lowercase, accents and punctuation removed, so "Heathrow" and "São Paulo" match "heathrow" and "sao paulo"."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    letters = "".join(ch if ch.isalnum() else " " for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(letters.split())


def _station(row: dict[str, Any]) -> Station:
    return Station(
        icao=row["icao"],
        iata=row.get("iata"),
        faa=row.get("faa"),
        name=row.get("name") or row["icao"],
        lat=float(row["lat"]),
        lon=float(row["lon"]),
        elevation_m=row.get("elev"),
        state=row.get("state"),
        country=row.get("country"),
        tz=row.get("tz"),
        types=tuple(row.get("types") or ()),
    )


class StationDB:
    """Look up and search stations. Loaded once; about 8,000 rows."""

    def __init__(self, stations: list[Station]) -> None:
        self._stations = stations
        self._by_icao = {s.icao: s for s in stations}
        self._by_iata = self._index(stations, "iata")
        self._by_faa = self._index(stations, "faa")
        self._haystack = [
            (_fold(" ".join(p for p in (s.name, s.state, s.country) if p)), s) for s in stations
        ]

    @staticmethod
    def _index(stations: list[Station], field: str) -> dict[str, list[Station]]:
        found: dict[str, list[Station]] = {}
        for station in stations:
            code = getattr(station, field)
            if code:
                found.setdefault(code, []).append(station)
        return found

    @classmethod
    def load(cls, path: Path | None = None) -> StationDB:
        """The bundled database, or the file at ``path`` (the build script and the tests use that)."""
        source = resources.files("wxbrief.data").joinpath(BUNDLED) if path is None else path
        data = source.read_bytes()
        rows = json.loads(gzip.decompress(data))
        return cls([_station(row) for row in rows])

    def __len__(self) -> int:
        return len(self._stations)

    def get(self, code: str) -> Station | None:
        """ICAO, else a unique IATA code, else a unique FAA code (``DEN`` finds KDEN, ``MAN`` finds EGCC).

        IATA wins over FAA because an FAA id such as ``MAN`` (KMAN) collides with foreign IATA codes. A code that two
        stations share within one scheme (``GWD``, ``SRG`` and six others) is ambiguous and gives ``None``.
        """
        key = code.strip().upper()
        if key in self._by_icao:
            return self._by_icao[key]
        for index in (self._by_iata, self._by_faa):
            owners = index.get(key)
            if owners:
                return owners[0] if len(owners) == 1 else None
        return None

    def search(self, query: str, limit: int = 10) -> list[Station]:
        """Best matches first: exact code, code prefix, name word prefix, then name substring."""
        code = query.strip().upper()
        folded = _fold(query)
        if not folded:
            return []
        scored: list[tuple[int, str, Station]] = []
        for text, station in self._haystack:
            score = self._score(code, folded, text, station)
            if score:
                scored.append((score, station.icao, station))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [station for _, _, station in scored[:limit]]

    @staticmethod
    def _score(code: str, folded: str, text: str, station: Station) -> int:
        codes = (station.icao, station.iata, station.faa)
        score = 0
        if code in codes:
            score = 100
        elif len(code) >= 2 and any(c and c.startswith(code) for c in codes):
            score = 70
        words = text.split()
        if folded == text:
            score = max(score, 90)
        elif text.startswith(folded):
            score = max(score, 65)
        elif any(word.startswith(folded) for word in words):
            score = max(score, 60)
        elif folded in text:
            score = max(score, 40)
        if score and "METAR" in station.types:
            score += 1
        if score and "TAF" in station.types:
            score += 2
        return score


def resolve_id(code: str) -> str:
    """A 3-character IATA or FAA code as the ICAO id of its station; anything else upper-cased as it is."""
    key = code.strip().upper()
    station = bundled().get(key) if len(key) == 3 else None
    return station.icao if station else key


@cache
def bundled() -> StationDB:
    """The shared instance of the bundled database."""
    return StationDB.load()
