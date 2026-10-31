"""Polling schedule, request budget and report freshness.

Everything time-dependent takes an injected clock (a zero-argument callable returning seconds, monotonic) and an
injected async ``sleep``, so the tests drive the schedule without waiting.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from wxbrief.data.awc import AwcClient, AwcError, ClientError, RateLimited, request_count

log = logging.getLogger(__name__)

Clock = Callable[[], float]
Sleep = Callable[[float], Awaitable[None]]

METAR_INTERVAL = 600.0
TAF_INTERVAL = 1800.0
AWAY_INTERVAL = 1800.0
BACKOFF_CAP = 3600.0
STALE_AFTER = timedelta(minutes=75)


class Freshness(StrEnum):
    FRESH = "fresh"
    STALE = "stale"


def freshness(observed: datetime | None, now: datetime) -> Freshness:
    """A report is fresh for 75 minutes after its observation time; one without a time is stale."""
    if observed is None or now - observed >= STALE_AFTER:
        return Freshness.STALE
    return Freshness.FRESH


class RateBudget:
    """Sliding-window request budget: at most ``limit`` requests in any ``window`` seconds."""

    def __init__(self, limit: int = 100, window: float = 60.0, clock: Clock = time.monotonic) -> None:
        self.limit = limit
        self.window = window
        self._clock = clock
        self._stamps: deque[float] = deque()

    def _trim(self) -> None:
        horizon = self._clock() - self.window
        while self._stamps and self._stamps[0] <= horizon:
            self._stamps.popleft()

    @property
    def used(self) -> int:
        self._trim()
        return len(self._stamps)

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    def try_acquire(self, count: int = 1) -> bool:
        """Spend ``count`` requests if the window has room (a ``count`` above ``limit`` needs an empty window)."""
        count = min(count, self.limit)
        if self.used + count > self.limit:
            return False
        now = self._clock()
        self._stamps.extend([now] * count)
        return True

    def wait_time(self, count: int = 1) -> float:
        """Seconds until ``count`` requests fit (0 when they fit now)."""
        count = min(count, self.limit)
        overflow = self.used + count - self.limit
        if overflow <= 0:
            return 0.0
        return max(0.0, self._stamps[overflow - 1] + self.window - self._clock())


class Product(StrEnum):
    METAR = "metar"
    TAF = "taf"


@dataclass(slots=True)
class _Track:
    interval: float
    due: float = 0.0
    failures: int = 0
    fetched: float | None = None  # clock time of the last successful fetch


def backoff_delay(interval: float, failures: int) -> float:
    """Delay after ``failures`` consecutive failures: the interval doubled each time, capped at an hour."""
    return min(BACKOFF_CAP, interval * 2 ** max(0, failures))


class PollScheduler:
    """Fetches METARs and TAFs for a changing id list, one batched request per product per cycle.

    ``on_result(product, rows)`` is called with each successful fetch, ``on_error(product, error)`` with each failure.
    Failures back off exponentially; a 429 waits at least the ``Retry-After`` the server gave.
    """

    def __init__(
        self,
        client: AwcClient,
        ids: Callable[[], Sequence[str]],
        on_result: Callable[[Product, list[Any]], Any],
        on_error: Callable[[Product, AwcError], Any] | None = None,
        *,
        budget: RateBudget | None = None,
        clock: Clock = time.monotonic,
        sleep: Sleep = asyncio.sleep,
        metar_interval: float = METAR_INTERVAL,
        taf_interval: float = TAF_INTERVAL,
        away_interval: float = AWAY_INTERVAL,
    ) -> None:
        self._client = client
        self._ids = ids
        self._on_result = on_result
        self._on_error = on_error
        self.budget = budget or RateBudget(clock=clock)
        self._clock = clock
        self._sleep = sleep
        self._away_interval = away_interval
        self._tracks = {Product.METAR: _Track(metar_interval), Product.TAF: _Track(taf_interval)}
        self._base = {Product.METAR: metar_interval, Product.TAF: taf_interval}
        self.away = False
        self.hold_until = 0.0  # clock time before which nothing may be fetched (set by a 429's Retry-After)
        self._requests = 0  # how many times poll_now() has been called
        self._wake = asyncio.Event()

    def _interval(self, product: Product) -> float:
        return max(self._base[product], self._away_interval) if self.away else self._base[product]

    def poll_now(self) -> None:
        """Make both products due immediately (a new station was added, the user pressed refresh)."""
        self._requests += 1
        for track in self._tracks.values():
            track.due = self.hold_until  # never earlier than a rate-limit hold
        self._wake.set()

    def return_from_away(self) -> None:
        """Back in focus: a product whose away interval has not run out yet is rescheduled on its normal interval."""
        self.away = False
        for product, track in self._tracks.items():
            if track.failures == 0 and track.fetched is not None:
                track.due = max(self.hold_until, min(track.due, track.fetched + self._interval(product)))
        self._wake.set()

    def hold_remaining(self) -> float:
        """Seconds left of a rate-limit hold (0 when nothing is on hold)."""
        return max(0.0, self.hold_until - self._clock())

    def next_due_in(self) -> float:
        """Seconds until the earliest product is due (0 when something is due now)."""
        now = self._clock()
        return max(0.0, min(track.due for track in self._tracks.values()) - now)

    async def run_cycle(self) -> list[Product]:
        """Fetch every product that is due and has budget; return the products attempted."""
        attempted: list[Product] = []
        for product, track in self._tracks.items():
            if track.due > self._clock():
                continue
            ids = list(self._ids())  # read per product: a station added during the METAR fetch is in the TAF one
            if not ids:
                track.due = self._clock() + self._interval(product)
                continue
            requests = request_count(ids)  # a long id list is sent as several requests, each spending budget
            if not self.budget.try_acquire(requests):
                track.due = self._clock() + self.budget.wait_time(requests)
                continue
            attempted.append(product)
            requested = self._requests
            try:
                rows: list[Any] = (
                    await self._client.metars(ids) if product is Product.METAR else await self._client.tafs(ids)
                )
            except Exception as exc:  # nothing a fetch raises may end the poller
                if not isinstance(exc, AwcError):
                    log.exception("unexpected error fetching %s", product.value)
                error = exc if isinstance(exc, AwcError) else ClientError(f"unexpected {type(exc).__name__}")
                track.failures += 1
                delay = backoff_delay(self._interval(product), track.failures - 1)
                if self._requests == requested:  # a poll_now() during the fetch keeps the due time it set
                    track.due = self._clock() + delay
                if isinstance(error, RateLimited):
                    # The limit is per client, not per product: hold every track back and end the cycle.
                    hold = self._clock() + max(delay, error.retry_after)
                    self.hold_until = max(self.hold_until, hold)
                    for other in self._tracks.values():
                        other.due = max(other.due, hold)
                if self._on_error:
                    self._notify(self._on_error, product, error)
                if isinstance(error, RateLimited):
                    break
                continue
            track.failures = 0
            track.fetched = self._clock()
            if self._requests == requested:
                track.due = track.fetched + self._interval(product)
            self._notify(self._on_result, product, rows)
        return attempted

    @staticmethod
    def _notify(callback: Callable[..., Any], *args: Any) -> None:
        """Call a result or error callback; one that raises is logged and must not end the poller."""
        try:
            callback(*args)
        except Exception:
            log.exception("poll callback failed")

    async def run(self) -> None:
        """Poll until cancelled."""
        while True:
            await self.run_cycle()
            await self._wait(self.next_due_in())

    async def _wait(self, seconds: float) -> None:
        if seconds <= 0:
            return
        sleeper = asyncio.ensure_future(self._sleep(seconds))
        waker = asyncio.ensure_future(self._wake.wait())
        try:
            await asyncio.wait({sleeper, waker}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            sleeper.cancel()
            waker.cancel()
        self._wake.clear()
