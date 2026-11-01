"""First-user polish: the list fills its column, the copy toast shows, key hints, small dialogs, paste, one no-report phrase."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from test_footer import shown
from test_layout import key_line, screen_lines
from test_timeline_ui import demo_app, settle, text_of
from textual.widgets import Input, TextArea
from textual.widgets._toast import Toast

from wxbrief import clipboard
from wxbrief.data.cache import CACHE_DIR_ENV
from wxbrief.i18n import Translator
from wxbrief.ui.screens.paste import PasteDecodeScreen
from wxbrief.ui.widgets.detail import StationHeader
from wxbrief.ui.widgets.station_list import StationList
from wxbrief.ui.widgets.status_bar import StatusBar
from wxbrief.ui.widgets.taf_timeline import TafTimeline


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async def refuse(self: object, request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"network access in a test: {request.url}")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", refuse)
    monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path / "cache"))
    monkeypatch.setattr(clipboard, "_pyperclip_copy", lambda text: None)


@pytest.mark.parametrize("size", [(120, 30), (280, 70)])
async def test_the_station_list_box_runs_the_height_of_its_column(size: tuple[int, int]) -> None:
    app = demo_app()
    async with app.run_test(size=size) as pilot:
        await settle(pilot)
        listing = app.screen.query_one(StationList).region
        main = app.screen.query_one("#main").region
        assert listing.height == main.height  # not just as tall as its ten rows
        assert app.screen.query_one("#detail").region.height == main.height


@pytest.mark.parametrize("size", [(120, 30), (60, 16)])
async def test_the_copy_confirmation_is_one_visible_row_on_the_status_bar(size: tuple[int, int]) -> None:
    app = demo_app()
    async with app.run_test(size=size, notifications=True) as pilot:
        await settle(pilot)
        app.clear_notifications()
        await settle(pilot)
        await pilot.press("c")
        await pilot.pause(0.3)
        toasts = list(app.screen.query(Toast))
        assert len(toasts) == 1
        assert toasts[0].region.height == 1  # a title would make it two rows over the report text
        status = app.screen.query_one(StatusBar).region
        assert toasts[0].region.y == status.y
        assert "Copied KDEN METAR" in screen_lines(app)[status.y]


async def test_the_timeline_cursor_keys_show_on_the_key_bar_when_there_is_room() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("enter", "3")
        assert isinstance(app.focused, TafTimeline)
        assert "left" in shown(app) and "right" not in shown(app)
        assert "←/→ Move" in await key_line(app, pilot)


async def test_a_tight_key_bar_keeps_add_and_list_grid_before_the_section_keys() -> None:
    app = demo_app()
    async with app.run_test(size=(60, 16)) as pilot:
        await settle(pilot)
        line = await key_line(app, pilot)
        assert "a Add" in line and "v List/grid" in line and "? Help" in line and "q Quit" in line
        assert "1 Raw" not in line and "←/→" not in line


async def test_settings_is_only_what_enter_changes_and_fits_60x16() -> None:
    app = demo_app()
    async with app.run_test(size=(60, 16)) as pilot:
        await settle(pilot)
        await pilot.press("S")
        await settle(pilot)
        text = "\n".join(screen_lines(app))
        for label in ("Poll", "Config file", "Cache folder", "Theme:", "Layout:"):
            assert label not in text
        assert "Settings" in text and "Language:" in text and "Glyphs:" in text
        assert "Enter changes the value, Esc closes" in text  # the hint is on one row, whole
        assert app.screen.query_one("#settings-hint").region.y == app.screen.query_one("#settings-options").region.bottom


async def test_the_add_and_theme_hints_fit_60x16() -> None:
    app = demo_app()
    async with app.run_test(size=(60, 16)) as pilot:
        await settle(pilot)
        await pilot.press("a", "k", "s", "e", "a")
        await settle(pilot)
        assert "Esc cancels" in "\n".join(screen_lines(app)) and "Enter adds" in "\n".join(screen_lines(app))
        results = app.screen.query_one("#results").region
        hint = app.screen.query_one(".hint").region
        assert hint.y == results.bottom  # no blank rows between the matches and the hint
        await pilot.press("escape", "T")
        await settle(pilot)
        assert "Enter keeps, Esc cancels" in "\n".join(screen_lines(app))


@pytest.mark.parametrize("lang", ["en", "de", "es", "fr", "pt"])
def test_dialog_hints_are_one_row_at_60_columns(lang: str) -> None:
    t = Translator.load(lang)
    for key in ("ui.add.hint", "ui.themes.hint", "ui.settings.hint"):
        assert len(t.t(key)) <= 46, (lang, key)  # the dialog is 54 wide with 6 columns of border and padding


async def test_paste_leads_with_the_instruction_and_keeps_the_date_below_the_box() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        await pilot.press("p")
        await settle(pilot)
        assert isinstance(app.screen, PasteDecodeScreen)
        box = app.screen.query_one(TextArea)
        date = app.screen.query_one("#reference", Input)
        assert box.region.y == 0 and box.region.bottom <= date.region.y
        assert "Paste a METAR or TAF here" in box.placeholder
        assert "Paste a METAR or TAF here" in screen_lines(app)[0] + screen_lines(app)[1]
        assert "Reference date" not in "\n".join(screen_lines(app)[:3])


async def test_a_station_without_a_report_says_no_report_yet_everywhere() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        assert app.state.add("KXXX", persist=False)
        app.briefing.select("KXXX")
        await settle(pilot)
        header = text_of(app.screen.query_one(StationHeader))
        assert "No report yet" in header and "r to refresh" in header
        lines = screen_lines(app)
        assert any("KXXX" in line and "No report yet" in line for line in lines)  # the list row
        assert "No report yet" in text_of(app.screen.query_one(StatusBar))
        for gone in ("no data", "no report", "No METAR available"):
            assert gone not in "\n".join(lines)
