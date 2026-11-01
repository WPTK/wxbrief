"""TUI smoke tests: ``App.run_test()`` with a pilot. No test touches the network or the real clipboard or config."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from textual import events

from wxbrief import clipboard
from wxbrief.app import AppOptions, WxBriefApp
from wxbrief.config import Config
from wxbrief.data.awc import AwcClient
from wxbrief.data.cache import DiskCache
from wxbrief.i18n import Translator
from wxbrief.i18n.keys import K
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
HELP_TEXT = Translator.load("en").t(K.UI_HELP_BODY)


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


async def wait_for(pilot: object, condition: object, what: str = "the condition", timeout: float = 5.0) -> None:
    """Poll ``condition()`` until it is true, for at most ``timeout`` seconds; never a fixed sleep.

    Use it after a key press whose effect (a screen change, a focus move, a layout settle) lands a frame or more later.
    """
    deadline = time.monotonic() + timeout
    while not condition():  # type: ignore[operator]
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out after {timeout:g} s waiting for: {what}")
        await pilot.pause(0.02)  # type: ignore[attr-defined]


async def assert_jump_keys_scroll(pilot: object, pane: DetailPane) -> None:
    """Keys 3, 2 and 1 bring the forecast, the decoded table and the raw report to the top of the pane."""
    def title_in_view(title_id: str) -> bool:
        title = pane.query_one(title_id)
        return pane.region.y <= title.region.y < pane.region.bottom

    assert pane.scroll_y == 0 and pane.max_scroll_y > 0, "the test needs a pane taller than its window"
    await pilot.press("3")  # type: ignore[attr-defined]
    await wait_for(pilot, lambda: pane.scroll_y > 0, "key 3 to scroll to the forecast")
    assert title_in_view("#taf-title")
    await pilot.press("2")  # type: ignore[attr-defined]
    await wait_for(pilot, lambda: title_in_view("#decoded-title"), "key 2 to bring the decoded table into view")
    scrolled = pane.scroll_y
    await pilot.press("1")  # type: ignore[attr-defined]
    await wait_for(pilot, lambda: pane.scroll_y < scrolled and title_in_view("#raw-title"), "key 1 to scroll back up")


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
        await pilot.press("k")
        assert briefing.selected == "KDEN"
        await pilot.press("j")
        assert briefing.selected == "EGLL"
        await assert_jump_keys_scroll(pilot, briefing.query_one(DetailPane))
        await pilot.press("c")
        assert copied and "EGLL" in copied[-1]
        assert copied[-1].startswith("```\n") and copied[-1].endswith("\n```") and "````" not in copied[-1]
        await pilot.press("C")
        assert "TAF" in copied[-1] and copied[-1].count("```") == 4 and "````" not in copied[-1]
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
        await wait_for(pilot, lambda: second.state.transport_failures)
        await pilot.pause()
        briefing = second.screen
        assert isinstance(briefing, BriefingScreen)
        header = str(briefing.query_one(StationHeader).render())
        assert "stale" in header and "cached" in header
        assert briefing.query_one(DecodedTable).row_count > 5
        status = str(briefing.query_one(StatusBar).render())
        assert "stale" in status and "offline" not in status  # one failed poll is not an outage


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
        await wait_for(pilot, lambda: len(screen.decoded) == 1)  # the 200 ms debounce has run
        assert screen.decoded[0].flight_category is not None
        assert screen.decoded[0].flight_category.value == "LIFR"
        await pilot.press("f2")
        assert copied and copied[-1] == screen.discord_text and "KDEN" in copied[-1]
        await pilot.press("escape")
        assert isinstance(app.screen, BriefingScreen)


def test_parse_reference() -> None:
    assert parse_reference("2026-10-13", NOW) == (datetime(2026, 10, 13, 23, 59, 59, tzinfo=UTC), True)
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
        await pilot.press("j")
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


def notes(app: WxBriefApp) -> list[str]:
    return [n.message for n in app._notifications]


async def test_enter_on_a_station_focuses_the_detail(tmp_path: Path) -> None:
    app = make_app(tmp_path, ["KDEN", "EGLL"], online_client())
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: app.state.stations.get("KDEN") and app.state.stations["KDEN"].metar)
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        assert briefing.query_one(StationList).has_focus
        await pilot.press("enter")
        assert briefing.query_one(DetailPane).has_focus


async def test_help_lists_the_view_keys(tmp_path: Path) -> None:
    assert "g  u  z" in HELP_TEXT and "[ and ]" not in HELP_TEXT
    app = make_app(tmp_path, [])
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press("question_mark")
        body = "\n".join(str(w.render()) for w in app.screen.query("Static"))
        assert "g  u  z" in body and "--no-config" in body


async def test_unknown_station_is_rejected_and_not_saved(tmp_path: Path) -> None:
    app = make_app(tmp_path, ["KDEN"])
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("a")
        await pilot.press(*"zzzz")
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, AddStationScreen)  # still open
        assert any("Unknown station ZZZZ" in n for n in notes(app))
        app.screen.dismiss(None)
        await pilot.pause()
        app.add_station("ZZZZ")
        assert "ZZZZ" not in app.state.ids
        assert not (tmp_path / "config.toml").exists()


async def test_duplicate_station_gives_a_message_and_selects_it(tmp_path: Path) -> None:
    app = make_app(tmp_path, ["KDEN", "EGLL"])
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.add_station("EGLL")
        await pilot.pause()
        assert "EGLL is already in the list (now saved)" in notes(app)  # it was only listed for this run
        assert isinstance(app.screen, BriefingScreen) and app.screen.selected == "EGLL"
        app.add_station("DEN")  # an IATA code resolves to the listed station
        await pilot.pause()
        assert "DEN" not in app.state.ids
        assert "KDEN is already in the list (now saved)" in notes(app)
        app.add_station("KDEN")  # now it is saved: the plain message
        await pilot.pause()
        assert "KDEN is already in the list" in notes(app)


async def test_unreadable_config_is_never_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[stations\nwatchlist = ", encoding="utf-8")
    app = make_app(tmp_path, [])
    app.options.config_usable = False
    app.options.config_warnings = [f"{path} is not valid TOML"]
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        app.add_station("EGLL")
        await pilot.pause()
        assert "EGLL" in app.state.ids  # kept for this run
        assert any("could not be read" in n for n in notes(app))
    assert path.read_text(encoding="utf-8") == "[stations\nwatchlist = "
    assert not (tmp_path / "config.toml.bak").exists()


async def test_removing_a_command_line_station_does_not_rewrite_the_config(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("# my notes\n[stations]\nwatchlist = ['EGLL']\n", encoding="utf-8")
    app = make_app(tmp_path, ["KDEN"], watchlist=["EGLL"])
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        briefing.select("KDEN")
        await pilot.press("d")
        assert app.state.ids == ["EGLL"]
    assert path.read_text(encoding="utf-8").startswith("# my notes")


async def test_backup_notice_names_the_bak_file(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[view]\nunits = 'bogus'\n", encoding="utf-8")
    app = make_app(tmp_path, [])
    app.options.config_warnings = ["view.units must be one of us, metric, mixed; using 'mixed'"]
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        app.add_station("EGLL")
        await pilot.pause()
        assert any("config.toml.bak" in n for n in notes(app))


def test_command_line_ids_are_resolved_and_bad_ones_reported() -> None:
    from wxbrief.__main__ import build_tui_parser, tui_options

    args = build_tui_parser().parse_args(["--no-config", "den", "egll", "!!", "toolong1"])
    options = tui_options(args)
    assert options.ids == ["KDEN", "EGLL"]
    assert len(options.notices) == 2 and not options.config_warnings


async def test_refocus_returns_the_scheduler_to_its_normal_interval(tmp_path: Path) -> None:
    app = make_app(tmp_path, ["KDEN"], online_client())
    async with app.run_test(size=(100, 30)) as pilot:
        await wait_for(pilot, lambda: app.state.stations.get("KDEN") and app.state.stations["KDEN"].metar)
        scheduler = app.scheduler
        assert scheduler is not None
        app.on_app_blur(events.AppBlur())
        assert scheduler.away
        app.on_app_focus(events.AppFocus())
        assert not scheduler.away


async def test_a_server_error_is_not_labelled_offline(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    client = AwcClient(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    app = make_app(tmp_path, ["KDEN"], client)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: app.state.errors)
        await pilot.pause()
        status = str(app.screen.query_one(StatusBar).render())
        assert "aviationweather.gov problem" in status and "503" not in status and "offline" not in status


async def test_a_deeply_nested_reply_does_not_close_the_app(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"[" * 100000 + b"]" * 100000)

    client = AwcClient(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    app = make_app(tmp_path, ["KDEN"], client)
    async with app.run_test(size=(100, 30)) as pilot:
        await wait_for(pilot, lambda: app.state.errors)
        assert app.is_running


async def test_a_config_with_unknown_keys_is_backed_up_before_saving(tmp_path: Path) -> None:
    from wxbrief.config import load_config

    path = tmp_path / "config.toml"
    path.write_text("[view]\ntheem = 'nord'\n\n[alerts]\nwebhook = 'x'\n", encoding="utf-8")
    loaded = load_config(path)
    app = make_app(tmp_path, [])
    app.options.config_warnings = loaded.warnings
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        app.add_station("EGLL")
        await pilot.pause()
    assert "alerts" in (tmp_path / "config.toml.bak").read_text(encoding="utf-8")
    assert "alerts" not in path.read_text(encoding="utf-8")


async def test_flight_category_row_wraps_in_a_narrow_pane(tmp_path: Path) -> None:
    app = make_app(tmp_path, ["KDEN"], online_client())
    async with app.run_test(size=(90, 30)) as pilot:
        await wait_for(pilot, lambda: app.state.stations.get("KDEN") and app.state.stations["KDEN"].metar)
        await pilot.pause()
        table = app.screen.query_one(DecodedTable)
        cells = [row[1].plain for row in (table.get_row_at(i) for i in range(table.row_count))]
        category = next(c for c in cells if "LIFR" in c)
        lines = category.split("\n")
        width = list(table.columns.values())[1].width
        assert len(lines) >= 3  # wrapped onto several lines, not one long one
        assert all(len(line) <= width for line in lines)
        assert "instrument flight rules" in " ".join(category.split())


def test_cache_dir_can_be_redirected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from wxbrief.data.cache import default_cache_dir

    monkeypatch.setenv("WXBRIEF_CACHE_DIR", str(tmp_path / "elsewhere"))
    assert default_cache_dir() == tmp_path / "elsewhere"
    assert DiskCache().directory == tmp_path / "elsewhere"


async def test_the_offline_label_and_message_come_from_the_same_error(tmp_path: Path) -> None:
    from wxbrief.data.poll import Product

    app = make_app(tmp_path, ["KDEN"])
    app.options.poll = False
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.state.record_error(Product.TAF, "taf: server error 503")
        for _ in range(2):
            app.state.record_error(Product.METAR, "metar: TransportError: down", offline=True)
        app.briefing.refresh_view()
        await pilot.pause()
        status = str(app.screen.query_one(StatusBar).render())
        assert "offline" in status and "problem" not in status


async def test_a_hand_written_config_is_backed_up_before_the_first_save(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    original = "# my stations\n[stations]\nwatchlist = ['EGLL']\n"
    path.write_text(original, encoding="utf-8")
    app = make_app(tmp_path, [], watchlist=["EGLL"])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        app.add_station("KDEN")
        await pilot.pause()
    assert (tmp_path / "config.toml.bak").read_text(encoding="utf-8") == original
    assert "KDEN" in path.read_text(encoding="utf-8")


async def test_a_config_the_app_wrote_is_not_backed_up_again(tmp_path: Path) -> None:
    from wxbrief.config import config_text

    path = tmp_path / "config.toml"
    app = make_app(tmp_path, [], watchlist=["EGLL"])
    path.write_text(config_text(app.options.config), encoding="utf-8")
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        app.add_station("KDEN")
        await pilot.pause()
    assert not (tmp_path / "config.toml.bak").exists()


def test_a_date_in_the_paste_field_keeps_late_reports_of_that_day() -> None:
    from wxbrief.decode.split import parse_any

    reference, _ = parse_reference("2026-10-31", NOW)
    raw = "METAR KDEN 311853Z 06007KT 10SM CLR 09/08 A3001\nTAF KDEN 311740Z 3118/0124 06007KT P6SM SKC"
    metar, taf = parse_any(raw, reference)
    assert metar.observed == datetime(2026, 10, 31, 18, 53, tzinfo=UTC)
    assert taf.valid_from == datetime(2026, 10, 31, 18, tzinfo=UTC)
