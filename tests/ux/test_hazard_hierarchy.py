"""(a) Flight-category hazard hierarchy: VFR/MVFR/IFR/LIFR must differ by more than colour, in every surface."""

from __future__ import annotations

import unicodedata

import pytest
from ux_kit import make_app

from wxbrief.decode.model import FlightCategory
from wxbrief.render.palette import Palette, all_themes
from wxbrief.ui.glyphs import GLYPH_SETS, glyphs_for
from wxbrief.ui.style import ViewPalette

CATEGORIES = list(FlightCategory)


def view_palette(theme: str) -> ViewPalette:
    return ViewPalette(Palette.from_theme(all_themes()[theme]))


@pytest.mark.parametrize("theme", ["textual-dark", "textual-light", "paper-chart", "phosphor-green"])
def test_badge_carries_the_category_name_not_only_a_colour(theme: str) -> None:
    view = view_palette(theme)
    texts = {c: view.badge(c).plain.strip() for c in CATEGORIES}
    assert texts == {c: c.value for c in CATEGORIES}
    assert len(set(texts.values())) == 4
    assert view.badge(None).plain.strip() == "--"


def _linear(v: float) -> float:
    v /= 255
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


# Machado 2009, severity 1.0, on linear RGB.
CVD = {
    "protan": ((0.152286, 1.052583, -0.204868), (0.114503, 0.786281, 0.099216), (-0.003882, -0.048116, 1.051998)),
    "deutan": ((0.367322, 0.860646, -0.227968), (0.280085, 0.672501, 0.047413), (-0.011820, 0.042940, 0.968881)),
    "tritan": ((1.255528, -0.076749, -0.178779), (-0.078411, 0.930809, 0.147602), (0.004733, 0.691367, 0.303900)),
}


def _lab(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    r, g, b = (min(1.0, max(0.0, c)) for c in rgb)
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    return 116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))


def _simulate(hex6: str, kind: str) -> tuple[float, float, float]:
    rgb = [_linear(int(hex6[i : i + 2], 16)) for i in (1, 3, 5)]
    m = CVD[kind]
    return _lab(tuple(sum(m[row][col] * rgb[col] for col in range(3)) for row in range(3)))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("theme", "kind"),
    [
        (t, k)
        for t in ("textual-dark", "textual-light")
        for k in sorted(CVD)
    ],
)
def test_category_fills_stay_distinct_under_colour_blindness(theme: str, kind: str) -> None:
    """Informational floor (CIE76 dE >= 10): with the text code in every badge this is a second channel, not the only one."""
    palette = Palette.from_theme(all_themes()[theme])
    labs = {c: _simulate(palette.hex(f"fcat-{c.value.lower()}"), kind) for c in CATEGORIES}
    close = []
    for i, a in enumerate(CATEGORIES):
        for b in CATEGORIES[i + 1 :]:
            d = sum((x - y) ** 2 for x, y in zip(labs[a], labs[b], strict=True)) ** 0.5
            if d < 10:
                close.append(f"{a.value}/{b.value} dE={d:.1f}")
    assert not close, close


def _shape(char: str) -> str:
    """The glyph's Unicode name without its colour word: two marks with the same shape name differ by colour alone."""
    name = unicodedata.name(char[0], f"U+{ord(char[0]):04X}")
    colours = ["GREEN", "ORANGE", "RED", "YELLOW", "LARGE", "MEDIUM"]
    if ord(char[0]) >= 0x2600:  # emoji: WHITE is a colour there, but BLACK/WHITE CIRCLE in the geometric block is fill
        colours.append("WHITE")
    for colour in colours:
        name = name.replace(colour, "")
    return " ".join(name.split())


@pytest.mark.parametrize(
    "glyph_set",
    GLYPH_SETS,
)
def test_freshness_marks_differ_in_shape_not_only_colour(glyph_set: str) -> None:
    g = glyphs_for(glyph_set)
    shapes = [_shape(g.fresh), _shape(g.stale), _shape(g.missing)]
    assert len(set(shapes)) == 3, shapes


async def test_timeline_overlay_row_has_a_non_colour_category_marker(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from ux_kit import load, rows

    from wxbrief.ui.widgets.taf_timeline import TafTimeline

    app = make_app(tmp_path, ["KDEN"])
    async with app.run_test(size=(120, 40)) as pilot:
        load(app, rows("metar_kden_egll"), rows("taf_kden_egll"))
        await pilot.pause()
        timeline = app.screen.query_one(TafTimeline)
        assert any(cell.overlay for cell in timeline.cells), "fixture must have a TEMPO/PROB group"
        overlay_row = str(timeline.render()).split("\n")[2]
        assert any(ch.isalpha() for ch in overlay_row), repr(overlay_row)
