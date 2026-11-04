"""UI-screen audit fixes: focus after a resize, the forecast placeholder, the section keys, clicks, toasts, the demo
header, the pinned header, the grid legend and the offline counter."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from test_app_smoke import wait_for
from test_layout import key_line
from test_timeline_ui import demo_app, settle, text_of
from textual.events import Click, MouseUp

from wxbrief.data.poll import Product
from wxbrief.i18n.keys import K
from wxbrief.state import AppState
from wxbrief.ui.screens.briefing import BriefingScreen
from wxbrief.ui.screens.station_detail import StationDetailScreen
from wxbrief.ui.widgets.detail import DetailPane, StationHeader
from wxbrief.ui.widgets.station_card import StationCard
from wxbrief.ui.widgets.station_grid import StationGrid
from wxbrief.ui.widgets.station_list import StationList


def toasts(app: object) -> list[str]:
    return [n.message for n in app._notifications]  # type: ignore[attr-defined]


# --- #255: the keyboard goes back to the list when the list comes back ---------------------------------------------


async def test_a_narrow_trip_hands_the_keyboard_back_to_the_list() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 36)) as pilot:
        await settle(pilot)
        assert isinstance(app.focused, StationList)
        await pilot.resize_terminal(80, 24)
        await wait_for(pilot, lambda: isinstance(app.focused, DetailPane), "the detail pane takes the keyboard")
        await pilot.resize_terminal(120, 36)
        await wait_for(pilot, lambda: isinstance(app.focused, StationList), "the list gets the keyboard back")
        keys = await key_line(app, pilot)
        assert "d Remove" in keys and "esc Back" not in keys


async def test_a_pane_the_user_chose_keeps_the_keyboard_through_a_resize() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 36)) as pilot:
        await settle(pilot)
        await pilot.press("enter")
        await wait_for(pilot, lambda: isinstance(app.focused, DetailPane), "Enter moves into the detail")
        await pilot.resize_terminal(80, 24)
        await settle(pilot)
        await pilot.resize_terminal(120, 36)
        await settle(pilot)
        assert isinstance(app.focused, DetailPane)


# --- #253, #245, #230: a section key always shows something --------------------------------------------------------


async def test_a_station_without_a_taf_says_so_and_key_3_answers() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot)
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        app.state.stations["EGLL"].taf = None
        briefing.select("EGLL")
        await settle(pilot)
        pane = briefing.query_one(DetailPane)
        assert text_of(pane.query_one("#taf-note")) == app.ctx.translator.t(K.TIMELINE_NO_TAF)
        await pilot.press("3")
        await wait_for(pilot, lambda: app.ctx.translator.t(K.TIMELINE_NO_TAF) in toasts(app), "a toast for key 3")


async def test_keys_1_and_2_say_so_when_the_section_is_already_in_place() -> None:
    app = demo_app()
    async with app.run_test(size=(200, 160)) as pilot:  # tall enough that the pane has nothing to scroll
        await settle(pilot)
        pane = app.screen.query_one(DetailPane)
        assert pane.max_scroll_y == 0, "precondition: every section fits"
        t = app.ctx.translator
        await pilot.press("2")
        await wait_for(pilot, lambda: t.t(K.UI_TOAST_JUMP_SHOWN, section=t.t(K.UI_SECTION_DECODED)) in toasts(app), "2")
        await pilot.press("1")
        await wait_for(pilot, lambda: t.t(K.UI_TOAST_JUMP_SHOWN, section=t.t(K.UI_SECTION_RAW)) in toasts(app), "1")


async def test_a_key_that_scrolls_the_pane_needs_no_toast() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        pane = app.screen.query_one(DetailPane)
        await pilot.press("2")
        await wait_for(pilot, lambda: pane.scroll_y > 0, "the pane scrolls to Decoded")
        await settle(pilot)
        assert not any("already on screen" in message for message in toasts(app))


async def test_key_2_on_a_station_with_only_a_taf_names_the_missing_metar() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot)
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        entry = app.state.stations["EGLL"]
        entry.metar = None
        entry.awc_metar = None
        briefing.select("EGLL")
        await settle(pilot)
        await pilot.press("2")
        t = app.ctx.translator
        await wait_for(pilot, lambda: t.t(K.UI_DETAIL_NO_METAR) in toasts(app), "a toast naming the METAR")
        assert t.t(K.UI_DETAIL_NO_REPORT) not in toasts(app)  # a forecast is on screen: "No report yet" would be wrong


# --- #231: a dismissed toast can be raised again --------------------------------------------------------------------


async def test_a_dismissed_toast_is_shown_again_and_a_live_one_is_not_doubled() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        app.clear_notifications()
        app.notify("hello")
        app.notify("hello")
        await settle(pilot)
        assert toasts(app) == ["hello"]
        app.clear_notifications()
        await pilot.pause(app.TOAST_SETTLE + 0.1)
        app.notify("hello")
        await settle(pilot)
        assert toasts(app) == ["hello"]


# --- #232, #249: one click behaviour in both layouts ----------------------------------------------------------------


async def test_list_mouse_buttons_and_drag() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        stations = briefing.query_one(StationList)
        first = briefing.selected
        for button in (2, 3):  # middle and right
            await pilot.click(stations, offset=(3, 4), button=button)
            await settle(pilot)
            assert briefing.selected == first, f"button {button} changed the selection"
        # a drag: the button goes down on one row and comes up on another
        await pilot.mouse_down(stations, offset=(3, 2))
        await pilot._post_mouse_events([MouseUp, Click], stations, offset=(3, 4), button=1)
        await settle(pilot)
        assert briefing.selected == first, "a drag selected the row it ended on"
        await pilot.click(stations, offset=(3, 4))
        await settle(pilot)
        assert briefing.selected != first


async def test_grid_click_selects_and_double_click_opens_like_the_list() -> None:
    app = demo_app("--layout", "grid")
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot)
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        cards = list(briefing.query(StationCard))
        target = cards[1]
        await pilot.click(target, offset=(2, 1), button=2)
        await settle(pilot)
        assert briefing.selected == cards[0].icao, "a middle click selected a card"
        await pilot.click(target, offset=(2, 1))
        await settle(pilot)
        assert briefing.selected == target.icao
        await pilot.click(target, offset=(2, 1))  # another single click on the selected card no longer opens it
        await settle(pilot)
        assert isinstance(app.screen, BriefingScreen)
        assert isinstance(app.focused, StationGrid)
        await pilot.click(target, offset=(2, 1), times=2)
        await wait_for(pilot, lambda: isinstance(app.screen, StationDetailScreen), "a double click opens the detail")


# --- #233: the offline count starts again when the stations change ------------------------------------------------


def test_a_changed_station_list_restarts_the_offline_count() -> None:
    state = AppState(["KDEN"], [], None, lambda: datetime(2026, 11, 1, tzinfo=UTC))
    assert not state.record_error(Product.METAR, "x", offline=True)  # the first dropped connection is not shown
    state.add("KJFK", persist=False)
    assert not state.record_error(Product.METAR, "x", offline=True)  # counted again: still the first
    assert state.record_error(Product.METAR, "x", offline=True)  # the second in a row for the product
    state.remove("KJFK")
    assert state.transport_failures == {}
    assert not state.record_error(Product.METAR, "x", offline=True)


# --- #257: the demo header does not call fixed samples fresh -----------------------------------------------------


async def test_the_demo_header_names_no_age_and_no_freshness() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        header = text_of(app.screen.query_one(StationHeader))
        t = app.ctx.translator
        assert t.t(K.UI_DETAIL_DEMO_SAMPLE) in header
        assert "ago" not in header and t.t(K.UI_STATE_FRESH) not in header


# --- #198: the station header stays while the report scrolls -----------------------------------------------------


async def test_the_station_header_stays_at_the_top_while_the_pane_scrolls() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        pane = app.screen.query_one(DetailPane)
        header = pane.query_one(StationHeader)
        top = header.region
        await pilot.press("3")
        await wait_for(pilot, lambda: pane.scroll_y > 10, "the pane has scrolled well down")
        await settle(pilot)
        assert header.region == top and top.y == pane.region.y
        assert "KDEN" in text_of(header)


# --- #201: the grid has a key to its marks ---------------------------------------------------------------------


async def test_the_grid_shows_a_legend_for_hatching_and_the_temporary_row() -> None:
    app = demo_app("--layout", "grid")
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot)
        legend = app.screen.query_one("#legend")
        shown = text_of(legend)
        t = app.ctx.translator
        for key in (K.TIMELINE_LEGEND_BECOMING, K.TIMELINE_LEGEND_TEMPORARY, K.TIMELINE_LEGEND_WORST):
            assert t.t(key) in shown
        assert legend.region.bottom == app.screen.query_one(StationGrid).region.bottom


@pytest.mark.parametrize("size", [(140, 40), (200, 50)])
async def test_the_timeline_legend_names_the_cursor_when_there_is_room(size: tuple[int, int]) -> None:
    app = demo_app()
    async with app.run_test(size=size) as pilot:
        await settle(pilot)
        timeline = app.screen.query_one("#timeline")
        legend = timeline.render().plain.splitlines()[-1]  # type: ignore[attr-defined]
        assert app.ctx.translator.t(K.TIMELINE_LEGEND_CURSOR) in legend
