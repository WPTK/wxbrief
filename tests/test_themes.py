"""Colourways: every theme registers, the semantic variables resolve and stay legible, and the CLI palette matches Textual."""

from __future__ import annotations

import pytest
from rich.console import Console
from textual.app import App, ComposeResult
from textual.color import Color
from textual.theme import Theme
from textual.widgets import Static

from wxbrief.render.palette import Palette, all_themes, contrast_ratio
from wxbrief.ui.themes import AVIATION_THEMES, THEME_CYCLE
from wxbrief.ui.themes.semantic import (
    BUILTIN_THEME_NAMES,
    COLOR_STATE_COLORS,
    FLIGHT_CATEGORY_COLORS,
    SEMANTIC_DEFAULTS,
    semantic_variables,
)

THEMES = all_themes()
ALL_THEMES = list(THEMES.values())


class _SemanticApp(App[None]):
    """The injection the real app will do: the palette's resolved semantic variables on top of Textual's own."""

    CSS = "".join(f"#{key} {{ color: ${key}; }}\n" for key in SEMANTIC_DEFAULTS) + "".join(
        f"#{key} {{ color: ${key}; }}\n" for key in semantic_variables(True)
    )

    def get_css_variables(self) -> dict[str, str]:
        return {**super().get_css_variables(), **Palette.from_theme(self.current_theme).css_variables()}

    def compose(self) -> ComposeResult:
        for key in (*SEMANTIC_DEFAULTS, *semantic_variables(True)):
            yield Static("x", id=key)


def test_cycle_names_all_exist() -> None:
    assert len(set(THEME_CYCLE)) == len(THEME_CYCLE)
    assert [theme.name for theme in AVIATION_THEMES] == list(THEME_CYCLE[: len(AVIATION_THEMES)])
    assert all(name in THEMES for name in BUILTIN_THEME_NAMES)


async def test_every_theme_registers_with_an_app() -> None:
    app = App[None]()
    for theme in AVIATION_THEMES:
        app.register_theme(theme)
    async with app.run_test():
        for theme in AVIATION_THEMES:
            assert theme.name in app.available_themes
            app.theme = theme.name
            assert app.current_theme.name == theme.name
            assert app.current_theme.dark is theme.dark


def test_aviation_themes_cover_both_sides() -> None:
    assert {theme.dark for theme in AVIATION_THEMES} == {True, False}
    assert len({theme.name for theme in AVIATION_THEMES}) == 6


@pytest.mark.parametrize("theme", ALL_THEMES, ids=lambda theme: theme.name)
def test_semantic_variables_resolve(theme: Theme) -> None:
    palette = Palette.from_theme(theme)
    for key in (*SEMANTIC_DEFAULTS, *semantic_variables(theme.dark)):
        color = palette.color(key)
        assert color.a == 1.0, key
    assert palette.hex("fcat-ifr") == FLIGHT_CATEGORY_COLORS["ifr"][0 if theme.dark else 1]


@pytest.mark.parametrize("theme", ALL_THEMES, ids=lambda theme: theme.name)
def test_fixed_colors_are_legible_on_the_background(theme: Theme) -> None:
    palette = Palette.from_theme(theme)
    background = palette.color("background")
    for key in semantic_variables(theme.dark):
        ratio = contrast_ratio(palette.color(key), background)
        assert ratio >= 3.0, f"{theme.name}: {key} is {ratio:.2f}:1 on {background.hex}"


def test_fixed_pairs_are_defined_for_both_sides() -> None:
    for pair in (*FLIGHT_CATEGORY_COLORS.values(), *COLOR_STATE_COLORS.values()):
        assert len(pair) == 2 and pair[0] != pair[1]
    assert set(semantic_variables(True)) == set(semantic_variables(False))


def test_theme_variables_override_the_defaults() -> None:
    theme = Theme(name="override", primary="#112233", variables={"wx-wind": "#ff0000"})
    assert Palette.from_theme(theme).hex("wx-wind") == "#ff0000"


def test_references_and_auto_colors_resolve() -> None:
    theme = Theme(name="refs", primary="#112233", background="#000000", dark=True, variables={"wx-vis": "$wx-wind"})
    palette = Palette.from_theme(theme)
    assert palette.hex("wx-vis") == palette.hex("wx-wind")
    # text-muted is "auto 60%": white at 60% over black.
    assert palette.hex("wx-time") == Color(153, 153, 153).hex.lower()


def test_circular_references_are_reported() -> None:
    theme = Theme(name="loop", primary="#112233", variables={"wx-a": "$wx-b", "wx-b": "$wx-a"})
    with pytest.raises(ValueError, match="circular"):
        Palette.from_theme(theme).color("wx-a")


@pytest.mark.parametrize("name", ["cockpit-night", "paper-chart", "nord", "solarized-light"])
async def test_rich_colors_match_textual(name: str) -> None:
    """Each semantic token and fixed colour is the same colour in the Rich theme as on a Textual widget."""
    theme = THEMES[name]
    palette = Palette.from_theme(theme)
    app = _SemanticApp()
    app.register_theme(theme)
    app.theme = name
    async with app.run_test():
        background = palette.color("background")
        for key in (*SEMANTIC_DEFAULTS, *semantic_variables(theme.dark)):
            widget = app.query_one(f"#{key}", Static)
            textual_color = (background + widget.styles.color).with_alpha(1.0)
            expected = palette.color(key)
            assert max(abs(textual_color.r - expected.r), abs(textual_color.g - expected.g), abs(textual_color.b - expected.b)) <= 1, key

    rich = palette.rich_theme.styles
    for key in SEMANTIC_DEFAULTS:
        assert rich[key.replace("-", ".", 1)].color is not None
        assert rich[key.replace("-", ".", 1)].color.get_truecolor().hex.upper() == palette.hex(key).upper(), key  # type: ignore[union-attr]
    for category in FLIGHT_CATEGORY_COLORS:
        style = rich[f"fcat.{category}"]
        assert style.color is not None and style.color.get_truecolor().hex.upper() == palette.hex(f"fcat-{category}").upper()
        badge = rich[f"fcat.{category}.badge"]
        assert badge.bgcolor is not None and badge.bgcolor.get_truecolor().hex.upper() == palette.hex(f"fcat-{category}").upper()


def test_rich_theme_has_every_style_the_renderer_uses() -> None:
    from wxbrief.render.richtext import DEFAULT_THEME

    palette = Palette.from_theme(THEMES["paper-chart"])
    assert set(DEFAULT_THEME.styles) <= set(palette.rich_theme.styles)


def test_decode_with_theme_renders_truecolor(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    from wxbrief.decode.split import parse_any
    from wxbrief.i18n import Translator
    from wxbrief.render.richtext import build_renderable

    report = parse_any("METAR KDEN 131453Z 06007KT 3/4SM BR OVC003 09/08 A3001")[0]
    palette = Palette.from_theme(THEMES["paper-chart"])
    console = Console(theme=palette.rich_theme, force_terminal=True, color_system="truecolor", width=100)
    console.print(build_renderable(report, Translator.load("en")))
    out = capsys.readouterr().out
    wind = palette.color("wx-wind")
    assert f"38;2;{wind.r};{wind.g};{wind.b}" in out


def test_cli_rejects_an_unknown_theme(capsys: pytest.CaptureFixture[str]) -> None:
    from wxbrief.__main__ import main

    assert main(["decode", "--theme", "nope", "METAR KDEN 131453Z 06007KT 10SM CLR 09/08 A3001"]) == 2
    assert "unknown theme 'nope'" in capsys.readouterr().err


def test_cli_accepts_a_known_theme(capsys: pytest.CaptureFixture[str]) -> None:
    from wxbrief.__main__ import main

    assert main(["decode", "--theme", "paper-chart", "--plain", "METAR KDEN 131453Z 06007KT 10SM CLR 09/08 A3001"]) == 0
    assert "KDEN" in capsys.readouterr().out


def test_ansi_themes_are_not_offered() -> None:
    assert "ansi-dark" not in THEMES and "ansi-light" not in THEMES


@pytest.mark.parametrize("theme", ALL_THEMES, ids=lambda theme: theme.name)
def test_every_theme_builds_css_variables(theme: Theme) -> None:
    variables = Palette.from_theme(theme).css_variables()
    assert set(variables) == {*SEMANTIC_DEFAULTS, *semantic_variables(theme.dark)}
    assert all(value.startswith("#") for value in variables.values())


def test_cli_reports_a_theme_that_cannot_be_built(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from textual.color import ColorParseError

    from wxbrief.__main__ import main

    def broken(theme: Theme) -> Palette:
        raise ColorParseError("failed to parse")

    monkeypatch.setattr(Palette, "from_theme", staticmethod(broken))
    assert main(["decode", "--theme", "nord", "METAR KDEN 131453Z 06007KT 10SM CLR 09/08 A3001"]) == 2
    assert "cannot build theme" in capsys.readouterr().err
