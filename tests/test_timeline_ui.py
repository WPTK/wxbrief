"""The TAF timeline, period detail, grid layout and ``--demo``: run in a pilot, fully offline."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from rich.text import Text
from test_app_smoke import wait_for

from wxbrief import app as app_module
from wxbrief.__main__ import build_tui_parser, tui_options
from wxbrief.app import WxBriefApp
from wxbrief.data.demo import DEMO_NOW, demo_ids, demo_text, load_demo
from wxbrief.data.poll import Freshness
from wxbrief.decode.model import Metar, Taf
from wxbrief.decode.split import parse_any
from wxbrief.ui.screens.briefing import BriefingScreen
from wxbrief.ui.screens.station_detail import StationDetailScreen
from wxbrief.ui.widgets.detail import DetailPane
from wxbrief.ui.widgets.period_detail import PeriodDetail
from wxbrief.ui.widgets.station_card import StationCard
from wxbrief.ui.widgets.station_grid import StationGrid
from wxbrief.ui.widgets.station_list import StationList
from wxbrief.ui.widgets.taf_timeline import TafTimeline


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async def refuse(self: object, request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"network access in a test: {request.url}")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", refuse)
    monkeypatch.setenv("WXBRIEF_CACHE_DIR", str(tmp_path / "cache"))

    def no_save(*args: object, **kwargs: object) -> bool:
        raise AssertionError("the demo wrote the config")

    monkeypatch.setattr(app_module, "save_config", no_save)


def demo_app(*flags: str) -> WxBriefApp:
    options = tui_options(build_tui_parser().parse_args(["--demo", "--glyphs", "unicode", "--no-config", *flags]))
    return WxBriefApp(options)


def text_of(widget: object) -> str:
    content = widget.render()  # type: ignore[attr-defined]
    return content.plain if isinstance(content, Text) else str(content)


async def settle(pilot: object) -> None:
    await pilot.pause()  # type: ignore[attr-defined]
    await pilot.pause(0.1)  # type: ignore[attr-defined]


# --- the demo ------------------------------------------------------------------------------------------------------


def test_every_demo_report_decodes_without_unexpected_warnings() -> None:
    stations = load_demo()
    assert [s.icao for s in stations] == [
        "KDEN", "EGLL", "ETHB", "UUEE", "YSSY", "RJTT", "VIDP", "SBGR", "CYYZ", "NZSP"
    ]  # fmt: skip
    for station in stations:
        assert isinstance(station.metar, Metar) and isinstance(station.taf, Taf), station.icao
        assert station.metar.station == station.taf.station == station.icao
        assert station.metar.warnings == (), station.icao
        if station.icao == "NZSP":
            # the real forecast ends with notes this decoder leaves as unknown words (see the S2b notes)
            assert {w.text for w in station.taf.warnings} == {"WND21008KT", "AFT", "3122", "ALL", "WINDS", "GRID"}
        else:
            assert station.taf.warnings == (), station.icao
        # a fixed clock at which every METAR is fresh and every TAF is in force
        assert station.awc_metar.observed is not None
        assert DEMO_NOW - station.awc_metar.observed < timedelta(minutes=75)
        assert station.taf.valid_from is not None and station.taf.valid_to is not None
        assert station.taf.valid_from <= DEMO_NOW < station.taf.valid_to


def test_demo_files_are_one_metar_and_one_taf() -> None:
    for icao in demo_ids():
        kinds = [type(item) for item in parse_any(demo_text(icao), DEMO_NOW)]
        assert kinds == [Metar, Taf], icao


async def test_demo_boots_offline_and_writes_nothing(tmp_path: Path) -> None:
    app = demo_app()
    assert app.options.demo and not app.options.poll and not app.options.use_cache and not app.options.use_config
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot)
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        assert briefing.query_one(StationList).option_count == 10
        assert app.scheduler is None
        assert app.state.ids == demo_ids()
        assert app.state.stations["KDEN"].freshness(app.now()) is Freshness.FRESH
        briefing.select("NZSP")
        await settle(pilot)
        assert "NZSP" in text_of(briefing.query_one("#header"))
    assert not (tmp_path / "cache").exists()


# --- the timeline --------------------------------------------------------------------------------------------------


async def test_timeline_cells_and_cursor_keys() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 50)) as pilot:
        await settle(pilot)
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        briefing.select("EGLL")
        await settle(pilot)
        timeline = briefing.query_one(TafTimeline)
        detail = briefing.query_one(PeriodDetail)
        assert timeline.step == 1 and len(timeline.cells) == 30
        assert timeline.cursor == 0  # the clock is at the first hour of the forecast
        assert "12:00 GMT to 13:00 GMT" in text_of(detail)
        assert "Prevailing: Base forecast" in text_of(detail)

        await pilot.press("3")  # jump to the forecast: the timeline takes the keyboard
        await wait_for(pilot, lambda: timeline.has_focus, "the timeline focused")
        for _ in range(10):
            await pilot.press("right")
        await wait_for(pilot, lambda: timeline.cursor == 10, "the cursor at 22:00Z, inside the BECMG 21-24 window")
        await wait_for(pilot, lambda: "22:00 GMT to 23:00 GMT" in text_of(detail), "the period text")
        shown = text_of(detail)
        assert "Becoming" in shown and "haze" in shown.lower()
        await pilot.press("right", "right")  # 00:00Z: the TEMPO group
        await wait_for(pilot, lambda: "Temporary" in text_of(detail), "the TEMPO group")
        shown = text_of(detail)
        assert "Temporary" in shown and "30% chance" not in shown
        assert "Worst case in this window:" in shown
        await pilot.press("right")  # 01:00Z: the PROB30 group joins it
        await wait_for(pilot, lambda: "30% chance" in text_of(detail), "the PROB30 group")
        await pilot.press("end")
        await wait_for(pilot, lambda: timeline.cursor == 29, "the cursor at the end")
        await pilot.press("home", "left")
        await wait_for(pilot, lambda: timeline.cursor == 0, "the cursor at the start")


async def test_hover_selects_the_period_under_the_mouse() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 50)) as pilot:
        await settle(pilot)
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        briefing.select("KDEN")
        await settle(pilot)
        timeline = briefing.query_one(TafTimeline)
        timeline.scroll_visible(animate=False)
        await settle(pilot)
        await pilot.hover(TafTimeline, offset=(2 * 5 + 1, 1))  # two columns per hour: the sixth cell, 17:00Z
        await settle(pilot)
        assert timeline.cursor == 5
        assert "2026-10-31 11:00 MDT to 12:00 MDT" in text_of(briefing.query_one(PeriodDetail))  # Denver is UTC-6
        await pilot.hover(TafTimeline, offset=(2 * 20, 1))
        await settle(pilot)
        assert timeline.cursor == 20


async def test_narrow_terminal_uses_three_hour_cells() -> None:
    app = demo_app()
    async with app.run_test(size=(60, 20)) as pilot:
        await settle(pilot)
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        briefing.select("EGLL")
        await settle(pilot)
        timeline = briefing.query_one(TafTimeline)
        assert timeline.step == 3 and len(timeline.cells) == 10
        assert all(len(c.hours) == 3 for c in timeline.cells)
        await pilot.press("3", "right")
        await wait_for(pilot, lambda: timeline.cursor == 1, "the cursor on the second block")
        await wait_for(
            pilot,
            lambda: "15:00 GMT to 18:00 GMT" in text_of(briefing.query_one(PeriodDetail)),
            "the second block's period text",
        )


async def test_timeline_follows_the_time_mode() -> None:
    app = demo_app("--time", "zulu")
    async with app.run_test(size=(120, 50)) as pilot:
        await settle(pilot)
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        briefing.select("YSSY")
        await settle(pilot)
        assert "12:00Z to 13:00Z" in text_of(briefing.query_one(PeriodDetail))
        assert "UTC" in text_of(briefing.query_one(TafTimeline))


async def test_station_without_a_taf_shows_no_timeline() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 50)) as pilot:
        await settle(pilot)
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        app.state.stations["EGLL"].taf = None
        briefing.select("EGLL")
        await settle(pilot)
        assert not briefing.query_one(TafTimeline).display
        assert not briefing.query_one("#taf-title").display


# --- the grid ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("width", "columns"), [(140, 3), (60, 1)])
async def test_grid_layout_columns(width: int, columns: int) -> None:
    app = demo_app()
    async with app.run_test(size=(width, 20)) as pilot:
        await settle(pilot)
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        assert briefing.query_one(DetailPane).display
        await pilot.press("v")
        grid = briefing.query_one(StationGrid)
        await wait_for(
            pilot,
            lambda: grid.display
            and not briefing.query_one(StationList).display
            and not briefing.query_one(DetailPane).display
            and grid.columns == columns
            and len(briefing.query(StationCard)) == 10,
            "the grid laid out",
        )
        cards = list(briefing.query(StationCard))
        assert len(cards) == 10
        xs = {card.region.x for card in cards[:columns]}
        assert len(xs) == columns
        assert sum(1 for card in cards if card.has_class("-selected")) == 1
        await pilot.press("v")
        await wait_for(pilot, lambda: briefing.query_one(DetailPane).display and not grid.display, "the list layout")


async def test_grid_keys_select_and_open_detail() -> None:
    app = demo_app("--layout", "grid")
    async with app.run_test(size=(140, 40)) as pilot:
        await settle(pilot)
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        assert briefing.layout_mode == "grid" and briefing.query_one(StationGrid).display
        await pilot.press("right", "down")
        # EGLL is the second card; one row (three columns) down is the fifth
        await wait_for(pilot, lambda: briefing.selected == "YSSY", "YSSY selected")
        await pilot.press("enter")
        await wait_for(pilot, lambda: isinstance(app.screen, StationDetailScreen), "the station screen")
        await wait_for(pilot, lambda: len(app.screen.query(TafTimeline)) == 1, "the timeline")
        await pilot.press("escape")
        await wait_for(pilot, lambda: isinstance(app.screen, BriefingScreen), "the briefing")


async def test_card_mini_strip_text() -> None:
    app = demo_app("--layout", "grid")
    async with app.run_test(size=(140, 40)) as pilot:
        await settle(pilot)
        card = next(c for c in app.screen.query(StationCard) if c.icao == "KDEN")
        shown = text_of(card)
        assert "KDEN" in shown and "LIFR" in shown and "32005KT 1/4SM" in shown
        assert "L " in shown  # the strip starts on LIFR
        tick_row = shown.splitlines()[2]
        assert tick_row.startswith("0") or tick_row.startswith("1") or tick_row.startswith("2")  # hour labels
        assert "MDT" in tick_row or "MST" in tick_row  # the zone the labels are in


async def test_card_says_when_the_taf_has_expired() -> None:
    app = demo_app("--layout", "grid")
    app.options.now = lambda: DEMO_NOW + timedelta(days=3)
    async with app.run_test(size=(140, 40)) as pilot:
        await settle(pilot)
        shown = text_of(next(c for c in app.screen.query(StationCard) if c.icao == "KDEN"))
        assert "TAF expired" in shown and "no TAF" not in shown


# --- review fixes --------------------------------------------------------------------------------------------------


def test_demo_without_no_config_ignores_the_config_file() -> None:
    options = tui_options(build_tui_parser().parse_args(["--demo"]))
    assert options.demo and not options.use_config and options.ids == demo_ids()


async def test_grid_adds_and_removes_stations() -> None:
    app = demo_app("--layout", "grid")
    async with app.run_test(size=(140, 40)) as pilot:
        await settle(pilot)
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        grid = briefing.query_one(StationGrid)

        def order() -> list[str]:
            return [card.icao for card in grid.query(StationCard)]

        assert order() == demo_ids()
        app.remove_station("EGLL")
        await settle(pilot)
        assert order() == [i for i in demo_ids() if i != "EGLL"]
        app.add_station("KJFK")
        await settle(pilot)
        assert order()[-1] == "KJFK" and len(order()) == 10
        app.remove_station("KJFK")  # and straight back again, in the same pass
        app.add_station("KJFK")
        app.add_station("EGLL")
        await settle(pilot)
        assert sorted(order()) == sorted(app.state.ids) and order() == app.state.ids
        assert sum(1 for card in grid.query(StationCard) if card.has_class("-selected")) == 1


async def test_digit_keys_do_nothing_in_the_grid() -> None:
    app = demo_app("--layout", "grid")
    async with app.run_test(size=(140, 40)) as pilot:
        await settle(pilot)
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        await pilot.press("3", "1", "2")
        await settle(pilot)
        await wait_for(pilot, lambda: briefing.query_one(StationGrid).has_focus, "the grid focused")
        assert not briefing.query_one(TafTimeline).has_focus


async def test_timeline_focus_is_released_when_the_taf_goes_away() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 50)) as pilot:
        await settle(pilot)
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        await pilot.press("3")
        timeline = briefing.query_one(TafTimeline)
        await wait_for(pilot, lambda: timeline.has_focus, "the timeline focused")
        app.state.stations["KDEN"].taf = None
        briefing.refresh_view()
        await settle(pilot)
        assert not timeline.display and not timeline.has_focus
        assert briefing.query_one(DetailPane).has_focus  # the keyboard went to the pane, not nowhere


async def test_a_stale_cursor_message_is_dropped() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 50)) as pilot:
        await settle(pilot)
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        briefing.select("EGLL")
        await settle(pilot)
        timeline = briefing.query_one(TafTimeline)
        detail = briefing.query_one(DetailPane)
        period = briefing.query_one(PeriodDetail)
        shown = text_of(period)
        old = TafTimeline.Moved(timeline, timeline.cells[0], timeline.taf, timeline.timeline, "KDEN")
        detail.on_taf_timeline_moved(old)  # another station's message
        stale = TafTimeline.Moved(timeline, timeline.cells[5], timeline.taf, timeline.timeline, "EGLL")
        detail.on_taf_timeline_moved(stale)  # the cursor is not on cell 5
        await settle(pilot)
        assert text_of(period) == shown


async def test_toggling_layout_twice_at_60_columns_keeps_focus_visible() -> None:
    app = demo_app()
    async with app.run_test(size=(60, 20)) as pilot:
        await settle(pilot)
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        await pilot.press("v", "v")
        await wait_for(pilot, lambda: briefing.query_one(DetailPane).has_focus, "the detail pane focused")
        assert not briefing.query_one(StationList).display
        assert not briefing.query_one(StationList).has_focus


async def test_detail_screen_redraws_on_theme_change() -> None:
    app = demo_app("--layout", "grid")
    async with app.run_test(size=(140, 40)) as pilot:
        await settle(pilot)
        await pilot.press("enter")
        await wait_for(pilot, lambda: isinstance(app.screen, StationDetailScreen), "the station screen")
        screen = app.screen
        assert isinstance(screen, StationDetailScreen)
        calls: list[int] = []
        monkey = screen.redraw
        screen.redraw = lambda: (calls.append(1), monkey())[1]  # type: ignore[method-assign]
        app.theme = "nord" if app.theme != "nord" else "textual-dark"
        await settle(pilot)
        await pilot.pause(0.5)
        assert calls
