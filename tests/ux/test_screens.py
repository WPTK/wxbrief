"""(d) Main briefing screen at 80x24, 120x40 and 200x60: long METAR, many stations, empty and error states.

SVGs live in ``tests/ux/__snapshots__``; regenerate with ``pytest tests/ux/test_screens.py --snapshot-update``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from test_app_smoke import _no_network  # noqa: F401
from ux_kit import load, make_app, rows, screen_lines, station_ids

from wxbrief.data.poll import Product
from wxbrief.ui.widgets.detail import RawReport, StationHeader
from wxbrief.ui.widgets.station_list import StationList

SIZES = [(80, 24), (120, 40), (200, 60)]
_EXPORT_COMMENT = re.compile(r"[ \t]*<!-- Generated with Rich [^>]*-->\r?\n")


@pytest.fixture(autouse=True)
def _plain_screenshots(monkeypatch: pytest.MonkeyPatch) -> None:
    from textual import _doc

    original = _doc.take_svg_screenshot
    monkeypatch.setattr(_doc, "take_svg_screenshot", lambda *a, **k: _EXPORT_COMMENT.sub("", original(*a, **k)))
    monkeypatch.delenv("NO_COLOR", raising=False)


def longest_metar_rows() -> tuple[str, list[dict[str, Any]]]:
    best = max(
        (r for name in ("metar_world_20261031", "metar_europe_20261031", "metar_us_20261031") for r in rows(name)),
        key=lambda r: len(r["rawOb"]),
    )
    return best["icaoId"], [best]


def build(state: str, tmp_path: Path) -> tuple[Any, Any]:
    """The app for ``state`` and a ``run_before`` that loads its data."""
    if state == "long":
        icao, metars = longest_metar_rows()
        app = make_app(tmp_path, [icao])
        taf = [r for name in ("taf_world_20261031", "taf_europe_20261031", "taf_us_20261031") for r in rows(name) if r["icaoId"] == icao]
        data = (metars, taf)
    elif state == "many":
        ids = station_ids("taf_us_20261031", 40)
        app = make_app(tmp_path, ids)
        data = (rows("metar_us_20261031"), rows("taf_us_20261031"))
    elif state == "empty":
        app = make_app(tmp_path, [])
        data = None
    else:  # "error": two network failures, nothing held
        app = make_app(tmp_path, ["KDEN", "EGLL"])
        data = None

    async def before(pilot: Any) -> None:
        if data is not None:
            load(app, *data)
        if state == "error":
            for _ in range(2):
                app.state.record_error(Product.METAR, "metar: down", offline=True)
            app.redraw_screens()
        await pilot.pause()

    return app, before


@pytest.mark.parametrize("state", ["long", "many", "empty", "error"])
@pytest.mark.parametrize("size", SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
def test_briefing_snapshot(snap_compare: Any, tmp_path: Path, state: str, size: tuple[int, int]) -> None:
    app, before = build(state, tmp_path)
    assert snap_compare(app, terminal_size=size, run_before=before)


@pytest.mark.parametrize("size", SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
async def test_long_metar_keeps_every_raw_group_visible(tmp_path: Path, size: tuple[int, int]) -> None:
    app, before = build("long", tmp_path)
    async with app.run_test(size=size) as pilot:
        await before(pilot)
        raw = app.screen.query_one(RawReport)
        region = raw.region
        text = [line[region.x : region.right] for line in screen_lines(app)[region.y : region.bottom]]
        seen = " ".join(text)
        metar = app.state.stations[app.screen.selected].metar
        assert metar is not None
        missing = [t.text for t in metar.tokens if t.text not in seen]
        assert not missing, missing


@pytest.mark.parametrize("size", SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
async def test_many_stations_highlight_stays_inside_the_list(tmp_path: Path, size: tuple[int, int]) -> None:
    app, before = build("many", tmp_path)
    async with app.run_test(size=size) as pilot:
        await before(pilot)
        for _ in range(25):
            await pilot.press("j")
        await pilot.pause()
        option_list = app.screen.query_one(StationList)
        if not option_list.display:  # below 90 columns the list is hidden (#66); the status bar names the position
            n = len(app.state.ids)
            assert f"{n}/{n}" in " ".join(screen_lines(app))
            return
        line = option_list._index_to_line[option_list.highlighted]
        assert option_list.scroll_offset.y <= line < option_list.scroll_offset.y + option_list.scrollable_content_region.height


@pytest.mark.parametrize("state", ["error", "empty"])
async def test_no_orphan_section_heading_when_nothing_is_held(tmp_path: Path, state: str) -> None:
    """With no report the pane shows a 'Raw' heading over nothing (error state) and Add/Remove hints on an empty list."""
    app, before = build(state, tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await before(pilot)
        lines = [line.rstrip() for line in screen_lines(app)]
        pane = "\n".join(line[36:] for line in lines)
        assert not re.search(r"^\W*Raw\s*$", pane, re.M), pane
        if state == "empty":
            assert " d Remove" not in lines[-1], lines[-1]
        assert app.screen.query_one(StationHeader) is not None


@pytest.mark.parametrize("width", [120, 200])
async def test_station_list_name_column_is_aligned(tmp_path: Path, width: int) -> None:
    """The names start in one column however long each row's conditions are (at 120 columns the list is too narrow
    for names: the rows must still all end alike, with none or one start column)."""
    app, before = build("many", tmp_path)
    async with app.run_test(size=(width, 60)) as pilot:
        await before(pilot)
        option_list = app.screen.query_one(StationList)
        starts = set()
        for index in range(option_list.option_count):
            plain = option_list.get_option_at_index(index).prompt.plain
            if "No report" in plain:
                continue
            match = re.search(r"\d{2}SM(?: \$| SPECI)* +(\S)", plain)
            if match is None:
                assert width < 160, plain  # a list this narrow shows no names
                continue
            starts.add(match.start(1))
        assert len(starts) == (1 if width >= 160 else 0), sorted(starts)


async def test_removing_the_last_station_hides_remove_from_the_key_bar(tmp_path: Path) -> None:
    app = make_app(tmp_path, ["KDEN"])
    async with app.run_test(size=(120, 40)) as pilot:
        load(app, rows("metar_kden_egll"), rows("taf_kden_egll"))
        await pilot.pause()
        assert " d Remove" in screen_lines(app)[-1], screen_lines(app)[-1]
        await pilot.press("d")
        await pilot.pause()
        assert not app.state.ids
        assert " d Remove" not in screen_lines(app)[-1], screen_lines(app)[-1]


async def test_decoded_values_start_in_one_column(tmp_path: Path) -> None:
    """``Station``, ``Wind`` and the badge of ``Flight category`` start their values in the same column."""
    app, before = build("many", tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await before(pilot)
        lines = screen_lines(app)
        starts = {}
        for line in lines:
            pane = line[39:]
            match = re.match(r"^\W?\s*(Station|Wind|Flight category)\s{2,}(\S)", pane)
            if match:
                starts[match.group(1)] = match.start(2)
        assert set(starts) == {"Station", "Wind", "Flight category"}, starts
        assert len(set(starts.values())) == 1, starts
