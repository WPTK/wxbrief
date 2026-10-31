"""Colourways in the running app: cycling, the picker, persistence, the --theme flag and CLI/TUI colour parity."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from rich.text import Text
from test_app_smoke import HELP_TEXT, METARS, TAFS, _no_network, make_app  # noqa: F401
from textual.widgets import OptionList, Static

from wxbrief.__main__ import build_tui_parser, tui_options
from wxbrief.app import WxBriefApp
from wxbrief.config import Config, save_config
from wxbrief.data.models import parse_metars, parse_tafs
from wxbrief.data.poll import Product
from wxbrief.render.palette import Palette, all_themes
from wxbrief.ui.screens.briefing import BriefingScreen
from wxbrief.ui.screens.theme_picker import ThemePickerScreen
from wxbrief.ui.themes import AVIATION_THEMES, THEME_CYCLE
from wxbrief.ui.themes.semantic import SEMANTIC_DEFAULTS, semantic_variables
from wxbrief.ui.widgets.detail import RawReport
from wxbrief.ui.widgets.status_bar import StatusBar


def load_reports(app: WxBriefApp) -> None:
    app.state.apply(Product.METAR, parse_metars(METARS))
    app.state.apply(Product.TAF, parse_tafs(TAFS))
    app.briefing.refresh_view()


def saved_theme(path: Path) -> str | None:
    if not path.exists():
        return None
    theme = tomllib.loads(path.read_text(encoding="utf-8")).get("view", {}).get("theme")
    return theme if isinstance(theme, str) else None


def wind_color(app: WxBriefApp) -> str | None:
    """The colour of the wind group in the highlighted KDEN METAR, as the raw-report widget got it."""
    content = app.screen.query_one(RawReport).content
    assert isinstance(content, Text)
    for span in content.spans:
        if content.plain[span.start : span.end].endswith("KT") and not isinstance(span.style, str):
            color = span.style.color
            return color.get_truecolor().hex if color else None
    return None


def test_the_help_lists_the_theme_keys() -> None:
    assert "next theme" in HELP_TEXT and "pick a theme" in HELP_TEXT


async def test_every_theme_is_registered_and_applies(tmp_path: Path) -> None:
    app = make_app(tmp_path, ["KDEN"])
    async with app.run_test(size=(120, 36)) as pilot:
        for theme in AVIATION_THEMES:
            assert theme.name in app.available_themes
        load_reports(app)
        await pilot.pause()
        seen: set[str | None] = set()
        for name in THEME_CYCLE:
            app.theme = name
            await pilot.pause()
            assert app.current_theme.name == name
            assert name in str(app.screen.query_one(StatusBar).render())
            seen.add(wind_color(app))
        # every theme re-colours the raw text; the colour changes at least as often as the palette says it can
        expected = {Palette.from_theme(app.available_themes[name]).hex("wx-wind").upper() for name in THEME_CYCLE}
        assert {c.upper() for c in seen if c} == expected


async def test_t_cycles_through_the_themes_in_order(tmp_path: Path) -> None:
    app = make_app(tmp_path, ["KDEN"])
    async with app.run_test(size=(120, 36)) as pilot:
        assert app.theme == "textual-dark"
        start = THEME_CYCLE.index("textual-dark")
        for step in range(1, len(THEME_CYCLE) + 1):
            await pilot.press("t")
            await pilot.pause()
            assert app.theme == THEME_CYCLE[(start + step) % len(THEME_CYCLE)]
        assert app.theme == "textual-dark"


async def test_the_picker_previews_keeps_and_reverts(tmp_path: Path) -> None:
    app = make_app(tmp_path, ["KDEN"])
    config = tmp_path / "config.toml"
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.press("T")
        await pilot.pause()
        assert isinstance(app.screen, ThemePickerScreen)
        await pilot.press("down")
        await pilot.pause()
        assert app.theme == THEME_CYCLE[THEME_CYCLE.index("textual-dark") + 1]
        await pilot.press("down")
        await pilot.pause()
        assert app.theme == THEME_CYCLE[THEME_CYCLE.index("textual-dark") + 2]
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, BriefingScreen)
        assert app.theme == "textual-dark"  # reverted
        assert saved_theme(config) is None  # previewing saved nothing

        await pilot.press("T")
        await pilot.pause()
        await pilot.press("up", "up")  # textual-dark is first among the built-ins; up moves into the aviation themes
        await pilot.pause()
        picked = app.theme
        assert picked != "textual-dark"
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, BriefingScreen)
        assert app.theme == picked
        assert saved_theme(config) == picked


async def test_the_picker_cannot_be_opened_twice(tmp_path: Path) -> None:
    app = make_app(tmp_path, ["KDEN"])
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.press("T")
        await pilot.pause()
        await pilot.press("T")
        await pilot.pause()
        assert isinstance(app.screen, ThemePickerScreen)
        assert len(app.screen_stack) == 3  # default screen, briefing, picker
        assert app.screen.query_one(OptionList).option_count == len(THEME_CYCLE)


async def test_a_chosen_theme_is_saved_and_loaded_next_time(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    first = make_app(tmp_path, ["KDEN"])
    async with first.run_test(size=(100, 30)) as pilot:
        await pilot.press("t")
        await pilot.pause()
        chosen = first.theme
        assert chosen == THEME_CYCLE[THEME_CYCLE.index("textual-dark") + 1]
    assert saved_theme(config) == chosen

    options = tui_options(build_tui_parser().parse_args(["--config", str(config)]))
    options.cache_dir = tmp_path / "cache"
    options.poll = False
    second = WxBriefApp(options)
    async with second.run_test(size=(100, 30)):
        assert second.theme == chosen
    assert saved_theme(config) == chosen


async def test_the_flag_theme_is_never_written_back(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    args = build_tui_parser().parse_args(["--theme", "phosphor-green", "--config", str(config_path)])
    options = tui_options(args)
    assert options.view.theme == "phosphor-green" and options.config.view.theme == "textual-dark"
    assert options.theme_from_flag
    options.cache_dir = tmp_path / "cache"
    options.poll = False
    app = WxBriefApp(options)
    async with app.run_test(size=(100, 30)) as pilot:
        assert app.theme == "phosphor-green"
        await pilot.press("t")
        await pilot.pause()
        assert app.theme != "phosphor-green"
        await pilot.press("a")  # a save for another reason still leaves the theme alone
        await pilot.press("escape")
    assert saved_theme(config_path) is None


async def test_a_change_made_while_the_config_is_unreadable_is_not_saved(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("this is [not toml", encoding="utf-8")
    args = build_tui_parser().parse_args(["--config", str(config_path)])
    options = tui_options(args)
    assert not options.config_usable
    options.cache_dir = tmp_path / "cache"
    options.poll = False
    app = WxBriefApp(options)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press("t")
        await pilot.pause()
    assert config_path.read_text(encoding="utf-8") == "this is [not toml"


async def test_no_config_never_writes(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    args = build_tui_parser().parse_args(["--no-config", "--config", str(config_path)])
    options = tui_options(args)
    options.cache_dir = tmp_path / "cache"
    options.poll = False
    app = WxBriefApp(options)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press("t")
        await pilot.pause()
    assert not config_path.exists()


async def test_a_saved_unknown_theme_falls_back_with_a_notice_and_is_kept(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config = Config()
    config.view.theme = "no-such-theme"
    assert save_config(config, config_path)
    args = build_tui_parser().parse_args(["--config", str(config_path)])
    options = tui_options(args)
    options.cache_dir = tmp_path / "cache"
    options.poll = False
    app = WxBriefApp(options)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        assert app.theme == "textual-dark"
        assert any("no-such-theme" in n.message for n in app._notifications)
        await pilot.press("a")
        await pilot.press("escape")
    assert saved_theme(config_path) == "no-such-theme"


def test_the_flag_rejects_an_unknown_theme(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stopped:
        build_tui_parser().parse_args(["--theme", "nope"])
    assert stopped.value.code == 2
    error = capsys.readouterr().err
    assert "unknown theme 'nope'" in error and "paper-chart" in error


@pytest.mark.parametrize("name", ["paper-chart", "phosphor-green", "nord", "high-contrast-light"])
async def test_tui_colours_equal_the_cli_colours(tmp_path: Path, name: str) -> None:
    """For each highlight kind: CSS variable = Rich style the raw text uses = what ``decode --theme`` prints."""
    theme = all_themes()[name]
    cli = Palette.from_theme(theme).rich_theme.styles
    app = make_app(tmp_path, ["KDEN"])
    app.theme = name
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        variables = app.get_css_variables()
        palette = app.ctx.palette
        for key in SEMANTIC_DEFAULTS:
            style_name = key.replace("-", ".", 1)
            tui = palette.style(style_name).color
            assert tui is not None and variables[key].lower() == tui.get_truecolor().hex.lower(), key
            assert cli[style_name].color == tui, key
        for key in semantic_variables(theme.dark):
            assert variables[key].lower() == Palette.from_theme(theme).hex(key), key
        # the badge fill is the fixed flight-category colour and its text is readable on it
        badge = palette.style("fcat.ifr.badge")
        assert badge.bgcolor is not None and badge.bgcolor.get_truecolor().hex.lower() == variables["fcat-ifr"].lower()
        assert cli["fcat.ifr.badge"] == badge


async def test_stylesheet_classes_resolve_to_the_fixed_colours(tmp_path: Path) -> None:
    app = make_app(tmp_path, ["KDEN"])
    async with app.run_test(size=(100, 30)) as pilot:
        for name in ("paper-chart", "cockpit-night"):
            app.theme = name
            chip = Static("IFR", classes="fcat-ifr")
            await app.screen.mount(chip)
            await pilot.pause()
            assert chip.styles.background.hex.lower() == app.get_css_variables()["fcat-ifr"].lower()
            assert chip.styles.color.automatic
            await chip.remove()


async def test_ansi_themes_are_not_available(tmp_path: Path) -> None:
    """They use the terminal's own colours, which the highlight palette cannot be built from."""
    app = make_app(tmp_path, ["KDEN"])
    async with app.run_test(size=(100, 30)):
        assert "ansi-dark" not in app.available_themes and "ansi-light" not in app.available_themes
        assert "textual-dark" in app.available_themes and "nord" in app.available_themes
    with pytest.raises(SystemExit):
        build_tui_parser().parse_args(["--theme", "ansi-dark"])
