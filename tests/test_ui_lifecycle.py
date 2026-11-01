"""Screens that stay open while time passes and data arrives: the clock, expiry, scroll, focus and redraws."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from corpus import awc_taf_rows
from rich.text import Text
from test_timeline_ui import demo_app, settle, text_of
from textual.widgets import Collapsible, TextArea

from wxbrief import app as app_module
from wxbrief.data.demo import DEMO_NOW
from wxbrief.data.models import parse_tafs
from wxbrief.data.poll import Product
from wxbrief.decode.taf import parse_taf
from wxbrief.ui.screens import station_detail
from wxbrief.ui.screens.briefing import BriefingScreen
from wxbrief.ui.screens.paste import PasteDecodeScreen
from wxbrief.ui.screens.station_detail import StationDetailScreen
from wxbrief.ui.widgets.detail import DecodedTable, DetailPane, StationHeader
from wxbrief.ui.widgets.station_card import StationCard
from wxbrief.ui.widgets.station_list import StationList
from wxbrief.ui.widgets.status_bar import StatusBar
from wxbrief.ui.widgets.taf_timeline import TafTimeline


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async def refuse(self: object, request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"network access in a test: {request.url}")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", refuse)
    monkeypatch.setenv("WXBRIEF_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(app_module, "save_config", lambda *args, **kwargs: True)


def later(app: app_module.WxBriefApp, delta: timedelta) -> None:
    app.options.now = lambda: DEMO_NOW + delta


# --- the grid's station screen ---------------------------------------------------------------------------------------


async def test_the_station_screen_moves_with_the_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(station_detail, "REDRAW_SECONDS", 0.05)
    app = demo_app("--layout", "grid")
    async with app.run_test(size=(140, 40)) as pilot:
        await settle(pilot)
        await pilot.press("enter")
        await settle(pilot)
        screen = app.screen
        assert isinstance(screen, StationDetailScreen)
        assert "fresh" in text_of(screen.query_one(StationHeader))
        later(app, timedelta(hours=3))  # no poll, no key: only the clock moved
        await pilot.pause(0.3)
        header = text_of(screen.query_one(StationHeader))
        assert "stale" in header and "3 h" in header


async def test_the_station_screen_shows_what_a_poll_brought() -> None:
    app = demo_app("--layout", "grid")
    async with app.run_test(size=(140, 40)) as pilot:
        await settle(pilot)
        await pilot.press("enter")
        await settle(pilot)
        screen = app.screen
        assert isinstance(screen, StationDetailScreen)
        assert "TAF KDEN" in text_of(screen.query_one("#raw"))
        others = [r for r in awc_taf_rows() if r["icaoId"] == "KATL"]
        app._on_result(Product.TAF, parse_tafs(others))  # a TAF answer that no longer lists the station
        await settle(pilot)
        assert "TAF KDEN" not in text_of(screen.query_one("#raw"))


# --- an expired forecast ---------------------------------------------------------------------------------------------


async def test_an_expired_taf_is_marked_and_has_no_prevailing_period() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 50)) as pilot:
        await settle(pilot)
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        assert briefing.query_one(TafTimeline).display
        later(app, timedelta(days=3))
        briefing.refresh_view()
        await settle(pilot)
        assert not briefing.query_one(TafTimeline).display
        assert not briefing.query_one("#period").display
        assert "expired" in text_of(briefing.query_one("#taf-note"))


async def test_a_taf_with_no_readable_valid_period_is_not_called_missing() -> None:
    app = demo_app("--layout", "grid")
    async with app.run_test(size=(140, 40)) as pilot:
        await settle(pilot)
        app.state.stations["KDEN"].taf = parse_taf("TAF KDEN 311140Z 32005KT 9999 SKC", DEMO_NOW)
        app.briefing.refresh_view()
        await settle(pilot)
        card = next(c for c in app.screen.query(StationCard) if c.icao == "KDEN")
        assert "no TAF" not in text_of(card)


# --- the header ------------------------------------------------------------------------------------------------------


async def test_the_header_does_not_claim_a_two_hour_gap_it_never_checked() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot)
        assert app.state.add("KXXX", persist=False)
        app.briefing.select("KXXX")
        await settle(pilot)
        header = text_of(app.screen.query_one(StationHeader))
        assert "No report yet" in header and "2 hours" not in header
        assert "r to refresh" in header
        entry = app.state.stations["KDEN"]
        assert entry.awc_metar is not None
        entry.awc_metar = replace(entry.awc_metar, observed=None)  # a row without a time still has its report
        app.briefing.select("KDEN")
        await settle(pilot)
        assert "No report yet" not in text_of(app.screen.query_one(StationHeader))


# --- scrolling -------------------------------------------------------------------------------------------------------


async def test_another_station_starts_at_the_top_but_a_redraw_keeps_the_place() -> None:
    app = demo_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await settle(pilot)
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        pane = briefing.query_one(DetailPane)
        await pilot.press("3")
        await settle(pilot)
        assert pane.scroll_y > 0
        scrolled = pane.scroll_y
        briefing.refresh_view()  # the 30 s redraw of the same station
        await settle(pilot)
        assert pane.scroll_y == scrolled
        await pilot.press("j")
        await settle(pilot)
        assert pane.scroll_y == 0


async def test_a_redraw_keeps_the_station_list_scroll_and_a_step_follows_the_selection() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 20)) as pilot:
        await settle(pilot)
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        for n in range(30):
            app.state.add(f"KA{n:02d}", persist=False)
        briefing.refresh_view()
        await settle(pilot)
        stations = briefing.query_one(StationList)
        assert stations.max_scroll_y > 5
        stations.scroll_to(y=5, animate=False)
        await settle(pilot)
        briefing.refresh_view()
        await settle(pilot)
        assert stations.scroll_y == 5
        for _ in range(20):
            await pilot.press("j")
        await settle(pilot)
        row = stations.highlighted
        assert row is not None
        assert stations.scroll_y <= row < stations.scroll_y + stations.scrollable_content_region.height


async def test_the_decoded_table_is_not_a_second_scroller() -> None:
    app = demo_app()
    async with app.run_test(size=(60, 16)) as pilot:
        await settle(pilot)
        table = app.screen.query_one(DecodedTable)
        assert table.region.height >= table.virtual_size.height


# --- focus -----------------------------------------------------------------------------------------------------------


async def test_focus_on_a_hidden_remarks_title_goes_to_the_pane() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot)
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        box = briefing.query_one("#remarks-box", Collapsible)
        assert box.display
        box.query_one("CollapsibleTitle").focus()
        await settle(pilot)
        briefing.select("EGLL")  # its METAR has no remarks
        await settle(pilot)
        assert not box.display
        assert briefing.query_one(DetailPane).has_focus


async def test_a_resize_leaves_the_timeline_focused() -> None:
    app = demo_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await settle(pilot)
        await pilot.press("3")
        await settle(pilot)
        timeline = app.screen.query_one(TafTimeline)
        assert timeline.has_focus
        await pilot.resize_terminal(82, 24)
        await settle(pilot)
        assert timeline.has_focus


# --- the paste screen and the status bar -----------------------------------------------------------------------------


async def test_the_paste_screen_follows_a_units_change() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot)
        await pilot.press("p")
        await settle(pilot)
        screen = app.screen
        assert isinstance(screen, PasteDecodeScreen)
        screen.query_one(TextArea).text = "METAR KDEN 131453Z 06007KT 3/4SM BR OVC003 09/08 A3001"
        screen.decode_now()
        app.apply_setting("units", "us")
        before = screen.discord_text
        app.apply_setting("units", "metric")
        assert screen.discord_text != before


async def test_a_long_error_cuts_the_message_not_the_freshness() -> None:
    app = demo_app()
    async with app.run_test(size=(60, 20)) as pilot:
        await settle(pilot)
        app.state.record_error(Product.METAR, "metar: ConnectError: " + "x" * 120, offline=True)
        app.briefing.refresh_view()
        await settle(pilot)
        rendered = app.screen.query_one(StatusBar).render()
        text = rendered.plain if isinstance(rendered, Text) else str(rendered)
        assert text.index("fresh") < text.index("(")
        assert text.index("(") > text.index("|")


# --- the grid, help and paste ----------------------------------------------------------------------------------------


async def test_an_empty_grid_says_how_to_add_a_station() -> None:
    app = demo_app("--layout", "grid")
    async with app.run_test(size=(140, 40)) as pilot:
        await settle(pilot)
        empty = app.screen.query_one("#empty")
        assert not empty.display
        app.state.watchlist.clear()
        app.state.session.clear()
        app.briefing.refresh_view()
        await settle(pilot)
        assert empty.display and "No stations yet" in text_of(empty)


async def test_down_goes_to_the_last_card_when_the_row_below_is_shorter() -> None:
    app = demo_app("--layout", "grid")
    async with app.run_test(size=(140, 40)) as pilot:  # three columns: rows of 3, 3, 3 and 1 of the ten demo stations
        await settle(pilot)
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        await pilot.press("right", "down", "down")  # index 1 -> 4 -> 7
        await settle(pilot)
        assert briefing.selected == app.state.ids[7]
        await pilot.press("down")  # 10 does not exist, but the last row does
        await settle(pilot)
        assert briefing.selected == app.state.ids[-1]
        await pilot.press("down")
        await settle(pilot)
        assert briefing.selected == app.state.ids[-1]


def test_the_help_says_what_enter_and_the_arrows_do_in_the_grid() -> None:
    from wxbrief.i18n import Translator
    from wxbrief.i18n.keys import K

    body = Translator.load("en").t(K.UI_HELP_BODY)
    assert "the grid: open the station" in body and "the grid: arrows over the cards" in body


async def test_a_paste_past_the_limit_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    from wxbrief.ui.screens import paste

    monkeypatch.setattr(paste, "MAX_PASTE_CHARS", 80)
    app = demo_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot)
        await pilot.press("p")
        await settle(pilot)
        screen = app.screen
        assert isinstance(screen, PasteDecodeScreen)
        report = "METAR KDEN 131453Z 06007KT 3/4SM BR OVC003 09/08 A3001"
        screen.query_one(TextArea).text = report
        screen.decode_now()
        assert "characters were decoded" not in text_of(screen.query_one("#paste-result"))
        screen.query_one(TextArea).text = (report + "\n") * 5
        screen.decode_now()
        assert "first 80 characters" in screen.query_one("#paste-result").content.renderables[0].plain  # type: ignore[attr-defined]


async def test_the_help_screen_says_what_the_app_is_not() -> None:
    from textual.widgets import Label

    from wxbrief.ui.screens.help import HelpScreen

    app = demo_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot)
        await pilot.press("question_mark")
        await settle(pilot)
        assert isinstance(app.screen, HelpScreen)
        texts = [text_of(label) for label in app.screen.query(Label)]
        assert any("not a substitute for an official weather briefing" in text for text in texts)
