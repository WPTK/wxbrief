"""Round 4 UI findings: a cancelled TAF, click and hover on the timeline, removal and resize, the keys of the pane."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from test_app_smoke import wait_for
from test_layout import key_line
from test_timeline_ui import demo_app, settle, text_of

from wxbrief.data.cache import CACHE_DIR_ENV
from wxbrief.decode.model import Modifier
from wxbrief.decode.taf import parse_taf
from wxbrief.ui.screens.briefing import BriefingScreen
from wxbrief.ui.screens.station_detail import StationDetailScreen
from wxbrief.ui.strip import strip_for
from wxbrief.ui.widgets.detail import DetailPane
from wxbrief.ui.widgets.period_detail import PeriodDetail
from wxbrief.ui.widgets.station_card import StationCard
from wxbrief.ui.widgets.station_grid import StationGrid
from wxbrief.ui.widgets.station_list import StationList
from wxbrief.ui.widgets.taf_timeline import TafTimeline


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async def refuse(self: object, request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"network access in a test: {request.url}")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", refuse)
    monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path / "cache"))


REF = datetime(2026, 10, 31, 11, 0, tzinfo=UTC)

# --- a cancelled TAF ----------------------------------------------------------------------------------------------------


def test_a_cancelled_taf_has_no_hours_to_draw() -> None:
    bare = parse_taf("TAF AMD LFPG 311000Z 3110/3118 CNL", REF)  # the repo's own fixture: a window and no groups
    assert bare.cancelled and strip_for(bare)[1] == ()
    body = parse_taf("TAF KDEN 311100Z 3112/0118 32005KT 1/4SM FG VV001", REF)
    assert strip_for(body)[1] != ()
    withdrawn = replace(body, modifiers=(Modifier.CNL,))  # a feed row whose remarks say CNL over a full forecast body
    assert strip_for(withdrawn)[1] == ()


@pytest.mark.parametrize("bare", [True, False])
async def test_the_card_says_a_cancelled_taf_is_cancelled(bare: bool) -> None:
    app = demo_app("--layout", "grid")
    async with app.run_test(size=(140, 40)) as pilot:
        await settle(pilot)
        entry = app.state.stations["KDEN"]
        assert entry.taf is not None
        entry.taf = (
            parse_taf("TAF AMD KDEN 311100Z 3112/0118 CNL", REF) if bare else replace(entry.taf, modifiers=(Modifier.CNL,))
        )
        app.screen.refresh_view()  # type: ignore[attr-defined]
        await settle(pilot)
        shown = text_of(next(c for c in app.screen.query(StationCard) if c.icao == "KDEN"))
        assert "TAF cancelled" in shown and "no TAF" not in shown
        assert len(shown.splitlines()) == 3  # head, conditions and the note: no colour strip


async def test_the_detail_pane_draws_no_timeline_for_a_cancelled_taf() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 50)) as pilot:
        await settle(pilot)
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        entry = app.state.stations["KDEN"]
        assert entry.taf is not None
        entry.taf = replace(entry.taf, modifiers=(Modifier.CNL,))
        briefing.refresh_view()
        await settle(pilot)
        pane = briefing.query_one(DetailPane)
        assert not briefing.query_one(TafTimeline).display and not briefing.query_one(PeriodDetail).display
        assert "TAF cancelled" in text_of(pane.query_one("#taf-note"))


# --- hover and click on the timeline ------------------------------------------------------------------------------------


async def timeline_on(app: object, pilot: object) -> tuple[TafTimeline, object, object, object]:
    await settle(pilot)
    briefing = app.screen  # type: ignore[attr-defined]
    briefing.select("EGLL")
    await settle(pilot)
    timeline = briefing.query_one(TafTimeline)
    timeline.scroll_visible(animate=False)
    await settle(pilot)
    assert timeline.taf is not None and timeline._ctx is not None
    return timeline, timeline.taf, timeline._ctx, app.now()  # type: ignore[attr-defined]


async def test_a_click_on_the_cell_the_pointer_is_already_on_is_a_choice() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 50)) as pilot:
        timeline, taf, ctx, now = await timeline_on(app, pilot)
        cell = (2 * 9 + 1, 1)
        await pilot.hover(TafTimeline, offset=cell)  # a real pointer moves before it presses
        await settle(pilot)
        assert timeline.cursor == 9
        await pilot.click(TafTimeline, offset=cell)
        await settle(pilot)
        timeline.set_taf(taf, ctx, "EGLL", now + timedelta(hours=5))  # the 30 s redraw, later in the day
        assert timeline.cursor == 9


async def test_a_hover_does_not_replace_a_chosen_hour() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 50)) as pilot:
        timeline, taf, ctx, now = await timeline_on(app, pilot)
        timeline.focus()
        before = timeline.cursor
        await pilot.press("right", "right", "right")
        assert timeline.cursor == before + 3
        await pilot.hover(TafTimeline, offset=(2 * 14 + 1, 1))  # the pointer crosses the strip and stops
        await settle(pilot)
        assert timeline.cursor == 14  # previewed
        timeline.set_taf(taf, ctx, "EGLL", now)  # the next redraw
        assert timeline.cursor == before + 3  # the chosen hour is back


# --- removal ------------------------------------------------------------------------------------------------------------


async def test_removing_a_station_selects_the_one_that_takes_its_place() -> None:
    app = demo_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await settle(pilot)
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        ids = list(app.state.ids)
        briefing.select(ids[4])
        await settle(pilot)
        app.remove_station(ids[4])
        await settle(pilot)
        assert briefing.selected == ids[5]
        assert briefing.query_one(StationList).highlighted == 4
        app.remove_station(ids[5])
        await settle(pilot)
        assert briefing.selected == ids[6]  # a second d takes the next row, not the first
        briefing.select(ids[-1])
        await settle(pilot)
        app.remove_station(ids[-1])
        await settle(pilot)
        assert briefing.selected == ids[-2]  # the last row went: the one above it


# --- a resize that only changes the height ------------------------------------------------------------------------------


async def test_a_height_only_resize_keeps_the_selected_card_in_view() -> None:
    app = demo_app("--layout", "grid")
    async with app.run_test(size=(200, 39)) as pilot:
        await settle(pilot)
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        for n in range(30):
            app.state.add(f"K{n // 10}X{n % 10}"[:4], persist=False)
        briefing.refresh_view()
        await settle(pilot)
        grid = briefing.query_one(StationGrid)
        last = grid.ids[-1]
        assert len(grid.ids) == 40
        briefing.select(last)
        await settle(pilot)

        def in_view() -> bool:
            card = next(c for c in grid.query(StationCard) if c.icao == grid.selected)
            return grid._to_reveal is None and grid.region.contains_region(card.region)

        await wait_for(pilot, in_view, "the last row in view at 200x39")
        columns = grid.columns
        await pilot.resize_terminal(200, 24)  # the same width, so the same columns: only the height shrinks
        assert grid.columns == columns
        await wait_for(pilot, in_view, "the last row in view at 200x24")


# --- the keys of the detail pane and the key bar ------------------------------------------------------------------------


@pytest.mark.parametrize("size", [(80, 24), (60, 16)])
async def test_left_and_right_show_the_forecast_they_move(size: tuple[int, int]) -> None:
    app = demo_app()
    async with app.run_test(size=size) as pilot:
        await settle(pilot)
        await pilot.press("v", "enter")
        await wait_for(pilot, lambda: isinstance(app.screen, StationDetailScreen), "the station screen")
        await settle(pilot)
        pane = app.screen.query_one(DetailPane)
        timeline = pane.query_one(TafTimeline)
        pane.focus()
        await settle(pilot)
        await pilot.press("right", "right")
        await settle(pilot)
        assert pane.region.contains_region(timeline.region), (pane.region, timeline.region)


@pytest.mark.parametrize("size", [(60, 16), (70, 20)])
async def test_the_station_screen_keeps_back_help_and_quit(size: tuple[int, int]) -> None:
    app = demo_app()
    async with app.run_test(size=size) as pilot:
        await settle(pilot)
        await pilot.press("v", "enter")
        await wait_for(pilot, lambda: isinstance(app.screen, StationDetailScreen), "the station screen")
        last = await key_line(app, pilot)
        assert "esc Back" in last and "? Help" in last and "q Quit" in last, last
