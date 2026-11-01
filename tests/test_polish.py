"""S8 polish: the g/u/z keys, the AWC cross-check mark, save failures, rate-limit holds and the scroll fixes."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from rich.text import Text
from test_app_smoke import make_app
from test_timeline_ui import demo_app

from wxbrief import app as app_module
from wxbrief.app import WxBriefApp
from wxbrief.data.awc import AwcClient
from wxbrief.data.cache import CACHE_DIR_ENV, default_cache_dir
from wxbrief.data.poll import PollScheduler
from wxbrief.ui.screens.briefing import BriefingScreen
from wxbrief.ui.widgets.detail import DecodedTable, DetailPane, StationHeader
from wxbrief.ui.widgets.station_grid import StationGrid
from wxbrief.ui.widgets.station_list import StationList


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async def refuse(self: object, request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"network access in a test: {request.url}")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", refuse)
    monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path / "cache"))


def plain(widget: object) -> str:
    content = widget.render()  # type: ignore[attr-defined]
    return content.plain if isinstance(content, Text) else str(content)


def demo(tmp_path: Path) -> WxBriefApp:
    return demo_app()


async def test_g_u_z_cycle_the_view_settings(tmp_path: Path) -> None:
    app = demo(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert (app.glyph_set, app.ctx.units.value, app.ctx.time_mode) == ("unicode", "mixed", "station")
        await pilot.press("g")
        assert app.glyph_set == "emoji" and app.ctx.glyphs.fresh == "🟢"
        await pilot.press("u")
        assert app.ctx.units.value == "us"
        await pilot.press("z")
        assert app.ctx.time_mode == "local"
        for _ in range(3):
            await pilot.press("z")
        assert app.ctx.time_mode == "local"  # three modes: a full turn comes back to where it was


async def test_the_status_bar_shows_live_state_only(tmp_path: Path) -> None:
    app = demo(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        from wxbrief.ui.widgets.status_bar import StatusBar

        text = plain(app.screen.query_one(StatusBar))
        for setting in (app.theme, "unicode", "mixed", "station"):
            assert setting not in text


async def test_awc_category_mark(tmp_path: Path) -> None:
    app = demo(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, BriefingScreen)
        assert "≠" not in plain(screen.query_one(StationHeader))
        entry = app.state.stations["KDEN"]
        assert entry.metar is not None and entry.awc_metar is not None
        entry.awc_metar = replace(entry.awc_metar, flight_category="MVFR")  # ours is LIFR
        screen.refresh_view()
        await pilot.pause()
        assert "≠MVFR" in plain(screen.query_one(StationHeader))
        assert "≠MVFR" in str(screen.query_one(StationList).get_option("KDEN").prompt)
        entry.awc_metar = replace(entry.awc_metar, flight_category=entry.metar.flight_category.value)  # type: ignore[union-attr]
        screen.refresh_view()
        await pilot.pause()
        assert "≠" not in plain(screen.query_one(StationHeader))
        app.ctx.crosscheck = False
        entry.awc_metar = replace(entry.awc_metar, flight_category="MVFR")
        screen.refresh_view()
        await pilot.pause()
        assert "≠" not in plain(screen.query_one(StationHeader))  # switched off in the config


async def test_the_summary_row_is_not_in_the_decoded_table(tmp_path: Path) -> None:
    app = demo(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        table = app.screen.query_one(DecodedTable)
        labels = [str(table.get_row_at(i)[0]) for i in range(table.row_count)]
        assert labels and "Summary" not in labels


async def test_a_failed_save_leaves_the_config_alone_and_the_next_save_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = make_app(tmp_path, [], watchlist=["KDEN"])
    app.options.view = replace(app.options.config.view)  # the view in effect is a copy of what the file holds
    writes: list[bool] = []

    def failing(config: object, path: object) -> bool:
        writes.append(False)
        return False

    monkeypatch.setattr(app_module, "save_config", failing)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.add_station("EGLL")
        await pilot.pause()
        assert app.options.config.stations.watchlist == ["KDEN"]  # the write failed: nothing was recorded as saved
        app.apply_setting("glyph_set", "ascii")
        assert app.options.config.view.glyph_set != "ascii"
        saved: list[list[str]] = []
        monkeypatch.setattr(app_module, "save_config", lambda config, path: saved.append(list(config.stations.watchlist)) or True)
        app.apply_setting("units", "us")
        assert saved == [["KDEN", "EGLL"]] and app.options.config.view.glyph_set == "ascii"


async def test_refresh_during_a_rate_limit_hold_says_so(tmp_path: Path) -> None:
    app = make_app(tmp_path, [])
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        now = 1000.0
        scheduler = PollScheduler(AwcClient(), lambda: [], lambda *a: None, clock=lambda: now)
        scheduler.hold_until = now + 90
        app.scheduler = scheduler
        notices: list[str] = []
        app.notify = lambda message, **kw: notices.append(str(message))  # type: ignore[method-assign]
        app.refresh_now()
        assert notices == ["Rate limited; retrying in 90 s"]
        scheduler.hold_until = 0
        app.refresh_now()
        assert notices[-1] == "Refreshing"


def test_cache_dir_override_is_absolute(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CACHE_DIR_ENV, "relative/cache")
    assert default_cache_dir().is_absolute()


async def test_a_redraw_does_not_snap_the_grid_back(tmp_path: Path) -> None:
    app = demo(tmp_path)
    async with app.run_test(size=(80, 16)) as pilot:
        await pilot.pause()
        await pilot.press("v")
        await pilot.pause(0.2)
        grid = app.screen.query_one(StationGrid)
        grid.scroll_to(y=grid.max_scroll_y, animate=False)
        await pilot.pause()
        bottom = grid.scroll_y
        assert bottom > 0
        app.screen.refresh_view()  # type: ignore[attr-defined]
        await pilot.pause(0.2)
        assert grid.scroll_y == bottom


async def test_enter_in_the_grid_does_not_focus_the_hidden_detail_pane(tmp_path: Path) -> None:
    app = demo(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("v")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, BriefingScreen)
        screen.action_focus_detail()
        await pilot.pause()  # Widget.focus only schedules the change
        assert not screen.query_one(DetailPane).has_focus
        assert screen.query_one(StationGrid).has_focus


async def test_period_detail_uses_one_time_base(tmp_path: Path) -> None:
    app = demo(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("3")
        await pilot.pause(0.2)
        from wxbrief.ui.widgets.period_detail import PeriodDetail

        text = plain(app.screen.query_one(PeriodDetail))
        assert "MDT" in text and "UTC" not in text
        await pilot.press("z", "z")  # station -> local -> zulu
        await pilot.pause(0.2)
        text = plain(app.screen.query_one(PeriodDetail))
        assert "UTC" not in text and "Z" in text


async def test_timeline_names_both_zones_across_a_clock_change_and_labels_half_hours(tmp_path: Path) -> None:
    app = demo(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        from wxbrief.ui.widgets.taf_timeline import TafTimeline

        screen = app.screen
        assert isinstance(screen, BriefingScreen)
        first_line = plain(screen.query_one(TafTimeline)).split("\n")[0]
        assert first_line.rstrip().endswith("MDT/MST")  # KDEN's TAF runs past 2026-11-01 08:00Z
        screen.select("VIDP")
        await pilot.pause(0.2)
        first_line = plain(screen.query_one(TafTimeline)).split("\n")[0]
        assert ":30" in first_line and first_line.rstrip().endswith("IST")


async def test_a_view_flag_is_never_saved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = make_app(tmp_path, [], watchlist=["KDEN"])
    app.options.view = replace(app.options.config.view)
    app.options.flag_view = frozenset({"glyph_set"})
    saved: list[str] = []

    def record(config: object, path: object) -> bool:
        saved.append(config.view.glyph_set + config.view.units)  # type: ignore[attr-defined]
        return True

    monkeypatch.setattr(app_module, "save_config", record)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.apply_setting("glyph_set", "ascii")
        assert saved == []  # --glyphs was given: this run only
        app.apply_setting("units", "us")
        assert saved == ["unicodeus"]  # units were not a flag: saved; the glyph set was not
