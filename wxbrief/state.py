"""Application state: the station list, the latest report for each, and the cache that backs them.

Plain data and functions with no Textual imports, so the screens only read it and the tests build it directly.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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
CACHE_MAX_AGE = timedelta(hours=48)  # a cached report of a station not in this run's list is dropped after this
FETCHED_KEY = "wxbriefFetched"  # added to each cached row: when this row was fetched, which the file's save time is not


def _fetched_at(source: Mapping[str, Any], default: datetime) -> datetime:
    """The fetch time stamped on a cached row; ``default`` (the file's save time) for one without a usable stamp."""
    try:
        stamp = datetime.fromisoformat(source[FETCHED_KEY])
    except (KeyError, TypeError, ValueError):
        return default
    return stamp if stamp.tzinfo is not None else default


@dataclass(slots=True)
class StationReports:
    """What is known about one station: the newest AWC rows and their decodes."""

    icao: str
    awc_metar: AwcMetar | None = None
    awc_taf: AwcTaf | None = None
    metar: Metar | None = None
    taf: Taf | None = None
    metar_updated: datetime | None = None  # when each product last arrived (its fetch time, also when cached)
    taf_updated: datetime | None = None
    metar_cached: bool = False  # whether the report held for each product came from the cache, not from this run
    taf_cached: bool = False

    @property
    def updated(self) -> datetime | None:
        """When the data shown last arrived: the METAR's fetch time, else the TAF's."""
        return self.metar_updated or self.taf_updated

    @property
    def from_cache(self) -> bool:
        """Whether the data behind ``updated`` came from the cache."""
        return self.metar_cached if self.metar_updated else self.taf_cached

    def freshness(self, now: datetime) -> Freshness:
        observed = self.awc_metar.observed if self.awc_metar else None
        return freshness(observed, now)


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
        self.offline: set[Product] = set()  # products whose last failure was the network, not the server or the disk

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
        elif code in self.session:
            self.session.remove(code)
        else:
            return False
        if not self.ids:  # nothing left to fetch, so no fetch will ever clear an old failure
            self.errors.clear()
            self.offline.clear()
        return True

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
        entry.metar_updated = updated
        entry.metar_cached = from_cache

    def _set_taf(self, row: AwcTaf, updated: datetime, *, from_cache: bool) -> None:
        entry = self.entry(row.icao)
        previous = entry.awc_taf
        if previous is None or previous.raw != row.raw or previous.modifiers != row.modifiers or entry.taf is None:
            entry.taf = parse_taf(row.raw, row.issued or updated, row.modifiers)
        entry.awc_taf = row
        entry.taf_updated = updated
        entry.taf_cached = from_cache

    def apply(self, product: Product, rows: list[Any]) -> None:
        """Take a successful fetch: newest report per station, then write the cache."""
        now = self.now()
        self.errors.pop(product, None)
        self.offline.discard(product)
        if product is Product.METAR:
            for row in latest_by_station(rows).values():
                self._set_metar(row, now, from_cache=False)
        else:
            # A TAF fetch that succeeded is the whole truth about the listed stations: one it no longer returns has
            # lapsed or been withdrawn, so the old forecast goes rather than staying on screen as if current.
            returned = {row.icao for row in rows}
            for icao in self.ids:
                entry = self.stations.get(icao)
                if entry is not None and entry.awc_taf is not None and icao not in returned:
                    entry.awc_taf = entry.taf = entry.taf_updated = None
                    entry.taf_cached = False
            for row in rows:
                self._set_taf(row, now, from_cache=False)
        self._write_cache(product, now)

    def _write_cache(self, product: Product, now: datetime) -> None:
        """Write the cache file for ``product``, each row stamped with its own fetch time.

        The cache folder is shared by every run, whatever its station list, so the file keeps the rows of stations
        outside this run's list too (those loaded from it, and any another run added since), dropping a row only
        when it is older than ``CACHE_MAX_AGE`` or is a TAF that has expired.
        """
        if self.cache is None:
            return
        payload: list[dict[str, Any]] = []
        written: set[str] = set()
        listed = set(self.ids)
        for icao in [*self.ids, *(i for i in self.stations if i not in listed)]:
            entry = self.stations.get(icao)
            if entry is None:
                continue
            row: AwcMetar | AwcTaf | None
            if product is Product.METAR:
                row, fetched = entry.awc_metar, entry.metar_updated
            else:
                row, fetched = entry.awc_taf, entry.taf_updated
                if entry.taf is not None and entry.taf.valid_to is not None and entry.taf.valid_to <= now:
                    continue
            if row is None or fetched is None:
                continue
            written.add(icao)
            if icao not in listed and now - fetched > CACHE_MAX_AGE:
                continue
            payload.append({**row.source, FETCHED_KEY: fetched.isoformat()})
        payload.extend(self._others_cached(product, now, written | listed))
        if not self.cache.write(CACHE_KEYS[product], payload):
            self.record_error(product, f"{product.value}: could not write the cache in {self.cache.directory}")

    def _others_cached(self, product: Product, now: datetime, skip: set[str]) -> list[dict[str, Any]]:
        """Unexpired rows in the cache file for stations this run knows nothing about (another run wrote them)."""
        assert self.cache is not None
        found = self.cache.read(CACHE_KEYS[product])
        if found is None or not isinstance(found[1], list):
            return []
        saved_at, rows = found
        kept: list[dict[str, Any]] = []
        parse = parse_metars if product is Product.METAR else parse_tafs
        for parsed in parse(rows):
            if parsed.icao in skip:
                continue
            fetched = _fetched_at(parsed.source, saved_at)
            expired = isinstance(parsed, AwcTaf) and parsed.valid_to is not None and parsed.valid_to <= now
            if not expired and now - fetched <= CACHE_MAX_AGE:
                kept.append({**parsed.source, FETCHED_KEY: fetched.isoformat()})
        return kept

    def load_demo(self, stations: Iterable[DemoStation]) -> None:
        """Fill the state from the bundled demo reports. Nothing is cached or fetched."""
        for demo in stations:
            self.stations[demo.icao] = StationReports(
                demo.icao, demo.awc_metar, demo.awc_taf, demo.metar, demo.taf, self.now(), self.now()
            )

    def record_error(self, product: Product, message: str, *, offline: bool = False) -> None:
        self.errors[product] = message
        self.offline.discard(product)
        if offline:
            self.offline.add(product)

    def load_cache(self) -> int:
        """Fill the state from the cache files; returns how many stations got a report. Damaged files are skipped."""
        if self.cache is None:
            return 0
        loaded = 0
        self.cache.clean(CACHE_KEYS.values())
        for product, key in CACHE_KEYS.items():
            found = self.cache.read(key)
            if found is None:
                continue
            saved_at, payload = found
            if not isinstance(payload, list):
                continue
            if product is Product.METAR:
                for row in latest_by_station(parse_metars(payload)).values():
                    self._set_metar(row, _fetched_at(row.source, saved_at), from_cache=True)
                    loaded += 1
            else:
                for taf in parse_tafs(payload):
                    self._set_taf(taf, _fetched_at(taf.source, saved_at), from_cache=True)
        return loaded

    # --- views ---------------------------------------------------------------------------------------------------

    def reports(self) -> list[StationReports]:
        """One entry per listed station, in list order (an empty one when nothing is known yet)."""
        return [self.stations.get(i) or StationReports(i) for i in self.ids]
