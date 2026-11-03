"""(f) What the app says about data age today: fresh/stale on observation time, offline after two network failures.

A feed state (LIVE, STALE after 300 s) runs on the scheduler's monotonic clock, apart from the observation age.
"""

from __future__ import annotations

import re
from datetime import timedelta

from test_app_smoke import NOW, online_client
from ux_kit import load, make_app, rows

from wxbrief.data.poll import STALE_AFTER, Freshness, PollScheduler, Product, freshness
from wxbrief.ui.widgets.detail import FlagsRow
from wxbrief.ui.widgets.station_list import StationList
from wxbrief.ui.widgets.status_bar import StatusBar

OBS = NOW - timedelta(minutes=11)


def test_freshness_boundary_is_55_minutes() -> None:
    assert freshness(OBS, OBS + timedelta(minutes=54)) is Freshness.FRESH
    assert freshness(OBS, OBS + STALE_AFTER) is Freshness.STALE
    assert freshness(None, NOW) is Freshness.STALE


def test_an_observation_older_than_55_minutes_is_not_called_fresh() -> None:
    """Hourly METARs are due about every 60 min; at 56 min the routine report is overdue yet the header says fresh."""
    assert freshness(OBS, OBS + timedelta(minutes=56)) is not Freshness.FRESH


async def test_offline_needs_two_network_failures_then_shows(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = make_app(tmp_path, ["KDEN"])
    async with app.run_test(size=(120, 40)) as pilot:
        load(app, rows("metar_kden_egll"), rows("taf_kden_egll"))
        assert app.state.record_error(Product.METAR, "metar: down", offline=True) is False
        assert app.state.record_error(Product.METAR, "metar: down", offline=True) is True
        app.redraw_screens()
        await pilot.pause()
        assert "offline" in str(app.screen.query_one(StatusBar).render())


async def test_special_report_is_a_chip_in_the_detail_pane(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = make_app(tmp_path, ["KDEN"])
    async with app.run_test(size=(120, 40)) as pilot:
        load(app, rows("metar_kden_egll"), rows("taf_kden_egll"))
        await pilot.pause()
        assert "Special report" in str(app.screen.query_one(FlagsRow).render())


def _with_maintenance_flag():  # type: ignore[no-untyped-def]
    data = rows("metar_kden_egll")
    for row in data:
        if row["icaoId"] == "KDEN":
            row["rawOb"] = row["rawOb"] + " $"
    return data


async def test_maintenance_flag_shows_as_a_chip_in_the_detail_pane(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = make_app(tmp_path, ["KDEN"])
    async with app.run_test(size=(120, 40)) as pilot:
        load(app, _with_maintenance_flag(), rows("taf_kden_egll"))
        await pilot.pause()
        assert "needs maintenance" in str(app.screen.query_one(FlagsRow).render())


async def test_station_list_row_marks_maintenance_and_special_reports(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The list is where a pilot scans; a `$` (sensors unreliable) or SPECI is visible only after opening the station."""
    app = make_app(tmp_path, ["KDEN"])
    async with app.run_test(size=(120, 40)) as pilot:
        load(app, _with_maintenance_flag(), rows("taf_kden_egll"))
        await pilot.pause()
        line = app.screen.query_one(StationList).get_option_at_index(0).prompt.plain
        assert "$" in line or "SPECI" in line, line


async def test_status_bar_reports_feed_age_when_polls_stop_succeeding(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """No success for 400 s (> 300 s) and no failure recorded: the bar only counts down to the next poll."""
    clock = [1000.0]
    app = make_app(tmp_path, ["KDEN"])
    async with app.run_test(size=(120, 40)) as pilot:
        load(app, rows("metar_kden_egll"), rows("taf_kden_egll"))
        sched = PollScheduler(
            online_client(), lambda: ["KDEN"], lambda *a: None, clock=lambda: clock[0], metar_interval=3600, taf_interval=3600
        )
        await sched.run_cycle()
        app.scheduler = sched
        clock[0] += 400
        app.briefing.refresh_status()
        await pilot.pause()
        text = str(app.screen.query_one(StatusBar).render())
        assert re.search(r"(stale|ago|\bage\b|no update|last)", text, re.I), text
