"""ViewContext time handling: the zone of each time mode."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from wxbrief.data.stations import bundled
from wxbrief.decode.units import UnitsMode
from wxbrief.i18n import Translator
from wxbrief.ui.context import ViewContext

MOMENT = datetime(2026, 10, 31, 14, 53, tzinfo=UTC)
DENVER = ZoneInfo("America/Denver")


def context(mode: str) -> ViewContext:
    return ViewContext(
        app=None,  # type: ignore[arg-type]
        translator=Translator.load("en"),
        units=UnitsMode.MIXED,
        glyphs=None,  # type: ignore[arg-type]
        time_mode=mode,
        stations=bundled(),
        local_zone=DENVER,
    )


def test_local_mode_uses_the_computer_zone() -> None:
    ctx = context("local")
    shifted = ctx.localize(MOMENT, "EGLL")
    assert shifted.utcoffset() == DENVER.utcoffset(datetime(2026, 10, 31, 14, 53))
    assert shifted.hour == 8 and ctx.clock(MOMENT, "EGLL") == "08:53 MDT"
    assert not ctx.is_zulu("EGLL")


def test_zulu_and_station_modes() -> None:
    assert context("zulu").clock(MOMENT) == "14:53Z"
    assert context("station").clock(MOMENT, "EGLL") == "14:53 GMT"
    assert context("station").clock(MOMENT, "KDEN") == "08:53 MDT"
    assert context("station").clock(MOMENT, "ZZZZ") == "14:53Z"  # no known zone: zulu
