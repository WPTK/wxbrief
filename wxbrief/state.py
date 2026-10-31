"""Application state: the station list, the latest report for each, and the cache that backs them.

Plain data and functions with no Textual imports, so the screens only read it and the tests build it directly.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from wxbrief.config import WATCHLIST_CAP
from wxbrief.data.cache import DiskCache
from wxbrief.data.demo import DemoStation
from wxbrief.data.models import AwcMetar, AwcTaf, latest_by_station, parse_metars, parse_tafs
from wxbrief.data.poll import Freshness, Product, freshness
from wxbrief.decode.metar import parse_metar
from wxbrief.decode.model import Metar, Taf
from wxbrief.decode.taf import parse_taf

CACHE_KEYS = {Product.METAR: "metars", Product.TAF: "tafs"}


@dataclass(slots=True)
class StationReports:
    """What is known about one station: the newest AWC rows and their decodes."""

    icao: str
    awc_metar: AwcMetar | None = None
    awc_taf: AwcTaf | None = None
    metar: Metar | None = None
    taf: Taf | None = None
    updated: datetime | None = None  # when the data last arrived (fetch time, or the cache file's save time)
    from_cache: bool = False

    def freshness(self, now: datetime) -> Freshness:
        observed = self.awc_metar.observed if self.awc_metar else None
        return freshness(observed, now)


def _aware(moment: datetime) -> datetime | None:
    """A cache time without a zone is treated as damaged (``None``), never guessed."""
    return moment if moment.tzinfo is not None else None


class AppState:
    """The watchlist (saved), the ids added for this run only, and the reports for every id."""

    def __init__(
        self,
        watchlist: Iterable[str] = (),
        session: Iterable[str] = (),
        cache: DiskCache | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.watchlist: list[str] = list(dict.fromkeys(watchlist))
        self.session: list[str] = [i for i in dict.fromkeys(session) if i not in self.watchlist]
        self.cache = cache
        self.now = now
        self.stations: dict[str, StationReports] = {}
        self.errors: dict[Product, str] = {}
        self.last_success: datetime | None = None
        self._metar_rows: dict[str, AwcMetar] = {}
        self._taf_rows: dict[str, AwcTaf] = {}

    # --- the list -----------------------------------------------------------------------------------------------

    @property
    def ids(self) -> list[str]:
        return [*self.watchlist, *(i for i in self.session if i not in self.watchlist)]

    def add(self, icao: str, *, persist: bool) -> bool:
        """Add a station; ``True`` when the list changed. A persisted id goes to the watchlist (capped at 60)."""
        code = icao.strip().upper()
        if not code:
            return False
        if persist:
            if code in self.watchlist or len(self.watchlist) >= WATCHLIST_CAP:
                return False
            self.watchlist.append(code)
            if code in self.session:
                self.session.remove(code)
            return True
        if code in self.ids:
            return False
        self.session.append(code)
        return True

    def remove(self, icao: str) -> bool:
        """Remove a station from the list; the cached report for it is kept."""
        code = icao.strip().upper()
        if code in self.watchlist:
            self.watchlist.remove(code)
            return True
        if code in self.session:
            self.session.remove(code)
            return True
        return False

    def is_saved(self, icao: str) -> bool:
        return icao in self.watchlist

    def entry(self, icao: str) -> StationReports:
        return self.stations.setdefault(icao, StationReports(icao))

    # --- data in -------------------------------------------------------------------------------------------------

    def _set_metar(self, row: AwcMetar, updated: datetime, *, from_cache: bool) -> None:
        entry = self.entry(row.icao)
        if entry.awc_metar is None or entry.awc_metar.raw != row.raw or entry.metar is None:
            entry.metar = parse_metar(row.raw, row.observed or updated)
        entry.awc_metar = row
        entry.updated = updated
        entry.from_cache = from_cache
        self._metar_rows[row.icao] = row

    def _set_taf(self, row: AwcTaf, updated: datetime, *, from_cache: bool) -> None:
        entry = self.entry(row.icao)
        if entry.awc_taf is None or entry.awc_taf.raw != row.raw or entry.taf is None:
            entry.taf = parse_taf(row.raw, row.issued or updated)
        entry.awc_taf = row
        if entry.updated is None or not from_cache:
            entry.updated = updated
        self._taf_rows[row.icao] = row

    def apply(self, product: Product, rows: list[Any]) -> None:
        """Take a successful fetch: newest report per station, then write the cache."""
        now = self.now()
        self.errors.pop(product, None)
        self.last_success = now
        if product is Product.METAR:
            for row in latest_by_station(rows).values():
                self._set_metar(row, now, from_cache=False)
            payload = [row.source for row in self._metar_rows.values()]
        else:
            for row in rows:
                self._set_taf(row, now, from_cache=False)
            payload = [row.source for row in self._taf_rows.values()]
        if self.cache is not None:
            self.cache.write(CACHE_KEYS[product], payload)

    def load_demo(self, stations: Iterable[DemoStation]) -> None:
        """Fill the state from the bundled demo reports. Nothing is cached or fetched."""
        for demo in stations:
            self.stations[demo.icao] = StationReports(
                demo.icao, demo.awc_metar, demo.awc_taf, demo.metar, demo.taf, self.now(), from_cache=False
            )
        self.last_success = self.now()

    def record_error(self, product: Product, message: str) -> None:
        self.errors[product] = message

    def load_cache(self) -> int:
        """Fill the state from the cache files; returns how many stations got a report. Damaged files are skipped."""
        if self.cache is None:
            return 0
        loaded = 0
        for product, key in CACHE_KEYS.items():
            found = self.cache.read(key)
            if found is None:
                continue
            saved_at, payload = found
            stamp = _aware(saved_at)
            if stamp is None or not isinstance(payload, list):
                continue
            if product is Product.METAR:
                for row in latest_by_station(parse_metars(payload)).values():
                    self._set_metar(row, stamp, from_cache=True)
                    loaded += 1
            else:
                for taf in parse_tafs(payload):
                    self._set_taf(taf, stamp, from_cache=True)
        return loaded

    # --- views ---------------------------------------------------------------------------------------------------

    def reports(self) -> list[StationReports]:
        """One entry per listed station, in list order (an empty one when nothing is known yet)."""
        return [self.stations.get(i) or StationReports(i) for i in self.ids]
