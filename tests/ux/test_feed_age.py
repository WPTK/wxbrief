"""(f) What the app says about data age today: fresh/stale on observation time, offline after two network failures.

A feed state (LIVE, STALE after 300 s) runs on the scheduler's monotonic clock, apart from the observation age.
"""

from __future__ import annotations

import re
from datetime import timedelta

import pytest
from test_app_smoke import NOW, online_client
from ux_kit import load, make_app, rows, screen_lines

from wxbrief.data.poll import STALE_AFTER, Freshness, PollScheduler, Product, freshness
from wxbrief.i18n import LANGUAGES, Translator
from wxbrief.i18n.keys import K
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


async def _bar_after(tmp_path, seconds: float, lang: str = "en", width: int = 120) -> tuple[str, int]:  # type: ignore[no-untyped-def]
    """The status bar text and its width in cells, ``seconds`` after a successful cycle at the real poll intervals."""
    clock = [1000.0]
    app = make_app(tmp_path, ["KDEN"])
    async with app.run_test(size=(width, 24)) as pilot:
        app.ctx.translator = Translator.load(lang)
        load(app, rows("metar_kden_egll"), rows("taf_kden_egll"))
        sched = PollScheduler(online_client(), lambda: ["KDEN"], lambda *a: None, clock=lambda: clock[0])
        await sched.run_cycle()
        app.scheduler = sched
        clock[0] += seconds
        app.briefing.refresh_status()
        await pilot.pause()
        bar = app.screen.query_one(StatusBar).render()
        return str(bar), bar.cell_length


async def test_status_bar_reports_feed_age_when_polls_stop_succeeding(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """No success for 1000 s (past 1.5 x the 600 s METAR poll) and no failure recorded: the bar says so."""
    text, _ = await _bar_after(tmp_path, 1000)
    assert re.search(r"(stale|ago|age|no update|last)", text, re.I), text


async def test_feed_is_live_in_the_middle_of_a_normal_cycle(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """400 s after a success the next 600 s poll is not yet overdue: a fixed 300 s would cry stale on every cycle."""
    text, _ = await _bar_after(tmp_path, 400)
    assert "live" in text and "stale" not in text.split("|")[1], text


@pytest.mark.parametrize("lang", LANGUAGES)
async def test_stale_feed_text_fits_an_80_column_bar_in_every_language(tmp_path, lang: str) -> None:  # type: ignore[no-untyped-def]
    text, cells = await _bar_after(tmp_path, 3599, lang, width=80)  # 59 min: the longest age before it reads hours
    t = Translator.load(lang)
    budget = t.t(K.UI_STATUS_REQUESTS, used=0, limit=100).split("0")[0]
    assert cells <= 80 and budget in text, (cells, text)


async def test_marks_survive_the_clip_of_the_narrowest_list(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The list is hidden below 90 columns and 38 wide at 90: a gusty SPECI with `$` must still show both marks."""
    data = rows("metar_kden_egll")
    for row in data:
        if row["icaoId"] == "KDEN":
            row["rawOb"] = row["rawOb"].replace("32005KT", "32025G40KT") + " $"
    app = make_app(tmp_path, ["KDEN"])
    async with app.run_test(size=(90, 24)) as pilot:
        load(app, data, rows("taf_kden_egll"))
        await pilot.pause()
        row = next(line for line in screen_lines(app) if "KDEN" in line)
        assert "SPECI" in row and "$" in row and "G40KT" in row, row
