"""Layout at the sizes people use: cards, hanging indents, the key bar, dialogs and the too-small notice."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from test_timeline_ui import demo_app

from wxbrief.data.cache import CACHE_DIR_ENV
from wxbrief.ui.screens.add_station import AddStationScreen
from wxbrief.ui.screens.briefing import BriefingScreen
from wxbrief.ui.screens.too_small import TooSmallScreen
from wxbrief.ui.widgets.key_bar import KeyBar
from wxbrief.ui.widgets.station_card import StationCard
from wxbrief.ui.widgets.station_list import StationList
from wxbrief.ui.widgets.status_bar import StatusBar


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async def refuse(self: object, request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"network access in a test: {request.url}")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", refuse)
    monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path / "cache"))


async def key_line(app: object, pilot: object) -> str:
    """The bottom row once the key bar has drawn (it is recomposed after the first layout pass)."""
    for _ in range(40):
        await pilot.pause(0.05)  # type: ignore[attr-defined]
        if screen_lines(app)[-1].strip():
            break
    return screen_lines(app)[-1]


def screen_lines(app: object) -> list[str]:
    strips = app.screen._compositor.render_strips()  # type: ignore[attr-defined]
    return ["".join(segment.text for segment in strip).rstrip() for strip in strips]


@pytest.mark.parametrize("size", [(80, 24), (120, 30), (200, 50)])
async def test_a_card_keeps_all_its_rows(size: tuple[int, int]) -> None:
    """A long station name is cut with an ellipsis; it never wraps and pushes the strip out of the card."""
    app = demo_app("--layout", "grid")
    async with app.run_test(size=size) as pilot:
        await pilot.pause(0.2)
        cards = list(app.screen.query(StationCard))
        assert len(cards) == 10
        for card in cards:
            assert card.get_content_height(card.size, card.size, card.content_size.width) <= card.content_size.height, card.icao


async def test_taf_header_values_wrap_under_their_value_column() -> None:
    app = demo_app()
    async with app.run_test(size=(200, 50)) as pilot:
        await pilot.pause(0.3)
        await pilot.press("3")
        await pilot.pause(0.2)
        valid = next(line for line in screen_lines(app) if "Valid:" in line)
        assert valid.endswith("18:00 UTC")  # the whole sentence on one line, UTC not left behind
    app = demo_app()
    async with app.run_test(size=(100, 50)) as pilot:  # a narrower pane: the value wraps and hangs
        await pilot.pause(0.3)
        await pilot.press("3")
        await pilot.pause(0.2)
        lines = screen_lines(app)
        valid = next(i for i, line in enumerate(lines) if "Valid:" in line)
        column = lines[valid].index("2026-10-31 12:00")
        assert lines[valid + 1][column:].startswith("2026-11-01 18:00 UTC")  # the end stamp wraps whole


@pytest.mark.parametrize("size", [(60, 16), (80, 24)])
async def test_the_key_bar_keeps_help_and_quit(size: tuple[int, int]) -> None:
    app = demo_app()
    async with app.run_test(size=size) as pilot:
        await pilot.pause(0.3)
        last = await key_line(app, pilot)
        assert "? Help" in last and "q Quit" in last
        keys = [key for key in app.screen.query_one(KeyBar).children if key.display]
        assert all(key.region.right <= size[0] for key in keys)  # no label cut by the edge


async def test_the_status_bar_says_which_station_and_j_k_are_in_the_key_bar_when_the_list_is_hidden() -> None:
    app = demo_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause(0.3)
        assert not app.screen.query_one(StationList).display
        await pilot.pause(0.3)
        assert screen_lines(app)[-2].lstrip().startswith("1/10")
        assert "j/k" in await key_line(app, pilot)
        await pilot.press("j")
        assert screen_lines(app)[-2].lstrip().startswith("2/10")
        await pilot.resize_terminal(120, 30)
        await pilot.pause(0.2)
        assert "j/k" not in await key_line(app, pilot)
        assert app.screen.query_one(StatusBar)


async def test_a_wide_terminal_widens_the_list_and_caps_the_report() -> None:
    app = demo_app()
    async with app.run_test(size=(280, 70)) as pilot:
        await pilot.pause(0.3)
        station_list = app.screen.query_one(StationList)
        assert 38 < station_list.outer_size.width <= 56
        assert "Denver Intl" in screen_lines(app)[1]  # the row carries the station name when there is room
        raw = app.screen.query_one("#raw")
        assert raw.outer_size.width <= 110


async def test_a_wrapped_help_line_hangs_under_its_description() -> None:
    app = demo_app()
    async with app.run_test(size=(60, 40)) as pilot:
        await pilot.pause(0.3)
        await pilot.press("question_mark")
        await pilot.pause(0.3)
        lines = screen_lines(app)
        first = next(line for line in lines if "Left/Right" in line)
        wrapped = next(line for line in lines if "mouse works too)" in line)
        assert wrapped.index("mouse") == first.index("move the")


async def test_add_station_keeps_a_result_row_and_its_hint_at_60x16() -> None:
    app = demo_app()
    async with app.run_test(size=(60, 16)) as pilot:
        await pilot.pause(0.3)
        await pilot.press("a", "k", "s", "e", "a")
        await pilot.pause(0.3)
        assert isinstance(app.screen, AddStationScreen)
        lines = "\n".join(screen_lines(app))
        assert "KSEA" in lines
        assert "Esc" in lines  # the hint wraps inside the dialog instead of being cut


async def test_settings_rows_stay_on_one_line_at_60x16() -> None:
    app = demo_app("--lang", "de")
    async with app.run_test(size=(60, 16)) as pilot:
        await pilot.pause(0.3)
        await pilot.press("S")
        await pilot.pause(0.3)
        rows = [line for line in screen_lines(app) if "Sprache:" in line or "Einheiten:" in line]
        assert any("Deutsch" in row for row in rows)
        assert any(row.count("Einheiten:") and "…" in row for row in rows) or len(rows) == 2


async def test_a_terminal_below_60x16_shows_the_notice_and_the_app_returns_when_it_grows() -> None:
    app = demo_app()
    async with app.run_test(size=(30, 10)) as pilot:
        await pilot.pause(0.3)
        assert isinstance(app.screen, TooSmallScreen)
        assert "too small" in "\n".join(screen_lines(app))
        await pilot.press("a")  # keys do not reach the dialogs under the notice
        assert isinstance(app.screen, TooSmallScreen)
        await pilot.resize_terminal(80, 24)
        await pilot.pause(0.3)
        assert isinstance(app.screen, BriefingScreen)
        await pilot.press("a")
        assert isinstance(app.screen, AddStationScreen)
        await pilot.resize_terminal(55, 14)
        await pilot.pause(0.3)
        assert isinstance(app.screen, TooSmallScreen)
        await pilot.resize_terminal(80, 24)
        await pilot.pause(0.3)
        assert isinstance(app.screen, AddStationScreen)


async def test_q_quits_from_the_notice() -> None:
    app = demo_app()
    async with app.run_test(size=(50, 14)) as pilot:
        await pilot.pause(0.3)
        assert isinstance(app.screen, TooSmallScreen)
        await pilot.press("q")
        await pilot.pause(0.2)
        assert not app.is_running


async def test_the_notice_goes_when_the_palette_was_opened_over_it() -> None:
    app = demo_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause(0.3)
        await pilot.resize_terminal(50, 14)
        await pilot.pause(0.3)
        assert isinstance(app.screen, TooSmallScreen)
        await pilot.press("ctrl+p")
        await pilot.pause(0.3)
        assert not isinstance(app.screen, TooSmallScreen)
        await pilot.resize_terminal(80, 24)
        await pilot.pause(0.3)
        assert isinstance(app.screen, BriefingScreen)
        assert not any(isinstance(screen, TooSmallScreen) for screen in app.screen_stack)
        await pilot.press("escape")
        await pilot.pause(0.2)
        assert isinstance(app.screen, BriefingScreen)


def test_the_key_bar_still_has_the_footer_key_it_measures() -> None:
    """KeyBar sizes Textual's private FooterKey; if a Textual upgrade removes it this fails here, not on screen."""
    from textual.widgets._footer import FooterKey

    key = FooterKey("q", "q", "Quit", "quit")
    assert (key.key_display, key.description, key.action) == ("q", "Quit", "quit")


async def test_every_value_in_the_detail_starts_in_one_column() -> None:
    """The decoded rows, the forecast header and the period's rows share one label column (and the sublabels too)."""
    app = demo_app()
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause(0.3)
        await pilot.press("3")
        await pilot.pause(0.3)
        lines = screen_lines(app)
        column = lines[next(i for i, line in enumerate(lines) if "Valid:" in line)].index("2026-10-31 12:00")
        for label, value in (("Issued:", "2026-10-31 11:23"), ("Wind:", "From"), ("Visibility:", "1/4 SM")):
            row = next(line for line in lines if label in line)
            assert row.index(value) == column, (label, row)
        await pilot.press("2")
        await pilot.pause(0.3)
        lines = screen_lines(app)
        wind = next(line for line in lines if " Wind " in line)
        assert wind.index("From") == column


def test_wrap_keeps_stamps_and_paths_whole() -> None:
    from wxbrief.ui.wrap import wrap

    assert wrap("from 2026-10-31 12:00 UTC to 2026-11-01 18:00 UTC", 30) == [
        "from 2026-10-31 12:00 UTC to",
        "2026-11-01 18:00 UTC",
    ]
    assert wrap("saved unless --theme or --no-config is used", 28) == ["saved unless --theme or", "--no-config is used"]
    assert wrap(r"C:\Users\billp\AppData\Roaming\wxbrief\config.toml", 24) == [
        "C:\\Users\\billp\\AppData\\",
        "Roaming\\wxbrief\\",
        "config.toml",
    ]
    assert wrap("x" * 20, 8) == ["x" * 8, "x" * 8, "xxxx"]


async def test_roomy_terminals_give_the_cards_a_taller_box() -> None:
    app = demo_app("--layout", "grid")
    async with app.run_test(size=(200, 50)) as pilot:
        await pilot.pause(0.3)
        assert app.screen.has_class("-roomy")
        assert {card.outer_size.height for card in app.screen.query(StationCard)} == {9}
    async with demo_app("--layout", "grid").run_test(size=(120, 30)) as pilot:
        await pilot.pause(0.3)
        assert {card.outer_size.height for card in pilot.app.screen.query(StationCard)} == {7}
