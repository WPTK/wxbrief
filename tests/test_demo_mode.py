"""``--demo``: only the sample stations, a saved watchlist is neither shown nor touched, the status bar says it is not
live, and a repeated key press raises one toast."""

from __future__ import annotations

from pathlib import Path

from test_app_smoke import notes
from textual.widgets import Static

from wxbrief.__main__ import build_tui_parser, tui_options
from wxbrief.app import WxBriefApp
from wxbrief.data.demo import demo_ids
from wxbrief.i18n import Translator
from wxbrief.i18n.keys import K
from wxbrief.ui.widgets.status_bar import StatusBar

WATCHLIST = '[stations]\nwatchlist = ["KJAX", "KBQK", "KATL", "KCHS", "KVQQ", "KNIP"]\n'


def saved_config_app(tmp_path: Path, *flags: str) -> tuple[WxBriefApp, Path]:
    path = tmp_path / "config.toml"
    path.write_text(WATCHLIST, encoding="utf-8")
    args = build_tui_parser().parse_args(["--demo", "--config", str(path), *flags])
    options = tui_options(args)
    options.cache_dir = tmp_path / "cache"
    return WxBriefApp(options), path


async def test_demo_with_a_saved_watchlist_shows_only_demo_stations_and_leaves_the_file(tmp_path: Path) -> None:
    app, path = saved_config_app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert app.state.ids == demo_ids()
        assert all(entry.metar is not None for entry in app.state.stations.values())
        app.add_station("KJFK")
        app.remove_station("EGLL")
        app.action_cycle_theme()
        await pilot.pause()
        assert "KJFK" in app.state.ids and "EGLL" not in app.state.ids
    assert path.read_text(encoding="utf-8") == WATCHLIST
    assert not path.with_name("config.toml.bak").exists()


async def test_demo_status_bar_says_it_is_not_live(tmp_path: Path) -> None:
    app, _ = saved_config_app(tmp_path)
    t = Translator.load("en")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        bar = str(app.briefing.query_one(StatusBar).render())
        assert t.t(K.UI_STATUS_DEMO) in bar and t.t(K.UI_STATUS_POLLING_OFF) not in bar
        assert isinstance(app.briefing.query_one(StatusBar), Static)


async def test_refresh_in_demo_raises_one_toast_however_often_it_is_pressed(tmp_path: Path) -> None:
    app, _ = saved_config_app(tmp_path)
    expected = Translator.load("en").t(K.UI_TOAST_DEMO_REFRESH)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        for _ in range(3):
            await pilot.press("r")
        await pilot.pause()
        assert notes(app).count(expected) == 1
