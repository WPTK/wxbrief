"""Round 5: the TAF flags the METAR side already had, the expired-TAF copy, the TAF Flags row and warnings, feed controls."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from test_timeline_ui import demo_app, settle, text_of
from test_ui_lifecycle import later

from wxbrief import app as app_module
from wxbrief.data.demo import DEMO_NOW
from wxbrief.data.models import parse_metar as parse_awc_metar
from wxbrief.data.models import parse_station
from wxbrief.decode.metar import parse_metar
from wxbrief.decode.model import Flag
from wxbrief.decode.taf import parse_taf
from wxbrief.ui import copying
from wxbrief.ui.screens.briefing import BriefingScreen


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async def refuse(self: object, request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"network access in a test: {request.url}")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", refuse)
    monkeypatch.setenv("WXBRIEF_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(app_module, "save_config", lambda *args, **kwargs: True)


TAF_TEXT = "TAF KDEN 311140Z 3112/3218 06007KT P6SM SKC TEMPO 3114/3118 +FC SQ BKN020CB"
VALID_FROM = DEMO_NOW.replace(hour=12, minute=0)


def test_taf_flags_include_tornado_funnel_cloud_and_squall_like_the_metar_side() -> None:
    taf = parse_taf(TAF_TEXT, DEMO_NOW)
    assert {Flag.TORNADO, Flag.SQUALL, Flag.CB} <= set(taf.flags)
    funnel = parse_taf("TAF KDEN 311140Z 3112/3218 06007KT P6SM SKC TEMPO 3114/3118 FC", DEMO_NOW)
    assert Flag.FUNNEL_CLOUD in funnel.flags and Flag.TORNADO not in funnel.flags
    near = parse_taf("TAF KDEN 311140Z 3112/3218 06007KT P6SM SKC TEMPO 3114/3118 VCFC", DEMO_NOW)
    assert Flag.FUNNEL_CLOUD not in near.flags
    metar = parse_metar("METAR KDEN 311153Z 06007KT 3SM +FC SQ BKN020CB 20/10 A3001", DEMO_NOW)
    assert {Flag.TORNADO, Flag.SQUALL} <= set(metar.flags)


async def test_the_detail_pane_shows_the_taf_flags() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 50)) as pilot:
        await settle(pilot)
        app.state.stations["KDEN"].taf = parse_taf(TAF_TEXT, DEMO_NOW)
        app.briefing.refresh_view()
        await settle(pilot)
        summary = text_of(app.screen.query_one("#taf-summary"))
        assert "Flags" in summary and "Tornado" in summary and "Squall" in summary


async def test_the_detail_pane_shows_the_taf_warnings() -> None:
    app = demo_app()
    async with app.run_test(size=(120, 50)) as pilot:
        await settle(pilot)
        taf = parse_taf(TAF_TEXT + " ZZZZ9", DEMO_NOW)
        assert taf.warnings
        app.state.stations["KDEN"].taf = taf
        app.briefing.refresh_view()
        await settle(pilot)
        shown = text_of(app.screen.query_one("#warnings"))
        assert "ZZZZ9" in shown and "Forecast" in shown


async def test_copying_both_leaves_out_an_expired_taf(monkeypatch: pytest.MonkeyPatch) -> None:
    copied: list[str] = []
    monkeypatch.setattr(copying, "copy_text", lambda app, text, *args: copied.append(text) or True)
    app = demo_app()
    async with app.run_test(size=(120, 50)) as pilot:
        await settle(pilot)
        assert isinstance(app.screen, BriefingScreen)
        entry = app.state.stations["KDEN"]
        assert entry.metar is not None and entry.taf is not None
        app.screen.action_copy_both()
        assert len(copied) == 1 and "KDEN" in copied[0]
        live = copied[0]
        later(app, timedelta(days=3))
        app.screen.action_copy_both()
        assert len(copied) == 2
        assert copied[1] != live and len(copied[1]) < len(live)  # the METAR alone
        entry.metar = None
        app.screen.action_copy_both()
        assert len(copied) == 2  # an expired TAF alone: nothing is copied


def test_feed_strings_lose_their_control_characters() -> None:
    station = parse_station({"icaoId": "KDEN", "site": "Denver\x1b]0;pwn\x07 Intl"})
    assert station is not None and "\x1b" not in (station.name or "") and "\x07" not in (station.name or "")
    row = parse_awc_metar({"icaoId": "KDEN", "rawOb": "METAR KDEN 311153Z 06007KT", "name": "A\x1b[2JB"})
    assert row is not None and row.name is not None and "\x1b" not in row.name
