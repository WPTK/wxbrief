"""(c) Focus graph, keyboard reachability and the Ctrl+P command palette."""

from __future__ import annotations

import pytest
from ux_kit import briefing, load, make_app, rows

from wxbrief.ui.screens.help import HelpScreen
from wxbrief.ui.widgets.detail import DetailPane
from wxbrief.ui.widgets.station_grid import StationGrid
from wxbrief.ui.widgets.station_list import StationList
from wxbrief.ui.widgets.taf_timeline import TafTimeline


async def _loaded(app, pilot):  # type: ignore[no-untyped-def]
    load(app, rows("metar_kden_egll"), rows("taf_kden_egll"))
    await pilot.pause()


async def test_tab_cycle_is_closed_and_visits_every_interactive_region(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = make_app(tmp_path, ["KDEN", "EGLL"])
    async with app.run_test(size=(120, 40)) as pilot:
        await _loaded(app, pilot)
        order = []
        for _ in range(14):
            order.append(type(app.focused).__name__)
            await pilot.press("tab")
            await pilot.pause()
        assert order[0] == "StationList"
        assert {"StationList", "DetailPane", "TafTimeline"} <= set(order)
        period = order[1:].index("StationList") + 1
        assert order[:period] == order[period : 2 * period]  # the cycle repeats: no trap, no dead end


async def test_shift_tab_is_the_reverse_of_tab(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = make_app(tmp_path, ["KDEN", "EGLL"])
    async with app.run_test(size=(120, 40)) as pilot:
        await _loaded(app, pilot)
        forward = []
        for _ in range(4):
            await pilot.press("tab")
            forward.append(app.focused)
        for expected in reversed(forward[:-1]):
            await pilot.press("shift+tab")
            assert app.focused is expected


async def test_help_opens_from_every_focus_stop_and_restores_focus(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = make_app(tmp_path, ["KDEN", "EGLL"])
    async with app.run_test(size=(120, 40)) as pilot:
        await _loaded(app, pilot)
        for _ in range(5):
            stop = app.focused
            await pilot.press("question_mark")
            await pilot.pause()
            assert isinstance(app.screen, HelpScreen), type(stop).__name__
            await pilot.press("escape")
            await pilot.pause()
            assert app.focused is stop
            await pilot.press("tab")
            await pilot.pause()


async def test_grid_layout_focus_is_the_grid_and_toggle_returns_to_the_list(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = make_app(tmp_path, ["KDEN", "EGLL"])
    async with app.run_test(size=(120, 40)) as pilot:
        await _loaded(app, pilot)
        await pilot.press("v")
        await pilot.pause(0.2)
        assert isinstance(app.focused, StationGrid)
        for _ in range(3):
            await pilot.press("tab")
            await pilot.pause()
        await pilot.press("v")
        await pilot.pause(0.2)
        assert isinstance(app.focused, StationList)


async def test_escape_from_detail_returns_to_list(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = make_app(tmp_path, ["KDEN", "EGLL"])
    async with app.run_test(size=(120, 40)) as pilot:
        await _loaded(app, pilot)
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.focused, DetailPane)
        await pilot.press("3")
        await pilot.pause()
        assert isinstance(app.focused, TafTimeline)
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.focused, StationList)
        assert briefing(app).selected == "KDEN"


async def test_command_palette_opens_and_closes_with_focus_restored(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = make_app(tmp_path, ["KDEN", "EGLL"])
    async with app.run_test(size=(120, 40)) as pilot:
        await _loaded(app, pilot)
        before = app.focused
        await pilot.press("ctrl+p")
        await pilot.pause()
        assert type(app.screen).__name__ == "CommandPalette"
        await pilot.press("escape")
        await pilot.pause()
        assert app.focused is before


@pytest.mark.xfail(strict=True, reason="UX-06")
async def test_command_palette_offers_the_apps_own_commands(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Today the palette lists only Textual's defaults: Theme, Quit, Keys, Maximize, Screenshot."""
    app = make_app(tmp_path, ["KDEN", "EGLL"])
    async with app.run_test(size=(120, 40)) as pilot:
        await _loaded(app, pilot)
        titles = " | ".join(c.title.lower() for c in app.get_system_commands(app.screen))
        missing = [w for w in ("add station", "refresh", "settings", "paste", "help") if w not in titles]
        assert not missing, (missing, titles)
