"""(b2) Token-by-token view: the pairing of raw tokens with their meaning, and keyboard selection of a token."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from corpus import read_raw, reference_for, report_files
from ux_kit import load, make_app, rows

from wxbrief.decode.metar import parse_metar
from wxbrief.decode.model import SemanticKind
from wxbrief.decode.units import UnitsMode
from wxbrief.i18n import Translator
from wxbrief.render.pairs import token_pairs
from wxbrief.ui.widgets.detail import DetailPane, RawReport, TokenTable

T = Translator.load("en")
FILES = report_files()
RAW = "METAR KDEN 311153Z 18006G12KT 150V210 1 1/2SM -RA BR BKN010 OVC020 08/06 A3004 RMK AO2 SLP135 ZZQQ9 FRZ RAIN="
NOW = datetime(2026, 10, 31, 12, tzinfo=UTC)


def pairs(raw: str = RAW):  # type: ignore[no-untyped-def]
    return token_pairs(parse_metar(raw, NOW), T, UnitsMode.MIXED)


def test_every_group_is_one_pair_with_its_own_meaning() -> None:
    shown = {p.text: p for p in pairs()}
    assert "gusting to 12 kt" in shown["18006G12KT"].meaning
    assert shown["150V210"].meaning == "150°-210°"
    assert shown["1 1/2SM"].kind is SemanticKind.VISIBILITY  # two tokens, one group
    assert shown["-RA"].meaning == "light rain" and shown["BR"].meaning == "mist"
    assert shown["BKN010"].meaning.startswith("Broken") and shown["OVC020"].meaning.startswith("Overcast")
    assert "Dew point" in shown["08/06"].meaning
    assert shown["A3004"].meaning.startswith("30.04 inHg")
    assert shown["SLP135"].meaning.startswith("Sea-level pressure")


def test_pairs_cover_the_report_in_order_without_overlap_and_index_their_own_text() -> None:
    metar = parse_metar(RAW, NOW)
    found = token_pairs(metar, T, UnitsMode.MIXED)
    previous = 0
    for pair in found:
        assert pair.start >= previous
        assert metar.raw[pair.start : pair.end] == pair.text
        previous = pair.end
    assert "=" not in "".join(p.text for p in found[:-1])


def test_unknown_token_is_flagged_with_the_parser_warning() -> None:
    odd = [p for p in pairs("KDEN 311153Z 32005KT 1/4SM ZZQQ9 FG VV001 07/07 A3001") if p.unknown]
    assert [p.text for p in odd] == ["ZZQQ9"]
    assert "ZZQQ9" in odd[0].meaning


def test_remark_without_a_decoder_has_no_meaning_but_is_not_unknown() -> None:
    free = pairs()[-1]
    assert free.text == "ZZQQ9 FRZ RAIN" and free.meaning == "" and not free.unknown


@pytest.mark.parametrize("path", FILES, ids=[p.stem for p in FILES])
def test_corpus_pairs_never_overlap_and_every_unknown_token_is_paired(path) -> None:  # type: ignore[no-untyped-def]
    metar = parse_metar(read_raw(path), reference_for(path))
    found = token_pairs(metar, T, UnitsMode.MIXED)
    assert all(a.end <= b.start for a, b in zip(found, found[1:], strict=False))
    unknown = {t.text for t in metar.tokens if t.kind is SemanticKind.UNKNOWN}
    assert unknown <= {p.text for p in found if p.unknown}


@pytest.mark.parametrize(("size", "columns"), [((80, 24), 1), ((120, 40), 3)])
async def test_stacked_below_100_columns_and_side_by_side_from_100(tmp_path, size, columns) -> None:  # type: ignore[no-untyped-def]
    app = make_app(tmp_path, ["KDEN"])
    async with app.run_test(size=size) as pilot:
        load(app, rows("metar_kden_egll"), rows("taf_kden_egll"))
        await pilot.pause()
        table = app.screen.query_one(TokenTable)
        assert len(table.columns) == columns
        assert table.row_count > 5


async def test_keyboard_selection_marks_the_token_in_the_raw_line(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = make_app(tmp_path, ["KDEN"])
    async with app.run_test(size=(120, 40)) as pilot:
        load(app, rows("metar_kden_egll"), rows("taf_kden_egll"))
        await pilot.pause()
        raw = app.screen.query_one(RawReport)
        table = app.screen.query_one(TokenTable)
        metar = app.state.stations["KDEN"].metar
        assert not _marked(raw)
        app.screen.query_one(DetailPane).focus()
        await pilot.press("4")
        await pilot.pause()
        assert table.has_focus
        first = table.selected
        assert first is not None and _marked(raw) == metar.raw[first.start : first.end]
        await pilot.press("down", "down")
        await pilot.pause()
        picked = table.selected
        assert picked is not first and _marked(raw) == metar.raw[picked.start : picked.end]
        await pilot.press("up")
        await pilot.pause()
        assert table.cursor_row == 1
        app.screen.query_one(DetailPane).focus()
        await pilot.pause()
        assert not _marked(raw)


def _marked(raw: RawReport) -> str:
    text = raw._parts[0].copy() if raw._parts else None
    if text is None or raw._selected is None:
        return ""
    return text.plain[raw._selected[0] : raw._selected[1]]
