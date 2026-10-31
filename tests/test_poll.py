"""Poll schedule, rate budget and freshness with an injected clock (no real waiting)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from wxbrief.data.awc import AwcError, ClientError, RateLimited, ServerError
from wxbrief.data.poll import (
    BACKOFF_CAP,
    Freshness,
    PollScheduler,
    Product,
    RateBudget,
    backoff_delay,
    freshness,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class FakeClient:
    """Stands in for AwcClient: records calls, and raises queued errors."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []
        self.errors: list[AwcError] = []
        self.metar_only = False

    async def metars(self, ids: list[str]) -> list[Any]:
        return self._go("metar", ids)

    async def tafs(self, ids: list[str]) -> list[Any]:
        return self._go("taf", ids)

    def _go(self, product: str, ids: list[str]) -> list[Any]:
        self.calls.append((product, list(ids)))
        if self.errors and (product == "metar" or not self.metar_only):
            raise self.errors.pop(0)
        return [product]


def make(
    clock: FakeClock, client: FakeClient, ids: list[str] | None = None, **kw: Any
) -> tuple[PollScheduler, list[Any]]:
    seen: list[Any] = []
    scheduler = PollScheduler(
        client,  # type: ignore[arg-type]
        lambda: ids if ids is not None else ["KDEN", "EGLL"],
        lambda product, rows: seen.append((product, rows)),
        lambda product, error: seen.append((product, error)),
        clock=clock,
        **kw,
    )
    return scheduler, seen


async def test_first_cycle_fetches_both_products_once_in_one_batch() -> None:
    clock, client = FakeClock(), FakeClient()
    scheduler, seen = make(clock, client)
    assert await scheduler.run_cycle() == [Product.METAR, Product.TAF]
    assert client.calls == [("metar", ["KDEN", "EGLL"]), ("taf", ["KDEN", "EGLL"])]
    assert len(seen) == 2


async def test_intervals_metar_600_taf_1800() -> None:
    clock, client = FakeClock(), FakeClient()
    scheduler, _ = make(clock, client)
    await scheduler.run_cycle()
    clock.now += 599
    assert await scheduler.run_cycle() == []
    assert scheduler.next_due_in() == 1
    clock.now += 1
    assert await scheduler.run_cycle() == [Product.METAR]
    clock.now += 600
    assert await scheduler.run_cycle() == [Product.METAR]
    clock.now += 600  # 1800 s since the start
    assert await scheduler.run_cycle() == [Product.METAR, Product.TAF]


async def test_away_mode_slows_metar_to_1800() -> None:
    clock, client = FakeClock(), FakeClient()
    scheduler, _ = make(clock, client)
    scheduler.away = True
    await scheduler.run_cycle()
    clock.now += 600
    assert await scheduler.run_cycle() == []
    clock.now += 1200
    assert await scheduler.run_cycle() == [Product.METAR, Product.TAF]


async def test_failures_back_off_exponentially_and_cap() -> None:
    clock, client = FakeClock(), FakeClient()
    client.errors = [ServerError(500)] * 8
    client.metar_only = True
    scheduler, seen = make(clock, client, taf_interval=99999)
    delays = []
    for _ in range(5):
        await scheduler.run_cycle()
        delays.append(scheduler._tracks[Product.METAR].due - clock.now)
        clock.now += delays[-1]
    assert delays[:3] == [600, 1200, 2400]
    assert delays[3] == BACKOFF_CAP
    assert backoff_delay(1800, 5) == BACKOFF_CAP
    assert any(isinstance(item[1], ServerError) for item in seen)


async def test_success_resets_the_backoff() -> None:
    clock, client = FakeClock(), FakeClient()
    client.errors = [ServerError(500)]
    scheduler, _ = make(clock, client)
    await scheduler.run_cycle()  # metar fails, taf succeeds
    clock.now += 600
    await scheduler.run_cycle()  # metar succeeds again
    assert scheduler.next_due_in() == 600


async def test_retry_after_is_honoured_when_longer_than_the_backoff() -> None:
    clock, client = FakeClock(), FakeClient()
    client.errors = [RateLimited(1500)]
    scheduler, _ = make(clock, client)
    assert await scheduler.run_cycle() == [Product.METAR]  # 429 ends the cycle: taf is not tried
    clock.now += 1499
    assert await scheduler.run_cycle() == []  # taf was held back too
    clock.now += 1
    assert await scheduler.run_cycle() == [Product.METAR, Product.TAF]


async def test_a_short_retry_after_on_the_slow_track_holds_for_that_long_not_for_the_backoff() -> None:
    class TafLimited(FakeClient):
        limited = False

        def _go(self, product: str, ids: list[str]) -> list[Any]:
            if product == "taf" and self.limited:
                raise RateLimited(5)
            return super()._go(product, ids)

    clock, client = FakeClock(), TafLimited()
    scheduler, _ = make(clock, client)
    await scheduler.run_cycle()  # both succeed
    client.limited = True
    clock.now += 1800
    assert await scheduler.run_cycle() == [Product.METAR, Product.TAF]  # the TAF is limited for 5 s
    assert scheduler.hold_remaining() == 5  # not the 1800 s backoff of the TAF track
    clock.now += 5
    scheduler.poll_now()
    assert (await scheduler.run_cycle())[0] is Product.METAR


async def test_empty_watchlist_makes_no_requests() -> None:
    clock, client = FakeClock(), FakeClient()
    scheduler, _ = make(clock, client, ids=[])
    assert await scheduler.run_cycle() == []
    assert client.calls == []


async def test_poll_now_makes_everything_due() -> None:
    clock, client = FakeClock(), FakeClient()
    scheduler, _ = make(clock, client)
    await scheduler.run_cycle()
    scheduler.poll_now()
    assert await scheduler.run_cycle() == [Product.METAR, Product.TAF]


async def test_poll_now_does_not_break_a_rate_limit_hold() -> None:
    clock, client = FakeClock(), FakeClient()
    client.errors = [RateLimited(1500)]
    scheduler, _ = make(clock, client)
    await scheduler.run_cycle()
    scheduler.poll_now()  # the user presses refresh during the hold
    assert await scheduler.run_cycle() == []
    assert scheduler.next_due_in() == 1500
    clock.now += 1500
    scheduler.poll_now()
    assert await scheduler.run_cycle() == [Product.METAR, Product.TAF]


async def test_exhausted_budget_defers_instead_of_requesting() -> None:
    clock, client = FakeClock(), FakeClient()
    scheduler, _ = make(clock, client, budget=RateBudget(1, 60, clock))
    assert await scheduler.run_cycle() == [Product.METAR]
    assert [c[0] for c in client.calls] == ["metar"]
    clock.now += 60
    assert await scheduler.run_cycle() == [Product.TAF]


async def test_run_loop_sleeps_until_due_then_stops_on_cancel() -> None:
    import asyncio

    clock, client = FakeClock(), FakeClient()
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)
        clock.now += seconds
        if len(slept) >= 2:
            await asyncio.Event().wait()  # park, as a real sleep would

    scheduler, _ = make(clock, client, sleep=fake_sleep)
    task = asyncio.ensure_future(scheduler.run())
    for _ in range(50):
        await asyncio.sleep(0)
        if len(slept) >= 2:
            break
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert slept[0] == 600
    assert [c[0] for c in client.calls][:3] == ["metar", "taf", "metar"]


def test_rate_budget_sliding_window() -> None:
    clock = FakeClock()
    budget = RateBudget(100, 60, clock)
    assert budget.remaining == 100
    assert all(budget.try_acquire() for _ in range(100))
    assert not budget.try_acquire()
    assert budget.used == 100 and budget.remaining == 0
    assert budget.wait_time() == 60
    clock.now += 30
    assert budget.wait_time() == 30
    clock.now += 30
    assert budget.remaining == 100 and budget.wait_time() == 0
    assert budget.try_acquire(100)


def test_freshness_threshold_is_75_minutes() -> None:
    now = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
    assert freshness(now - timedelta(minutes=74), now) is Freshness.FRESH
    assert freshness(now - timedelta(minutes=75), now) is Freshness.STALE
    assert freshness(None, now) is Freshness.STALE


def test_rate_budget_count_above_the_limit_does_not_raise() -> None:
    clock = FakeClock()
    budget = RateBudget(3, 60, clock)
    assert budget.wait_time(10) == 0
    assert budget.try_acquire(10)
    assert budget.used == 3
    assert budget.wait_time(10) == 60


async def test_a_long_id_list_spends_one_budget_unit_per_request() -> None:
    clock = FakeClock()
    client = FakeClient()
    ids = [f"K{n:03d}" for n in range(401)]  # two chunks per product
    scheduler, _ = make(clock, client, ids)
    await scheduler.run_cycle()
    assert scheduler.budget.used == 4


class GatedClient(FakeClient):
    """Holds each METAR fetch open until ``gate`` is set."""

    def __init__(self) -> None:
        super().__init__()
        self.gate = asyncio.Event()

    async def metars(self, ids: list[str]) -> list[Any]:
        await self.gate.wait()
        return self._go("metar", ids)


async def test_poll_now_during_a_fetch_is_not_lost() -> None:
    clock, client = FakeClock(), GatedClient()
    ids = ["KDEN"]
    scheduler, _ = make(clock, client, ids)
    cycle = asyncio.ensure_future(scheduler.run_cycle())
    for _ in range(5):
        await asyncio.sleep(0)  # the METAR request is in flight
    ids.append("EGLL")
    scheduler.poll_now()
    client.gate.set()
    await cycle
    assert client.calls == [("metar", ["KDEN"]), ("taf", ["KDEN", "EGLL"])]  # the TAF fetch sees the new station
    assert scheduler.next_due_in() == 0  # and the METAR is still due
    assert await scheduler.run_cycle() == [Product.METAR]
    assert client.calls[-1] == ("metar", ["KDEN", "EGLL"])


async def test_an_unexpected_exception_is_reported_not_raised() -> None:
    class Broken(FakeClient):
        async def metars(self, ids: list[str]) -> list[Any]:
            raise RecursionError

    clock, client = FakeClock(), Broken()
    scheduler, seen = make(clock, client)
    await scheduler.run_cycle()
    assert [type(item[1]) for item in seen if item[0] is Product.METAR] == [ClientError]


async def test_a_short_blur_does_not_leave_the_away_interval_in_force() -> None:
    clock, client = FakeClock(), FakeClient()
    scheduler, _ = make(clock, client, ["KDEN"])
    await scheduler.run_cycle()
    clock.now += 599
    scheduler.away = True
    clock.now += 1
    await scheduler.run_cycle()  # the METAR poll that falls due while away
    assert scheduler._tracks[Product.METAR].due - clock.now == 1800
    clock.now += 1
    scheduler.return_from_away()
    assert scheduler.next_due_in() == 599


async def test_returning_after_a_long_blur_polls_what_is_overdue() -> None:
    clock, client = FakeClock(), FakeClient()
    scheduler, _ = make(clock, client, ["KDEN"])
    await scheduler.run_cycle()
    scheduler.away = True
    clock.now += 700
    scheduler.return_from_away()
    assert await scheduler.run_cycle() == [Product.METAR]


async def test_a_raising_callback_does_not_end_the_poller() -> None:
    clock, client = FakeClock(), FakeClient()
    calls: list[Product] = []

    def broken(product: Product, rows: list[Any]) -> None:
        calls.append(product)
        raise RuntimeError("apply failed")

    scheduler = PollScheduler(client, lambda: ["KDEN"], broken, broken_error, clock=clock)  # type: ignore[arg-type]
    assert await scheduler.run_cycle() == [Product.METAR, Product.TAF]
    assert calls == [Product.METAR, Product.TAF]


def broken_error(product: Product, error: AwcError) -> None:
    raise RuntimeError("report failed")


async def test_a_raising_error_callback_does_not_end_the_poller() -> None:
    clock, client = FakeClock(), FakeClient()
    client.errors = [ServerError(500), ServerError(500)]
    scheduler = PollScheduler(client, lambda: ["KDEN"], lambda p, r: None, broken_error, clock=clock)  # type: ignore[arg-type]
    assert await scheduler.run_cycle() == [Product.METAR, Product.TAF]
