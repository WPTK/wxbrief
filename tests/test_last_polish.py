"""The last polish before 0.3.0: Esc leaves the detail pane, plain-language offline messages, one zone on a card."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from test_footer import shown
from test_timeline_ui import demo_app, settle, text_of

from wxbrief import app as app_module
from wxbrief.data.awc import ClientError, TransportError
from wxbrief.data.poll import Product
from wxbrief.decode.model import FlightCategory
from wxbrief.ui.screens.briefing import BriefingScreen
from wxbrief.ui.strip import StripCell
from wxbrief.ui.widgets import station_card
from wxbrief.ui.widgets.detail import DetailPane
from wxbrief.ui.widgets.station_card import StationCard
from wxbrief.ui.widgets.station_list import StationList
from wxbrief.ui.widgets.status_bar import StatusBar
from wxbrief.ui.widgets.taf_timeline import tick_labels


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async def refuse(self: object, request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"network access in a test: {request.url}")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", refuse)
    monkeypatch.setenv("WXBRIEF_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(app_module, "save_config", lambda *args, **kwargs: True)


# --- Esc in the detail pane -----------------------------------------------------------------------------------------


async def test_escape_in_the_detail_pane_returns_to_the_station_list() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        await pilot.press("down", "enter")
        await settle(pilot)
        assert isinstance(app.focused, DetailPane)
        chosen = briefing.selected
        await pilot.press("escape")
        await settle(pilot)
        assert isinstance(app.focused, StationList)
        await pilot.press("down")
        await settle(pilot)
        assert briefing.selected != chosen


async def test_escape_is_on_the_key_bar_only_while_the_detail_pane_has_the_focus() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        assert "escape" not in shown(app)
        await pilot.press("enter")
        await settle(pilot)
        assert "escape" in shown(app)
        text = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
        assert "Back" in text
        await pilot.press("escape")
        await settle(pilot)
        assert "escape" not in shown(app)


async def test_escape_does_nothing_in_the_grid() -> None:
    app = demo_app("--layout", "grid")
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        assert isinstance(app.screen, BriefingScreen)
        await pilot.press("escape")
        await settle(pilot)
        assert isinstance(app.screen, BriefingScreen) and not isinstance(app.focused, StationList)


# --- the offline message ---------------------------------------------------------------------------------------------


async def test_an_offline_error_reads_in_plain_words_on_the_status_bar_and_the_toast() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        for _ in range(2):
            app._on_error(Product.METAR, TransportError("ConnectError: All connection attempts failed"))
        await settle(pilot)
        status = text_of(app.screen.query_one(StatusBar))
        assert "offline, showing saved data from" in status and "fresh" not in status
        assert "ConnectError" not in status
        toasts = [n.message for n in app._notifications]
        assert any("Can't reach aviationweather.gov" in m for m in toasts)
        assert not any("ConnectError" in m for m in toasts)
        assert "ConnectError" in app.state.errors[Product.METAR]  # the raw text stays in the state and the log


async def test_other_errors_do_not_leak_raw_text_either() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        app._on_error(Product.TAF, ClientError("unexpected status 418"))
        await settle(pilot)
        status = text_of(app.screen.query_one(StatusBar))
        assert "aviationweather.gov problem" in status and "418" not in status
        assert not any("418" in n.message for n in app._notifications)


async def test_the_offline_message_fits_a_small_terminal() -> None:
    app = demo_app()
    async with app.run_test(size=(60, 16)) as pilot:
        await settle(pilot)
        for _ in range(2):
            app._on_error(Product.METAR, TransportError("ConnectError: x"))
        await settle(pilot)
        bar = app.screen.query_one(StatusBar)
        assert len(text_of(bar).splitlines()) == 1 and "offline" in text_of(bar)


# --- one zone on a card ----------------------------------------------------------------------------------------------


def _cells(first: datetime, count: int) -> list[StripCell]:
    return [
        StripCell(
            first + timedelta(hours=i), first + timedelta(hours=i + 1), FlightCategory.VFR, FlightCategory.VFR,
            False, False, None, (i,), (0,),
        )
        for i in range(count)
    ]  # fmt: skip


async def test_a_card_shows_one_zone_where_the_strip_crosses_the_end_of_daylight_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cells = _cells(datetime(2026, 11, 1, 6, 0, tzinfo=UTC), 12)  # Denver turns clocks back at 08:00Z
    monkeypatch.setattr(station_card, "mini_cells", lambda hours, now: cells)
    app = demo_app("--time", "station", "--layout", "grid")
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        card = next(c for c in app.screen.query(StationCard) if c.icao == "KDEN")
        lines = text_of(card).splitlines()
        zones = lines[2]
        assert zones.rstrip().endswith("MDT") and "MST" not in zones
        assert max(len(line) for line in lines) <= card.content_size.width


async def test_the_timeline_keeps_every_zone_of_a_daylight_saving_change() -> None:
    app = demo_app("--time", "station")
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        cells = _cells(datetime(2026, 11, 1, 6, 0, tzinfo=UTC), 12)
        ctx = app.ctx
        assert tick_labels(cells, 2, ctx, "KDEN", every_cell=False).plain.endswith("MDT/MST")
        assert tick_labels(cells, 2, ctx, "KDEN", every_cell=False, all_zones=False).plain.endswith("MDT")
