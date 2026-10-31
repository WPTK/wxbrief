"""Build ``wxbrief/data/stations.json.gz`` from the AWC world station cache.

Usage::

    python scripts/build_stations.py                 # download the cache (one polite request) and rebuild
    python scripts/build_stations.py --cache FILE    # use a saved stations.cache.json.gz

Needs ``timezonefinder`` (a dev-only dependency; the app itself resolves zones with ``zoneinfo``). Keeps every
station that has an ICAO id and valid coordinates, at the full precision of the cache (nothing is rounded or dropped
for size). The output is deterministic: sorted by ICAO, gzip header without a timestamp.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

import httpx

CACHE_URL = "https://aviationweather.gov/data/cache/stations.cache.json.gz"
OUTPUT = Path(__file__).resolve().parent.parent / "wxbrief" / "data" / "stations.json.gz"
USER_AGENT = "wxbrief-build-stations (+https://github.com/WPTK/wxbrief)"


def _text(value: object) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def build_rows(source: list[dict[str, object]]) -> list[dict[str, object]]:
    from timezonefinder import TimezoneFinder

    finder = TimezoneFinder()
    rows: dict[str, dict[str, object]] = {}
    for item in source:
        icao = _text(item.get("icaoId"))
        types = [t for t in item.get("siteType") or [] if t in ("METAR", "TAF")]  # type: ignore[attr-defined]
        lat, lon = item.get("lat"), item.get("lon")
        if not icao or not isinstance(lat, int | float) or not isinstance(lon, int | float):
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue  # the cache holds placeholder coordinates such as -99.99
        elevation = item.get("elev")
        row: dict[str, object] = {
            "icao": icao.upper(),
            "iata": _text(item.get("iataId")),
            "faa": _text(item.get("faaId")),
            "name": _text(item.get("site")) or icao.upper(),
            "lat": float(lat),
            "lon": float(lon),
            "elev": elevation if isinstance(elevation, int | float) else None,
            "state": _text(item.get("state")),
            "country": _text(item.get("country")),
            "tz": finder.timezone_at(lat=float(lat), lng=float(lon)),
            "types": sorted(types),
        }
        rows[str(row["icao"])] = {k: v for k, v in row.items() if v is not None}
    return [rows[key] for key in sorted(rows)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--cache", type=Path, help="a saved stations.cache.json.gz instead of downloading")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    if args.cache:
        raw = args.cache.read_bytes()
    else:
        response = httpx.get(CACHE_URL, headers={"User-Agent": USER_AGENT}, timeout=60.0)
        response.raise_for_status()
        raw = response.content
    source = json.loads(gzip.decompress(raw))
    rows = build_rows(source)
    payload = json.dumps(rows, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    args.output.write_bytes(gzip.compress(payload, compresslevel=9, mtime=0))
    print(f"{len(rows)} stations -> {args.output} ({args.output.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
