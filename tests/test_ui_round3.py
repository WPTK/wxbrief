"""Round 3 UI findings: hover versus the clock, the list after a resize, the keys and focus of the detail pane."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from test_app_smoke import wait_for
from test_timeline_ui import demo_app, settle

from wxbrief.data.cache import CACHE_DIR_ENV
from wxbrief.ui.screens.briefing import BriefingScreen
from wxbrief.ui.widgets.detail import DetailPane
from wxbrief.ui.widgets.station_list import StationList
from wxbrief.ui.widgets.taf_timeline import TafTimeline


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async def refuse(self: object, request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"network access in a test: {request.url}")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", refuse)
    monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path / "cache"))


async def test_a_hover_does_not_stop_the_cursor_following_the_clock() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 50)) as pilot:
        await settle(pilot)
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        briefing.select("EGLL")
        await settle(pilot)
        timeline = briefing.query_one(TafTimeline)
        timeline.scroll_visible(animate=False)
        await settle(pilot)
        taf, ctx, now = timeline.taf, timeline._ctx, app.now()
        assert taf is not None and ctx is not None
        await pilot.hover(TafTimeline, offset=(2 * 9 + 1, 1))
        await settle(pilot)
        assert timeline.cursor == 9  # the hover previews that hour
        timeline.set_taf(taf, ctx, "EGLL", now + timedelta(hours=5))  # the clock moves on
        assert timeline.cursor == 5
        await pilot.click(TafTimeline, offset=(2 * 9 + 1, 1))  # a click is a choice, and stands
        await settle(pilot)
        timeline.set_taf(taf, ctx, "EGLL", now + timedelta(hours=7))
        assert timeline.cursor == 9


async def test_left_and_right_in_the_detail_pane_move_the_forecast_cursor() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 50)) as pilot:
        await settle(pilot)
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        briefing.select("EGLL")
        await settle(pilot)
        pane = briefing.query_one(DetailPane)
        timeline = briefing.query_one(TafTimeline)
        pane.focus()
        await settle(pilot)
        before = timeline.cursor
        await pilot.press("right", "right")
        assert timeline.cursor == before + 2
        await pilot.press("left")
        assert timeline.cursor == before + 1


async def test_a_station_change_takes_focus_off_the_timeline() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 50)) as pilot:
        await settle(pilot)
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        briefing.select("KDEN")
        await settle(pilot)
        timeline = briefing.query_one(TafTimeline)
        timeline.focus()
        await settle(pilot)
        assert timeline.has_focus
        briefing.select("EGLL")
        await settle(pilot)
        assert briefing.focused is briefing.query_one(DetailPane)


async def test_removing_the_last_station_leaves_focus_on_the_pane() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 50)) as pilot:
        await settle(pilot)
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        briefing.select("KDEN")
        await settle(pilot)
        timeline = briefing.query_one(TafTimeline)
        timeline.focus()
        await settle(pilot)
        assert timeline.has_focus
        for icao in list(app.state.ids):
            app.state.remove(icao)
        briefing.refresh_view()  # the pane has nothing to show; it must not be left with focus on nothing
        await settle(pilot)
        assert briefing.focused is briefing.query_one(DetailPane)


async def test_a_shorter_terminal_keeps_the_selected_station_in_the_list() -> None:
    app = demo_app()
    async with app.run_test(size=(140, 50)) as pilot:
        await settle(pilot)
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        stations = briefing.query_one(StationList)
        last = stations.option_count - 1
        briefing.select(app.state.ids[-1])
        await settle(pilot)
        assert stations.highlighted == last
        await pilot.resize_terminal(140, 10)

        def in_view() -> bool:
            line = stations._index_to_line.get(last)
            top = stations.scroll_offset.y
            return line is not None and top <= line < top + stations.scrollable_content_region.height

        await wait_for(pilot, in_view, "the selected station in view")
