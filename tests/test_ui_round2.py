"""Station screen keys, help height in every language, grid reveal on resize, the timeline following the clock."""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from test_app_smoke import wait_for
from test_layout import screen_lines
from test_timeline_ui import demo_app, settle

from wxbrief.data.cache import CACHE_DIR_ENV
from wxbrief.i18n import LANGUAGES, Translator
from wxbrief.i18n.keys import K
from wxbrief.ui.screens.briefing import BriefingScreen
from wxbrief.ui.screens.help import HelpScreen
from wxbrief.ui.screens.station_detail import StationDetailScreen
from wxbrief.ui.widgets.detail import DecodedTable, DetailPane
from wxbrief.ui.widgets.station_card import StationCard
from wxbrief.ui.widgets.station_grid import StationGrid
from wxbrief.ui.widgets.taf_timeline import TafTimeline


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async def refuse(self: object, request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"network access in a test: {request.url}")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", refuse)
    monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path / "cache"))


@pytest.mark.parametrize("size", [(60, 16), (120, 30)])
@pytest.mark.parametrize("lang", LANGUAGES)
async def test_the_help_reaches_its_last_row_in_every_language(lang: str, size: tuple[int, int]) -> None:
    app = demo_app("--lang", lang)
    last = re.sub(r"\[/?b\]", "", Translator.load(lang).t(K.UI_HELP_BODY).splitlines()[-1]).split()[-1]
    async with app.run_test(size=size) as pilot:
        await settle(pilot)
        await pilot.press("question_mark")
        await settle(pilot)
        assert isinstance(app.screen, HelpScreen)
        await pilot.press("end")
        await settle(pilot)
        assert last in "\n".join(screen_lines(app)), f"{lang} {size}: the last help row is clipped"


async def test_refresh_and_help_work_on_a_stations_own_screen(monkeypatch: pytest.MonkeyPatch) -> None:
    app = demo_app("--layout", "grid")
    asked: list[bool] = []
    monkeypatch.setattr(type(app), "refresh_now", lambda self: asked.append(True))
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot)
        await pilot.press("enter")
        await settle(pilot)
        assert isinstance(app.screen, StationDetailScreen)
        await pilot.press("r")
        assert asked == [True]
        await pilot.press("question_mark")
        await settle(pilot)
        assert isinstance(app.screen, HelpScreen)


async def test_a_resize_keeps_the_selected_card_in_view() -> None:
    app = demo_app("--layout", "grid")
    async with app.run_test(size=(200, 50)) as pilot:
        await settle(pilot)
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        grid = briefing.query_one(StationGrid)
        for _ in range(len(grid.ids)):
            await pilot.press("right")
        await settle(pilot)
        for size in ((60, 16), (200, 50), (80, 24)):
            await pilot.resize_terminal(*size)

            def settled() -> bool:  # laid out for this size, the reveal finished, and the card inside the grid
                card = next(c for c in grid.query(StationCard) if c.icao == grid.selected)
                return (
                    grid._laid_out_columns == grid.columns
                    and grid._to_reveal is None
                    and grid.region.contains_region(card.region)
                )

            await wait_for(pilot, settled, f"{size}: the selected card in view")


async def test_the_decoded_table_hands_back_focus_when_it_is_hidden() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 50)) as pilot:
        await settle(pilot)
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        table = briefing.query_one(DecodedTable)
        table.focus()
        await settle(pilot)
        assert table.has_focus
        app.state.stations["KDEN"].metar = None
        briefing.refresh_view()
        await settle(pilot)
        assert not table.display and not table.has_focus
        assert briefing.focused is briefing.query_one(DetailPane)  # the pane, not nowhere and not the timeline


async def test_the_timeline_cursor_follows_the_clock_until_the_user_moves_it() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 50)) as pilot:
        await settle(pilot)
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        briefing.select("EGLL")
        await settle(pilot)
        timeline = briefing.query_one(TafTimeline)
        taf, ctx, now = timeline.taf, timeline._ctx, app.now()
        assert taf is not None and ctx is not None
        assert timeline.cursor == 0
        timeline.set_taf(taf, ctx, "EGLL", now + timedelta(hours=5))  # the same TAF, five hours on
        assert timeline.cursor == 5
        timeline.move_to(2)  # the user's choice stands
        timeline.set_taf(taf, ctx, "EGLL", now + timedelta(hours=8))
        assert timeline.cursor == 2
