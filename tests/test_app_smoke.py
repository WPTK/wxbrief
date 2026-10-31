"""TUI smoke tests: ``App.run_test()`` with a pilot. No test touches the network or the real clipboard or config."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from wxbrief import clipboard
from wxbrief.app import AppOptions, WxBriefApp
from wxbrief.config import Config
from wxbrief.data.awc import AwcClient
from wxbrief.data.cache import DiskCache
from wxbrief.ui.screens.add_station import AddStationScreen
from wxbrief.ui.screens.briefing import BriefingScreen
from wxbrief.ui.screens.help import HelpScreen
from wxbrief.ui.screens.paste import PasteDecodeScreen, parse_reference
from wxbrief.ui.widgets.detail import DecodedTable, DetailPane, RawReport, StationHeader
from wxbrief.ui.widgets.station_list import StationList
from wxbrief.ui.widgets.status_bar import StatusBar

FIXTURES = Path(__file__).parent / "fixtures" / "awc"
METARS = json.loads((FIXTURES / "metar_kden_egll.json").read_text(encoding="utf-8"))
TAFS = json.loads((FIXTURES / "taf_kden_egll.json").read_text(encoding="utf-8"))
NOW = datetime(2026, 10, 31, 11, 45, tzinfo=UTC)  # ten minutes after the newest saved KDEN report
LATER = NOW + timedelta(hours=6)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly if anything outside a mock transport tries to reach the network."""

    async def refuse(self: object, request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"network access in a test: {request.url}")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", refuse)


@pytest.fixture
def copied(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace the clipboard; the list collects what would have been copied."""
    store: list[str] = []
    monkeypatch.setattr(clipboard, "_pyperclip_copy", store.append)
    return store


def online_client() -> AwcClient:
    def handler(request: httpx.Request) -> httpx.Response:
        ids = set(request.url.params["ids"].split(","))
        source = METARS if request.url.path.endswith("/metar") else TAFS
        return httpx.Response(200, json=[row for row in source if row["icaoId"] in ids])

    return AwcClient(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def offline_client() -> AwcClient:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network is down", request=request)

    return AwcClient(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def make_app(
    tmp_path: Path,
    ids: list[str],
    client: AwcClient | None = None,
    *,
    now: datetime = NOW,
    watchlist: list[str] | None = None,
) -> WxBriefApp:
    config = Config()
    config.stations.watchlist = list(watchlist or [])
    options = AppOptions(
        ids=ids,
        config=config,
        view=config.view,
        config_path=tmp_path / "config.toml",
        cache_dir=tmp_path / "cache",
        client=client,
        poll=client is not None,
        now=lambda: now,
    )
    options.view.glyph_set = "unicode"
    return WxBriefApp(options)


def screen_text(app: WxBriefApp) -> str:
    return "\n".join(str(line) for line in (app.export_screenshot(),))


async def wait_for(pilot: object, condition: object, tries: int = 50) -> None:
    for _ in range(tries):
        if condition():  # type: ignore[operator]
            return
        await pilot.pause(0.05)  # type: ignore[attr-defined]
    raise AssertionError("condition not met")


async def test_live_data_fills_list_and_detail(tmp_path: Path) -> None:
    app = make_app(tmp_path, ["KDEN", "EGLL"], online_client())
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: app.state.stations.get("KDEN") and app.state.stations["KDEN"].taf)
        await pilot.pause()
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        assert briefing.query_one(StationList).option_count == 2
        header = str(briefing.query_one(StationHeader).render())
        assert "KDEN" in header and "fresh" in header
        assert briefing.query_one(DecodedTable).row_count > 5
        assert "KDEN" in str(briefing.query_one(RawReport).render())
        # a successful fetch is cached for the next launch
        assert DiskCache(tmp_path / "cache").read("metars") is not None
        assert app.scheduler is not None and app.scheduler.budget.used == 2
        assert "req 2/100" in str(briefing.query_one(StatusBar).render())


async def test_keys_select_jump_and_copy(tmp_path: Path, copied: list[str]) -> None:
    app = make_app(tmp_path, ["KDEN", "EGLL"], online_client())
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: app.state.stations.get("EGLL") and app.state.stations["EGLL"].taf)
        await pilot.pause()
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        assert briefing.selected == "KDEN"
        await pilot.press("j")
        assert briefing.selected == "EGLL"
        await pilot.press("right_square_bracket")
        assert briefing.selected == "KDEN"
        await pilot.press("left_square_bracket")
        assert briefing.selected == "EGLL"
        await pilot.press("3", "2", "1")
        await pilot.press("c")
        assert copied and "EGLL" in copied[-1] and copied[-1].startswith("```")
        await pilot.press("C")
        assert "TAF" in copied[-1] and copied[-1].count("```") >= 4
        await pilot.press("y")
        assert copied[-1].startswith("METAR EGLL")
        await pilot.press("question_mark")
        assert isinstance(app.screen, HelpScreen)
        await pilot.press("escape")
        assert isinstance(app.screen, BriefingScreen)


async def test_offline_relaunch_shows_cached_stale_data(tmp_path: Path) -> None:
    # first run online fills the cache
    first = make_app(tmp_path, ["KDEN", "EGLL"], online_client())
    async with first.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: first.state.stations.get("EGLL") and first.state.stations["EGLL"].taf)
    # second run: the network is down and six hours have passed
    second = make_app(tmp_path, ["KDEN", "EGLL"], offline_client(), now=LATER)
    async with second.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: second.state.errors)
        await pilot.pause()
        briefing = second.screen
        assert isinstance(briefing, BriefingScreen)
        header = str(briefing.query_one(StationHeader).render())
        assert "stale" in header and "cached" in header
        assert briefing.query_one(DecodedTable).row_count > 5
        status = str(briefing.query_one(StatusBar).render())
        assert "offline" in status and "stale" in status


async def test_damaged_cache_time_is_ignored(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path / "cache")
    cache.write("metars", METARS)
    path = tmp_path / "cache" / "metars.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["saved_at"] = "2026-10-31T11:40:00"  # no zone
    path.write_text(json.dumps(document), encoding="utf-8")
    app = make_app(tmp_path, ["KDEN"])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        assert app.state.stations.get("KDEN") is None


async def test_add_station_finds_heathrow_by_name(tmp_path: Path) -> None:
    app = make_app(tmp_path, ["KDEN"], online_client())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("a")
        assert isinstance(app.screen, AddStationScreen)
        await pilot.press(*"heathrow")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, AddStationScreen)
        assert screen.matches[0].icao == "EGLL"
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, BriefingScreen)
        assert "EGLL" in app.state.ids
        assert app.state.is_saved("EGLL")
        assert "EGLL" in (tmp_path / "config.toml").read_text(encoding="utf-8")
        await wait_for(pilot, lambda: app.state.stations.get("EGLL") and app.state.stations["EGLL"].metar)


async def test_remove_station(tmp_path: Path) -> None:
    app = make_app(tmp_path, ["KDEN"], watchlist=["EGLL"])
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert app.state.ids == ["EGLL", "KDEN"]
        await pilot.press("d")
        assert app.state.ids == ["KDEN"]
        assert "EGLL" not in (tmp_path / "config.toml").read_text(encoding="utf-8")


async def test_config_with_warnings_is_backed_up_before_saving(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[view]\nunits = 'bogus'\n", encoding="utf-8")
    app = make_app(tmp_path, [])
    app.options.config_warnings = ["view.units must be one of us, metric, mixed; using 'mixed'"]
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        app.add_station("EGLL")
        await pilot.pause()
    assert (tmp_path / "config.toml.bak").read_text(encoding="utf-8") == "[view]\nunits = 'bogus'\n"
    assert "EGLL" in path.read_text(encoding="utf-8")


async def test_paste_screen_decodes_offline_and_copies_discord(tmp_path: Path, copied: list[str]) -> None:
    app = make_app(tmp_path, [])
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("p")
        screen = app.screen
        assert isinstance(screen, PasteDecodeScreen)
        screen.query_one("TextArea").insert("METAR KDEN 131453Z 06007KT 3/4SM BR OVC003 09/08 A3001")
        await pilot.pause(0.5)  # past the 200 ms debounce
        assert len(screen.decoded) == 1
        assert screen.decoded[0].flight_category is not None
        assert screen.decoded[0].flight_category.value == "LIFR"
        await pilot.press("f2")
        assert copied and copied[-1] == screen.discord_text and "KDEN" in copied[-1]
        await pilot.press("escape")
        assert isinstance(app.screen, BriefingScreen)


def test_parse_reference() -> None:
    assert parse_reference("2026-10-13", NOW) == (datetime(2026, 10, 13, 12, tzinfo=UTC), True)
    assert parse_reference("", NOW) == (NOW, True)
    assert parse_reference("tomorrow", NOW) == (NOW, False)


async def test_small_terminal_stays_usable(tmp_path: Path) -> None:
    app = make_app(tmp_path, ["KDEN", "EGLL"], online_client())
    async with app.run_test(size=(60, 20)) as pilot:
        await wait_for(pilot, lambda: app.state.stations.get("EGLL") and app.state.stations["EGLL"].taf)
        await pilot.pause()
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        assert not briefing.query_one(StationList).display
        assert briefing.query_one(DetailPane).display
        assert briefing.selected == "KDEN"
        await pilot.press("right_square_bracket")
        assert briefing.selected == "EGLL"
        assert "EGLL" in str(briefing.query_one(StationHeader).render())
        await pilot.press("a")
        assert isinstance(app.screen, AddStationScreen)
        await pilot.press("escape")
        await pilot.press("p")
        assert isinstance(app.screen, PasteDecodeScreen)


async def test_empty_watchlist_shows_hint(tmp_path: Path) -> None:
    app = make_app(tmp_path, [])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        assert briefing.query_one("#placeholder").display
        await pilot.press("j", "k", "c", "d")  # nothing selected: none of these may fail


def test_tui_flags_override_view_for_this_run_only() -> None:
    from wxbrief.__main__ import build_tui_parser, tui_options

    args = build_tui_parser().parse_args(
        ["--no-config", "--glyphs", "ascii", "--units", "metric", "--time", "zulu", "kden", "egll"]
    )
    options = tui_options(args)
    assert options.ids == ["KDEN", "EGLL"]
    assert (options.view.glyph_set, options.view.units, options.view.time) == ("ascii", "metric", "zulu")
    assert options.config.view.glyph_set == "nerd"  # what a save would write is untouched
    assert not options.use_config
