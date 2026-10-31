"""The footer follows focus (list: a d v; detail: 1 2 3 c) and the station count is shown once, in the border title."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from test_timeline_ui import demo_app

from wxbrief.data.cache import CACHE_DIR_ENV
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


async def test_the_footer_follows_focus() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert isinstance(app.focused, StationList)
        assert shown(app) == ["a", "d", "v", "p", "r", "question_mark", "q", "t"]
        await pilot.press("enter")  # into the detail pane
        assert shown(app) == ["1", "2", "3", "c", "p", "r", "question_mark", "q", "t"]
        await pilot.press("v")  # still works from the detail pane, though the footer does not list it
        assert isinstance(app.focused, StationGrid)
        assert shown(app) == ["a", "d", "v", "p", "r", "question_mark", "q", "t"]


async def test_hidden_keys_stay_hidden_and_the_footer_stays_short() -> None:
    app = demo_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        keys = shown(app)
        assert {"g", "u", "z", "C", "y"}.isdisjoint(keys)
        assert "q" in keys and "t" in keys
        footer = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
        assert "Quit" in footer and "Theme" in footer


async def test_the_count_is_in_the_border_title_and_not_in_the_detail_header() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        count = len(app.state.ids)
        assert app.briefing.query_one(StationList).border_title == f"Stations ({count})"
        assert app.briefing.query_one(StationGrid).border_title == f"Stations ({count})"
        header = app.briefing.query_one(StationHeader).render().plain  # type: ignore[union-attr]
        assert f"1/{count}" not in header
