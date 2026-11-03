"""(b) Raw-vs-decoded token alignment: what is coloured in the raw line is the group the decoder read."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from corpus import read_raw, reference_for, report_files
from ux_kit import load, make_app, rows

from wxbrief.decode.metar import parse_metar
from wxbrief.decode.model import SemanticKind
from wxbrief.i18n import Translator
from wxbrief.i18n.keys import K
from wxbrief.render.highlight import style_name
from wxbrief.render.palette import Palette, all_themes
from wxbrief.render.plain import warning_lines
from wxbrief.ui.style import ViewPalette
from wxbrief.ui.widgets.detail import DecodedTable, RawReport

T = Translator.load("en")
FILES = report_files()


def _palette() -> ViewPalette:
    return ViewPalette(Palette.from_theme(all_themes()["textual-dark"]))


@pytest.mark.parametrize("path", FILES, ids=[p.stem for p in FILES])
def test_every_token_span_indexes_its_own_text_in_the_raw_line(path) -> None:  # type: ignore[no-untyped-def]
    metar = parse_metar(read_raw(path), reference_for(path))
    palette = _palette()
    text = palette.raw_text(metar)
    assert text.plain == metar.raw
    for token in metar.tokens:
        assert metar.raw[token.start : token.end].upper() == token.text
        if token.kind is SemanticKind.TERMINATOR:
            continue
        want = palette.style(style_name(token.kind))
        covering = [s for s in text.spans if s.start <= token.start and token.end <= s.end and s.style == want]
        assert covering, (token, want)


def test_unknown_group_is_flagged_in_the_raw_line_and_in_the_decoded_pane() -> None:
    raw = "KDEN 311134Z 32005KT 1/4SM ZZQQ9 FG VV001 07/07 A3001"
    metar = parse_metar(raw, datetime(2026, 10, 31, 12, tzinfo=UTC))
    unknown = [t.text for t in metar.tokens if t.kind is SemanticKind.UNKNOWN]
    assert unknown == ["ZZQQ9"]
    assert any("ZZQQ9" in line for line in warning_lines(metar, T))


async def test_raw_pane_and_decoded_table_show_the_same_report(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = make_app(tmp_path, ["KDEN"])
    async with app.run_test(size=(120, 40)) as pilot:
        load(app, rows("metar_kden_egll"), rows("taf_kden_egll"))
        await pilot.pause()
        entry = app.state.stations["KDEN"]
        assert str(app.screen.query_one(RawReport).render()).startswith(entry.metar.raw)
        table = app.screen.query_one(DecodedTable)
        labels = [str(table.get_row_at(i)[0]) for i in range(table.row_count)]
        assert T.t(K.LABEL_WIND) in labels and table.row_count > 5
