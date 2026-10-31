"""The footer follows focus (list: a d v; detail: 1 2 3 c) and the station count is shown once, in the border title."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from test_timeline_ui import demo_app

from wxbrief.data.cache import CACHE_DIR_ENV
from wxbrief.ui.screens.station_detail import StationDetailScreen
from wxbrief.ui.widgets.detail import StationHeader
from wxbrief.ui.widgets.station_grid import StationGrid
from wxbrief.ui.widgets.station_list import StationList


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async def refuse(self: object, request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"network access in a test: {request.url}")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", refuse)
    monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path / "cache"))


def shown(app: object) -> list[str]:
    """The keys the footer would list now, in order."""
    bindings = app.screen.active_bindings  # type: ignore[attr-defined]
    return [key for key, active in bindings.items() if active.binding.show]


async def shown_is(app: object, pilot: object, expected: list[str]) -> list[str]:
    """The footer keys once they equal ``expected`` (bounded wait: the footer follows a focus or screen change later)."""
    keys = shown(app)
    for _ in range(100):
        if keys == expected:
            break
        await pilot.pause(0.05)  # type: ignore[attr-defined]
        keys = shown(app)
    return keys


async def test_the_footer_follows_focus() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert isinstance(app.focused, StationList)
        assert await shown_is(app, pilot, ["a", "d", "v", "p", "r", "question_mark", "q", "t"]) == ["a", "d", "v", "p", "r", "question_mark", "q", "t"]
        await pilot.press("enter")  # into the detail pane
        assert await shown_is(app, pilot, ["1", "2", "3", "c", "a", "p", "r", "question_mark", "q", "t"]) == ["1", "2", "3", "c", "a", "p", "r", "question_mark", "q", "t"]
        await pilot.press("v")  # still works from the detail pane, though the footer does not list it
        assert isinstance(app.focused, StationGrid)
        assert await shown_is(app, pilot, ["a", "d", "v", "p", "r", "question_mark", "q", "t"]) == ["a", "d", "v", "p", "r", "question_mark", "q", "t"]


async def screen_text(app: object, pilot: object, *wanted: str) -> str:
    """The drawn screen as text, once every wanted label shows (bounded wait: the footer draws after the first pass)."""
    text = ""
    for _ in range(100):
        await pilot.pause(0.05)  # type: ignore[attr-defined]
        text = "\n".join(strip.text for strip in app.screen._compositor.render_strips())  # type: ignore[attr-defined]
        if all(label in text for label in wanted):
            break
    return text


async def test_hidden_keys_stay_hidden_and_the_footer_stays_short() -> None:
    app = demo_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        keys = shown(app)
        assert {"g", "u", "z", "C", "y"}.isdisjoint(keys)
        assert "q" in keys and "t" in keys
        footer = await screen_text(app, pilot, "Add", "Quit", "Help")
        # at 80 columns the list is hidden, so j/k takes the room; Theme is the first key to drop out, whole
        assert "Add" in footer and "Quit" in footer and "Help" in footer and "j/k" in footer


async def test_the_count_is_in_the_border_title_and_not_in_the_detail_header() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        count = len(app.state.ids)
        assert app.briefing.query_one(StationList).border_title == f"Stations ({count})"
        assert app.briefing.query_one(StationGrid).border_title == f"Stations ({count})"
        header = app.briefing.query_one(StationHeader).render().plain  # type: ignore[union-attr]
        assert f"1/{count}" not in header


async def test_the_station_screen_copies_and_jumps(monkeypatch: pytest.MonkeyPatch) -> None:
    copied: list[str] = []
    monkeypatch.setattr("wxbrief.ui.copying.copy_text", lambda app, text, what, t: copied.append(what))
    app = demo_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("v", "enter")
        await pilot.pause()
        assert isinstance(app.screen, StationDetailScreen)
        keys = await shown_is(app, pilot, ["1", "2", "3", "c", "escape", "q", "t"])
        assert "a" not in keys and keys[:4] == ["1", "2", "3", "c"]
        await pilot.press("c")
        assert len(copied) == 1 and "METAR" in copied[0]
        await pilot.press("3", "2", "1", "a")  # none of these may raise; a is not offered on this screen
        await pilot.pause()
        assert isinstance(app.screen, StationDetailScreen)


async def test_the_border_title_count_follows_add_remove_and_language() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        station_list = app.briefing.query_one(StationList)
        count = len(app.state.ids)
        app.remove_station(app.state.ids[0])
        await pilot.pause()
        assert station_list.border_title == f"Stations ({count - 1})"
        app.add_station("KDEN")
        await pilot.pause()
        assert station_list.border_title == f"Stations ({count})"
        app.apply_setting("lang", "es")
        await pilot.pause()
        assert station_list.border_title == f"Estaciones ({count})"
        assert app.briefing.query_one(StationGrid).border_title == f"Estaciones ({count})"
