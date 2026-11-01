"""A cancelled TAF that still carries period groups (an AWC feed row with ``CNL`` in ``remarks``) reads as cancelled.

The groups are dropped from the model, so no renderer can present them as a forecast.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from corpus import awc_taf_rows
from rich.console import Console

from wxbrief.__main__ import main
from wxbrief.data.awc import BASE_URL
from wxbrief.data.models import parse_tafs
from wxbrief.decode.model import Modifier, Taf
from wxbrief.decode.taf import parse_taf
from wxbrief.decode.units import UnitsMode
from wxbrief.i18n import Translator
from wxbrief.render.discord import discord_block
from wxbrief.render.jsonout import to_dict
from wxbrief.render.plain import render_plain, taf_blocks, taf_header_rows
from wxbrief.render.richtext import build_renderable
from wxbrief.state import StationReports, decode_taf_row
from wxbrief.ui.context import ViewContext
from wxbrief.ui.widgets.detail import DetailPane

NOW = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
FIXTURES = Path(__file__).parent / "fixtures" / "awc"
EN = Translator.load("en")


def _row() -> dict[str, Any]:
    row = next(r for r in awc_taf_rows() if r["icaoId"] == "KATL")
    assert "FM311500" in row["rawTAF"]  # a real forecast body with change groups
    return {**row, "remarks": "CNL"}


def _cancelled() -> Taf:
    return decode_taf_row(parse_tafs([_row()])[0], NOW)


def test_a_feed_row_marked_cnl_keeps_no_groups() -> None:
    taf = _cancelled()
    assert taf.modifiers == (Modifier.CNL,) and taf.cancelled
    assert taf.base is None and taf.changes == () and taf.periods == ()
    assert taf.worst_category is None and taf.temperatures == ()
    assert "FM311500" in taf.raw  # the raw text is untouched


def test_plain_leads_with_cancelled_and_lists_no_group() -> None:
    lines = render_plain(_cancelled(), EN, UnitsMode.US).splitlines()
    assert lines[0].startswith("Notes:") and "Cancelled" in lines[0]
    text = "\n".join(lines)
    for gone in ("Base forecast", "Flight category", "Wind:", "Gusty", "worst"):
        assert gone not in text
    assert "KATL forecast cancelled." in text


def test_rich_leads_with_cancelled_and_lists_no_group() -> None:
    console = Console(file=StringIO(), width=120, color_system=None)
    console.print(build_renderable(_cancelled(), EN, UnitsMode.US))
    lines = [line for line in console.file.getvalue().splitlines() if line.strip()]  # type: ignore[attr-defined]
    table = lines[next(i for i, line in enumerate(lines) if line.startswith("Notes")) :]
    assert "Cancelled" in table[0]
    text = "\n".join(table)
    for gone in ("Base forecast", "Flight category", "Wind ", "VFR"):
        assert gone not in text


def test_json_has_no_groups_and_no_worst_category() -> None:
    document = to_dict(_cancelled())
    assert document["modifiers"] == ["CNL"]
    assert document["base"] is None and document["changes"] == []
    assert document["worst_category"] is None


def test_discord_says_cancelled_and_has_no_group() -> None:
    block = discord_block(_cancelled(), EN, UnitsMode.US)
    assert "CANCELLED" in block and "No forecast groups" in block
    assert "BASE" not in block and "FROM" not in block and "[VFR]" not in block


def test_the_detail_pane_shows_cancelled_first_and_no_blocks() -> None:
    ctx = ViewContext(
        app=None,  # type: ignore[arg-type]
        translator=EN,
        units=UnitsMode.US,
        glyphs=None,  # type: ignore[arg-type]
        time_mode="utc",
        stations={},
        local_zone=UTC,
    )
    rows, blocks = DetailPane._taf_rows(StationReports("KATL", taf=_cancelled()), ctx)
    assert blocks == [] and taf_blocks(_cancelled(), EN, UnitsMode.US) == []
    assert "Cancelled" in rows[0].value
    assert "Cancelled" in taf_header_rows(_cancelled(), EN, UnitsMode.US)[0].value


@pytest.fixture
def awc_cancelled() -> Iterator[respx.MockRouter]:
    taf = json.loads((FIXTURES / "taf_kden_egll.json").read_bytes())
    for record in taf:
        if record["icaoId"] == "KDEN":
            record["remarks"] = "CNL"
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE_URL}/metar").mock(
            return_value=httpx.Response(200, content=(FIXTURES / "metar_kden_egll.json").read_bytes())
        )
        router.get(f"{BASE_URL}/taf").mock(return_value=httpx.Response(200, content=json.dumps(taf).encode()))
        yield router


def test_get_prints_a_cancelled_taf_without_groups(
    awc_cancelled: respx.MockRouter, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["get", "KDEN", "--plain"]) == 0
    out = capsys.readouterr().out
    assert "Cancelled report" in out and "KDEN forecast cancelled." in out
    assert "Base forecast" not in out and "worst flight category" not in out
    assert main(["get", "KDEN", "--json"]) == 0
    taf = json.loads(capsys.readouterr().out)["KDEN"]["taf"]
    assert taf["changes"] == [] and taf["base"] is None and taf["worst_category"] is None


# --- a CNL word in the text after the groups -------------------------------------------------------------------------


def test_a_cnl_word_after_the_groups_withdraws_the_report() -> None:
    """ICAO Annex 3 cancels with ``CNL`` in place of the body; groups before it are malformed, so the safe reading
    is the same one: cancelled, nothing left to present as a forecast, and no unrecognised-group warning."""
    taf = parse_taf("TAF AMD KDEN 311000Z 3110/3118 06007KT 3/4SM BR OVC003 CNL", NOW)
    assert taf.modifiers == (Modifier.AMD, Modifier.CNL) and taf.cancelled
    assert taf.periods == () and taf.worst_category is None and taf.warnings == ()
    assert "Unrecognized" not in render_plain(taf, EN)
