"""Check that the AWC station cache that ``build_stations.py`` reads is still reachable and parsable.

Used by ``stations-canary.yml``. Standard library only. Exits 1, with the reason on stdout, if the download fails,
the file is not gzip JSON, the rows lost the fields the build reads, or the number of usable stations differs from the
bundled database by more than 2 % (the signal to rerun ``build_stations.py``). Writes nothing.
"""

from __future__ import annotations

import gzip
import json
import sys
import urllib.request
from pathlib import Path

CACHE_URL = "https://aviationweather.gov/data/cache/stations.cache.json.gz"
BUNDLED = Path(__file__).resolve().parent.parent / "wxbrief" / "data" / "stations.json.gz"
USER_AGENT = "wxbrief-stations-canary (+https://github.com/WPTK/wxbrief)"
MAX_DRIFT = 0.02


def usable(rows: list[object]) -> int:
    """Rows the build would keep: an ICAO id and in-range coordinates."""
    count = 0
    for item in rows:
        if not isinstance(item, dict):
            continue
        icao, lat, lon = item.get("icaoId"), item.get("lat"), item.get("lon")
        if (
            isinstance(icao, str)
            and icao.strip()
            and isinstance(lat, int | float)
            and isinstance(lon, int | float)
            and -90 <= lat <= 90
            and -180 <= lon <= 180
        ):
            count += 1
    return count


def main() -> int:
    request = urllib.request.Request(CACHE_URL, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            source = json.loads(gzip.decompress(response.read()))
    except Exception as error:
        print(f"cannot read {CACHE_URL}: {error!r}")
        return 1
    if not isinstance(source, list):
        print(f"expected a JSON list, got {type(source).__name__}")
        return 1
    fresh = usable(source)
    bundled = len(json.loads(gzip.decompress(BUNDLED.read_bytes())))
    drift = abs(fresh - bundled) / bundled
    print(f"source: {len(source)} rows, {fresh} usable; bundled: {bundled}; drift {drift:.1%}")
    if fresh == 0:
        print("no usable rows: the cache format changed")
        return 1
    if drift > MAX_DRIFT:
        print(f"drift is over {MAX_DRIFT:.0%}: rerun scripts/build_stations.py and commit the result")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
