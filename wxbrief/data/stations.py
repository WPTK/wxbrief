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
        self._haystack = [
            (_fold(" ".join(p for p in (s.name, s.state, s.country) if p)), s) for s in stations
        ]

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
        """Exact ICAO lookup, falling back to a unique IATA or FAA match (``DEN`` finds KDEN)."""
        key = code.strip().upper()
        if key in self._by_icao:
            return self._by_icao[key]
        matches = [s for s in self._stations if key in (s.iata, s.faa)]
        return matches[0] if len(matches) == 1 else None

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


@cache
def bundled() -> StationDB:
    """The shared instance of the bundled database."""
    return StationDB.load()
