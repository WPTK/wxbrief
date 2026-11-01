"""Language in the running app: the Settings dialog switches it live, the choice is saved, and bindings, labels and
toasts follow the catalog."""

from __future__ import annotations

import importlib
import pkgutil
import tomllib
from dataclasses import replace
from pathlib import Path

import pytest
from test_app_smoke import METARS, TAFS, _no_network, make_app, notes  # noqa: F401
from textual.widgets import Footer, OptionList

from wxbrief.__main__ import build_tui_parser, tui_options
from wxbrief.app import WxBriefApp
from wxbrief.config import save_config
from wxbrief.data.models import parse_metars, parse_tafs
from wxbrief.data.poll import Product
from wxbrief.i18n import LANGUAGES, Translator
from wxbrief.i18n.keys import K
from wxbrief.ui.bindings import translator_of
from wxbrief.ui.screens.briefing import BriefingScreen
from wxbrief.ui.screens.settings import EDITABLE, SettingsScreen
from wxbrief.ui.widgets.status_bar import StatusBar


def load_reports(app: WxBriefApp) -> None:
    app.state.apply(Product.METAR, parse_metars(METARS))
    app.state.apply(Product.TAF, parse_tafs(TAFS))
    app.briefing.refresh_view()


def make_saving_app(tmp_path: Path, ids: list[str]) -> WxBriefApp:
    """An app whose run-time view is a copy of the config's, as the command line builds it (flags never save)."""
    app = make_app(tmp_path, ids)
    app.options.view = replace(app.options.config.view)
    return app


def descriptions(app: WxBriefApp) -> set[str]:
    """Every binding description the active screen's footer would show."""
    return {binding.description for _, binding, _, _ in app.screen.active_bindings.values() if binding.show}


def test_every_setting_value_has_a_label_in_every_language() -> None:
    values = {
        "units": ("us", "metric", "mixed"),
        "time": ("station", "local", "zulu"),
        "glyphs": ("ascii", "unicode", "emoji", "nerd"),
        "layout": ("list", "grid"),
    }
    for lang in LANGUAGES:
        t = Translator.load(lang)
        for group, names in values.items():
            for name in names:
                key = f"ui.option.{group}.{name}"
                assert key in t.keys, f"{lang}: {key}"


def test_the_settings_rows_have_labels() -> None:
    assert [name for name, _ in EDITABLE] == ["lang", "units", "time", "glyph_set"]


async def test_settings_switches_the_language_live_and_saves_it(tmp_path: Path) -> None:
    app = make_saving_app(tmp_path, ["KDEN", "EGLL"])
    async with app.run_test(size=(130, 40)) as pilot:
        load_reports(app)
        await pilot.pause()
        assert "Add" in descriptions(app)
        await pilot.press("S")
        await pilot.pause()
        assert isinstance(app.screen, SettingsScreen)
        assert app.screen.query_one(OptionList).highlighted == 0  # the language row comes first
        await pilot.press("enter")
        await pilot.pause()
        assert app.ctx.translator.lang == "es"
        assert app.screen.query_one("#settings-title").render().plain == "Ajustes"  # type: ignore[attr-defined]
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, BriefingScreen)
        assert "Añadir" in descriptions(app) and "Add" not in descriptions(app)
        assert "Salir" in descriptions(app)
    saved = tomllib.loads((tmp_path / "config.toml").read_text(encoding="utf-8"))
    assert saved["view"]["lang"] == "es"


async def test_every_language_draws_the_whole_app(tmp_path: Path) -> None:
    app = make_app(tmp_path, ["KDEN", "EGLL"])
    async with app.run_test(size=(130, 40)) as pilot:
        load_reports(app)
        await pilot.pause()
        for lang in LANGUAGES:
            app.apply_setting("lang", lang)
            await pilot.pause()
            t = Translator.load(lang)
            assert app.ctx.translator.lang == lang
            assert t.t(K.UI_STATUS_POLLING_OFF) in str(app.briefing.query_one(StatusBar).render())
            assert t.t(K.UI_BINDING_ADD_STATION) in descriptions(app)
            assert t.t(K.UI_BINDING_QUIT) in descriptions(app)
        app.apply_setting("lang", "en")


async def test_detail_labels_follow_the_language(tmp_path: Path) -> None:
    app = make_app(tmp_path, ["KDEN"])
    async with app.run_test(size=(130, 40)) as pilot:
        load_reports(app)
        await pilot.pause()
        app.apply_setting("lang", "de")
        await pilot.pause()
        text = "\n".join(str(w.render()) for w in app.screen.query("Static"))
        assert "Wolkenuntergrenze" in text
        assert "Flight category" not in text


async def test_toasts_use_the_language(tmp_path: Path) -> None:
    app = make_app(tmp_path, ["KDEN"])
    async with app.run_test(size=(130, 40)) as pilot:
        app.apply_setting("lang", "fr")
        await pilot.pause()
        app.add_station("ZZZZ")
        await pilot.pause()
        assert any("Station inconnue ZZZZ" in n for n in notes(app))


async def test_layout_toast_is_translated(tmp_path: Path) -> None:
    app = make_app(tmp_path, ["KDEN"])
    async with app.run_test(size=(130, 40)) as pilot:
        app.apply_setting("lang", "pt")
        await pilot.pause()
        await pilot.press("v")
        await pilot.pause()
        assert any("Exibição em grade" in n for n in notes(app))


async def test_other_settings_cycle_and_save(tmp_path: Path) -> None:
    app = make_saving_app(tmp_path, ["KDEN"])
    before = app.options.view.units
    async with app.run_test(size=(130, 40)) as pilot:
        await pilot.press("S")
        await pilot.pause()
        await pilot.press("down")
        await pilot.press("enter")  # units
        await pilot.pause()
        assert app.ctx.units.value != before
        await pilot.press("escape")
    saved = tomllib.loads((tmp_path / "config.toml").read_text(encoding="utf-8"))
    assert saved["view"]["units"] == app.ctx.units.value


def test_lang_flag_sets_the_start_language(tmp_path: Path) -> None:
    args = build_tui_parser().parse_args(["--no-config", "--lang", "de", "KDEN"])
    assert tui_options(args).view.lang == "de"


def test_lang_flag_rejects_an_unknown_language(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        build_tui_parser().parse_args(["--lang", "xx"])
    assert "unknown language" in capsys.readouterr().err


async def test_demo_runs_in_another_language(tmp_path: Path) -> None:
    args = build_tui_parser().parse_args(["--demo", "--no-config", "--lang", "es"])
    app = WxBriefApp(tui_options(args))
    async with app.run_test(size=(130, 40)) as pilot:
        await pilot.pause()
        assert app.ctx.translator.lang == "es"
        assert any("Demostración" in n for n in notes(app))
        assert "Añadir" in descriptions(app)


async def test_a_saved_language_is_used_at_the_next_start(tmp_path: Path) -> None:
    first = make_app(tmp_path, ["KDEN"])
    first.options.view.lang = "de"
    assert save_config(first.options.config, tmp_path / "config.toml")
    args = build_tui_parser().parse_args(["--config", str(tmp_path / "config.toml")])
    options = tui_options(args)
    options.poll, options.cache_dir = False, tmp_path / "cache"
    second = WxBriefApp(options)
    async with second.run_test(size=(130, 40)) as pilot:
        await pilot.pause()
        assert second.ctx.translator.lang == "de"
        assert "Hinzufügen" in descriptions(second)


async def test_every_binding_carries_a_catalog_id(tmp_path: Path) -> None:
    app = make_app(tmp_path, ["KDEN"])
    english = Translator.load("en")
    async with app.run_test(size=(130, 40)) as pilot:
        await pilot.pause()
        for node in (app, app.screen, *app.screen.query("*")):
            for bindings in node._bindings.key_to_bindings.values():
                for binding in bindings:
                    if binding.id and binding.id.startswith("ui.binding."):
                        assert english.t(binding.id) != binding.id
                        assert translator_of(node).lang == "en"
        assert app.screen.query(Footer)


def test_every_binding_of_ours_has_a_catalog_id() -> None:
    """The label of a binding comes from the catalog by its id, so a plain ``Binding`` stays English in every language.
    Scans every class of the UI (screens and dialogs included), not just the widgets of one running screen."""
    from textual.binding import Binding
    from textual.dom import DOMNode

    import wxbrief.ui as ui

    english = Translator.load("en")
    bare: list[str] = []
    for module_info in pkgutil.walk_packages(ui.__path__, "wxbrief.ui."):
        module = importlib.import_module(module_info.name)
        for name, cls in vars(module).items():
            if not (isinstance(cls, type) and issubclass(cls, DOMNode) and cls.__module__ == module.__name__):
                continue
            for item in cls.__dict__.get("BINDINGS", []):
                if not isinstance(item, Binding) or not item.id or english.t(item.id) == item.id:
                    bare.append(f"{module.__name__}.{name}: {item}")
    assert not bare, bare
