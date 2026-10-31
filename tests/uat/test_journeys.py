"""User journeys through the real app, key by key, on the bundled demo reports (``--demo``), fully offline."""

from __future__ import annotations

from rich.text import Text
from test_timeline_ui import demo_app
from textual.widgets import Footer

from wxbrief.ui.screens.add_station import AddStationScreen
from wxbrief.ui.screens.briefing import BriefingScreen
from wxbrief.ui.screens.help import HelpScreen
from wxbrief.ui.screens.paste import PasteDecodeScreen
from wxbrief.ui.screens.settings import SettingsScreen
from wxbrief.ui.screens.station_detail import StationDetailScreen
from wxbrief.ui.widgets.detail import DecodedTable, DetailPane, StationHeader
from wxbrief.ui.widgets.period_detail import PeriodDetail
from wxbrief.ui.widgets.station_list import StationList
from wxbrief.ui.widgets.taf_timeline import HATCH, OVERLAY_MARK, TafTimeline


def plain(widget: object) -> str:
    content = widget.render()  # type: ignore[attr-defined]
    return content.plain if isinstance(content, Text) else str(content)


def decoded_text(screen: object) -> str:
    table = screen.query_one(DecodedTable)  # type: ignore[attr-defined]
    return "\n".join(str(cell) for i in range(table.row_count) for cell in table.get_row_at(i))


async def test_first_look_read_copy_and_leave(copied: list[str]) -> None:
    """Open the demo, read the first station, jump through the sections, copy it, ask for help, quit."""
    app = demo_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        screen = app.screen
        assert isinstance(screen, BriefingScreen) and screen.selected == "KDEN"
        assert "KDEN" in plain(screen.query_one(StationHeader))
        await pilot.press("2", "3")
        assert screen.query_one(TafTimeline).has_focus
        await pilot.press("right")
        assert plain(screen.query_one(PeriodDetail)) != ""
        await pilot.press("c")
        assert copied and copied[-1].startswith("```") and "KDEN" in copied[-1]
        await pilot.press("question_mark")
        assert isinstance(app.screen, HelpScreen)
        await pilot.press("escape")
        await pilot.press("q")


async def test_walk_the_list_and_open_the_dialogs() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        screen = app.screen
        assert isinstance(screen, BriefingScreen)
        await pilot.press("j", "j")
        assert screen.selected == "ETHB"
        await pilot.press("k")
        assert screen.selected == "EGLL"
        for key, dialog in (("a", AddStationScreen), ("p", PasteDecodeScreen), ("S", SettingsScreen)):
            await pilot.press(key)
            assert isinstance(app.screen, dialog)
            await pilot.press("escape")
            assert app.screen is screen


async def test_change_the_view_with_g_u_z_and_see_it_in_the_report() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        screen = app.screen
        assert isinstance(screen, BriefingScreen)
        assert "kt (" in decoded_text(screen)  # mixed: knots, then km/h
        await pilot.press("u")  # us
        assert "km/h" not in decoded_text(screen)
        await pilot.press("z", "z")  # local, then zulu
        await pilot.pause(0.2)
        assert "Z" in plain(screen.query_one(StationHeader)).split("\n")[1]
        await pilot.press("g")
        assert app.ctx.glyphs.fresh != "●"


async def test_grid_open_a_station_and_come_back() -> None:
    app = demo_app("--layout", "grid")
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause(0.3)
        await pilot.press("right", "enter")
        await pilot.pause(0.2)
        assert isinstance(app.screen, StationDetailScreen)
        pane = app.screen.query_one(DetailPane)
        assert pane.scroll_y == 0  # opens on the station header
        await pilot.press("3")
        await pilot.press("escape")
        assert isinstance(app.screen, BriefingScreen)


async def test_a_60x20_terminal_stays_usable() -> None:
    app = demo_app()
    async with app.run_test(size=(60, 20)) as pilot:
        await pilot.pause(0.3)
        screen = app.screen
        assert isinstance(screen, BriefingScreen)
        assert not screen.query_one(StationList).display  # the list gives way to the detail
        assert "KDEN" in plain(screen.query_one(StationHeader))
        await pilot.press("j")
        assert "EGLL" in plain(screen.query_one(StationHeader))
        assert screen.query_one(Footer).compact
        await pilot.press("3")
        assert screen.query_one(TafTimeline).has_focus
        await pilot.press("v")
        await pilot.pause(0.2)
        assert screen.layout_mode == "grid"
        assert app.screen.size.width == 60


async def test_timeline_markers_differ_without_colour_or_unicode_glyphs() -> None:
    """With NO_COLOR and the ascii glyph set, a becoming cell and a temporary mark are still different characters."""
    import os

    os.environ["NO_COLOR"] = "1"
    try:
        app = demo_app("--glyphs", "ascii")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.2)
            await pilot.press("3")
            await pilot.pause(0.2)
            timeline = app.screen.query_one(TafTimeline)
            text = plain(timeline)
            assert HATCH != OVERLAY_MARK
            assert HATCH in text and OVERLAY_MARK in text  # both in the legend, and each on its own row
            assert f"{HATCH} " in text and f"{OVERLAY_MARK} " in text
    finally:
        os.environ.pop("NO_COLOR", None)
