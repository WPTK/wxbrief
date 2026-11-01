"""First-run input and state: a click on a station, the section keys, and the status bar when the network drops."""

from __future__ import annotations

from test_timeline_ui import demo_app, settle, text_of
from textual.widgets import Footer

from wxbrief.app import WxBriefApp
from wxbrief.data.awc import TransportError
from wxbrief.data.poll import Product
from wxbrief.i18n.keys import K
from wxbrief.ui.screens.briefing import BriefingScreen
from wxbrief.ui.widgets.detail import DetailPane
from wxbrief.ui.widgets.station_grid import StationCard, StationGrid
from wxbrief.ui.widgets.station_list import StationList
from wxbrief.ui.widgets.status_bar import StatusBar


def footer_keys(app: WxBriefApp) -> list[str]:
    return [str(key.key_display) for key in app.screen.query(Footer).first().query("FooterKey")]  # type: ignore[attr-defined]


def status_of(app: WxBriefApp) -> str:
    return text_of(app.screen.query_one(StatusBar))


async def test_clicking_a_station_selects_it_and_keeps_the_list_focused() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        stations = briefing.query_one(StationList)
        keys = footer_keys(app)
        row = stations.region.y + 4
        # what a terminal sends: move onto the row, press, release, click, then more motion
        await pilot.click(offset=(stations.region.x + 3, row))
        frames = []
        for step in range(5):
            await pilot.hover(offset=(stations.region.x + 3 + step, row))
            await settle(pilot)
            frames.append((briefing.selected, app.focused, stations.region, briefing.query_one(DetailPane).region))
        assert {f[0] for f in frames} == {app.state.ids[3]}
        assert all(f[1] is stations for f in frames)  # a click is not Enter: the focus stays in the list
        assert len({(f[2], f[3]) for f in frames}) == 1  # nothing re-laid out
        assert footer_keys(app) == keys


async def test_double_click_opens_the_detail() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        stations = app.screen.query_one(StationList)
        await pilot.click(offset=(stations.region.x + 3, stations.region.y + 3), times=2)
        await settle(pilot)
        assert isinstance(app.focused, DetailPane)


async def test_clicking_a_card_in_the_grid_selects_it() -> None:
    app = demo_app("--layout", "grid")
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        card = list(briefing.query(StationCard))[3]
        await pilot.click(offset=(card.region.x + 2, card.region.y + 1))
        await settle(pilot)
        assert briefing.selected == card.icao and isinstance(app.focused, StationGrid)


async def test_a_section_key_with_no_report_says_so_once() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        app.add_station("KJFK")  # listed, nothing fetched
        await settle(pilot)
        briefing = app.screen
        assert isinstance(briefing, BriefingScreen)
        briefing.select("KJFK")
        await settle(pilot)
        for _ in range(2):
            await pilot.press("1")
        await settle(pilot)
        no_report = app.ctx.translator.t(K.UI_DETAIL_NO_REPORT)
        assert [n.message for n in app._notifications].count(no_report) == 1


async def test_section_keys_scroll_the_detail_pane_from_the_list_and_after_a_click() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        pane = app.screen.query_one(DetailPane)
        stations = app.screen.query_one(StationList)
        await pilot.press("2")
        await settle(pilot)
        assert pane.scroll_y > 0
        await pilot.press("1")
        await settle(pilot)
        mid = pane.scroll_y
        await pilot.click(offset=(stations.region.x + 3, stations.region.y + 2))
        await settle(pilot)
        await pilot.press("3")
        await settle(pilot)
        assert pane.scroll_y > mid


async def test_offline_status_is_one_state_never_fresh() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        for _ in range(2):
            app.state.record_error(Product.METAR, "metar: down", offline=True)
        app.briefing.refresh_view()
        await settle(pilot)
        status = status_of(app)
        assert "offline, showing saved data from" in status and "fresh" not in status and "stale" not in status


async def test_one_failed_fetch_is_not_offline_and_raises_no_toast() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        shown = len(app._notifications)
        app._on_error(Product.METAR, TransportError("ConnectError"))
        await settle(pilot)
        assert not app.state.offline and not app.state.errors
        assert "offline" not in status_of(app)
        assert len(app._notifications) == shown


async def test_two_failures_in_a_row_are_offline_with_one_toast() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        shown = len(app._notifications)
        for _ in range(2):
            app._on_error(Product.METAR, TransportError("ConnectError"))
        await settle(pilot)
        assert app.state.offline == {Product.METAR}
        assert "offline" in status_of(app)
        assert len(app._notifications) == shown + 1


async def test_a_failing_taf_beside_a_good_metar_is_never_offline() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        for _ in range(3):
            app._on_error(Product.TAF, TransportError("ConnectError"))
            app._on_result(Product.METAR, [])
        await settle(pilot)
        assert not app.state.offline
        assert "offline" not in status_of(app)


async def test_a_real_outage_is_offline_and_the_next_success_clears_it() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(pilot)
        for _ in range(3):
            app._on_error(Product.METAR, TransportError("ConnectError"))
            app._on_error(Product.TAF, TransportError("ConnectError"))
        await settle(pilot)
        assert app.state.offline == {Product.METAR, Product.TAF}
        assert "offline, showing saved data from" in status_of(app)
        app._on_result(Product.TAF, [])
        await settle(pilot)
        assert not app.state.offline and not app.state.errors
        assert "offline" not in status_of(app)
