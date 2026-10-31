"""The shipped catalogs: every language has every key, placeholders and plural tables line up, numbers and the
``--lang`` flag work. English is the reference; the others are checked against it."""

from __future__ import annotations

import re
import string
from pathlib import Path

import pytest

from wxbrief.__main__ import main
from wxbrief.decode.units import UnitsMode
from wxbrief.i18n import LANGUAGES, Catalog, Translator, _read_catalog, fallback_chain, resolve_language
from wxbrief.i18n.keys import K
from wxbrief.i18n.numbers import ENGLISH, NumberFormat
from wxbrief.i18n.plurals import RULE_CATEGORIES, RULES, plural_category
from wxbrief.render.measure import format_decimal, format_pressure_change

OTHER_LANGUAGES = tuple(lang for lang in LANGUAGES if lang != "en")
LOCALES = Path(__file__).parent.parent / "wxbrief" / "i18n" / "locales"
RMK_METAR = (
    "METAR KDEN 131453Z 06007KT 3/4SM BR OVC003 09/08 A3001 RMK AO2 PK WND 05030/1442 TSB35 "
    "SLP165 P0001 T00890078 CB DSNT W"
)
# Words that only English uses; none may appear in a decode in another language.
ENGLISH_ONLY = ("Remarks", "reporting", "Peak", "Surface", "Observed", "Temperature", "Pressure", "ceiling", "began")


def load(lang: str) -> Catalog:
    catalog = _read_catalog(lang)
    assert catalog is not None, lang
    return catalog


def fields(entry: str | dict[str, str]) -> set[str]:
    """Placeholder names with their format specs, over every form of the entry."""
    texts = [entry] if isinstance(entry, str) else list(entry.values())
    found: set[str] = set()
    for text in texts:
        for _, name, spec, conversion in string.Formatter().parse(text):
            if name is not None:
                found.add(f"{name}!{conversion or ''}:{spec or ''}")
    return found


def test_the_language_list_matches_the_files() -> None:
    assert sorted(path.stem for path in LOCALES.glob("*.toml")) == sorted(LANGUAGES)


@pytest.mark.parametrize("lang", OTHER_LANGUAGES)
def test_every_locale_has_exactly_the_english_keys(lang: str) -> None:
    english, catalog = load("en"), load(lang)
    assert sorted(set(english.entries) - set(catalog.entries)) == []
    assert sorted(set(catalog.entries) - set(english.entries)) == []


@pytest.mark.parametrize("lang", OTHER_LANGUAGES)
def test_placeholders_and_entry_shapes_match_english(lang: str) -> None:
    english, catalog = load("en"), load(lang)
    for key, reference in english.entries.items():
        entry = catalog.entries[key]
        assert isinstance(entry, str) == isinstance(reference, str), f"{lang}: {key} changes between plain and plural"
        assert fields(entry) == fields(reference), f"{lang}: {key} placeholders differ"


@pytest.mark.parametrize("lang", LANGUAGES)
def test_plural_tables_are_valid(lang: str) -> None:
    catalog = load(lang)
    rule = str(catalog.meta["plural_rule"])
    assert rule in RULES
    for key, entry in catalog.entries.items():
        if isinstance(entry, dict):
            assert "other" in entry, f"{lang}: {key} has no 'other' form"
            assert set(entry) <= set(RULE_CATEGORIES[rule]), f"{lang}: {key} uses categories the rule never returns"
            assert set(RULE_CATEGORIES[rule]) <= set(entry), f"{lang}: {key} lacks a form its rule can pick"


@pytest.mark.parametrize("lang", LANGUAGES)
def test_meta_is_complete(lang: str) -> None:
    meta = load(lang).meta
    for name in ("language", "status", "plural_rule", "decimal", "group", "clock"):
        assert meta.get(name), f"{lang}: [meta] {name}"
    assert meta["status"] in {"complete", "seeded"}
    assert len(str(meta["decimal"])) == 1


@pytest.mark.parametrize("lang", OTHER_LANGUAGES)
def test_a_catalog_is_translated_not_copied(lang: str) -> None:
    english, catalog = load("en"), load(lang)
    same = [key for key, entry in catalog.entries.items() if entry == english.entries[key]]
    assert len(same) < len(english.entries) * 0.12, f"{lang}: {len(same)} entries equal English: {same[:20]}"


@pytest.mark.parametrize("lang", OTHER_LANGUAGES)
def test_translated_values_are_single_lines_except_the_help(lang: str) -> None:
    for key, entry in load(lang).entries.items():
        if key != K.UI_HELP_BODY:
            texts = [entry] if isinstance(entry, str) else list(entry.values())
            assert all("\n" not in text and text.strip() == text and text for text in texts), f"{lang}: {key}"


def test_the_help_body_has_the_same_lines_in_every_language() -> None:
    reference = str(load("en").entries[K.UI_HELP_BODY]).splitlines()
    for lang in OTHER_LANGUAGES:
        lines = str(load(lang).entries[K.UI_HELP_BODY]).splitlines()
        assert len(lines) == len(reference), lang
        assert [line.startswith("[b]") for line in lines] == [line.startswith("[b]") for line in reference], lang


# --- numbers -------------------------------------------------------------------------------------------------------


def test_number_formats_per_language() -> None:
    assert ENGLISH.integer(12000) == "12,000" and ENGLISH.fixed(29.92, 2) == "29.92"
    de, fr, es, pt = (Translator.load(lang).numbers for lang in ("de", "fr", "es", "pt"))
    assert (de.integer(12000), de.fixed(1013.2, 1), de.trimmed(1.0)) == ("12.000", "1013,2", "1")
    assert fr.integer(12000) == "12 000" and fr.fixed(29.92, 2) == "29,92"  # noqa: RUF001
    assert es.integer(3000) == "3000" and es.integer(12000) == "12.000"
    assert pt.integer(3000) == "3.000" and pt.trimmed(0.75, 2) == "0,75"
    assert de.integer(-4500) == "-4.500"


def test_bad_number_meta_stays_english() -> None:
    assert NumberFormat.from_meta({"decimal": "", "group": 3, "min_grouping": True}) == ENGLISH


def test_measures_use_the_language_separators() -> None:
    fr = Translator.load("fr").numbers
    assert format_decimal(1013.2, 1, fr) == "1013,2"
    assert format_decimal(1013.2, 1) == "1013.2"
    assert format_pressure_change(2.5, UnitsMode.METRIC, fr).count(",") >= 1
    assert "," not in format_pressure_change(2.5, UnitsMode.METRIC)


# --- plurals -------------------------------------------------------------------------------------------------------


def test_plural_rules() -> None:
    assert [plural_category("one_other", n) for n in (0, 1, 2)] == ["other", "one", "other"]
    assert [plural_category("one_below_two", n) for n in (0, 1, 1.5, 2)] == ["one", "one", "one", "other"]
    assert plural_category("no_such_rule", 1) == "one"


@pytest.mark.parametrize(
    ("lang", "zero", "one", "two"),
    [
        ("en", "0 warnings", "1 warning", "2 warnings"),
        ("es", "0 advertencias", "1 advertencia", "2 advertencias"),
        ("fr", "0 avertissement", "1 avertissement", "2 avertissements"),
        ("de", "0 Warnungen", "1 Warnung", "2 Warnungen"),
        ("pt", "0 aviso", "1 aviso", "2 avisos"),
    ],
)
def test_warning_heading_plurals(lang: str, zero: str, one: str, two: str) -> None:
    t = Translator.load(lang)
    assert [t.plural(K.WARN_HEADING, n) for n in (0, 1, 2)] == [zero, one, two]


# --- language codes ------------------------------------------------------------------------------------------------


def test_resolve_language() -> None:
    assert resolve_language("de") == "de"
    assert resolve_language("DE") == "de"
    assert resolve_language("pt-BR") == "pt"
    assert resolve_language("pt_br") == "pt"
    assert resolve_language("xx") is None
    assert resolve_language("../en") is None


def test_regional_codes_fall_back_to_the_language() -> None:
    assert fallback_chain("es-MX") == ["es-MX", "es", "en"]
    assert Translator.load("es-MX").lang == "es"
    assert Translator.load("zz").lang == "en"


def test_keep_case_only_for_german() -> None:
    assert Translator.load("de").lower_first("Feuchter Dunst") == "Feuchter Dunst"
    assert Translator.load("fr").lower_first("Brume") == "brume"
    assert Translator.load("en").lower_first("CAVOK") == "CAVOK"


# --- decoded output ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("lang", OTHER_LANGUAGES)
def test_a_rmk_heavy_metar_has_no_english_left(lang: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["decode", "--lang", lang, "--date", "2026-10-13", RMK_METAR]) == 0
    out = capsys.readouterr().out
    for word in ENGLISH_ONLY:
        assert not re.search(rf"\b{word}\b", out), f"{lang}: {word!r} in the decode"
    assert out.splitlines()[0].startswith(Translator.load(lang).t(K.LABEL_STATION))


def test_decode_in_german_uses_decimal_commas(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["decode", "--lang", "de", "--date", "2026-10-13", RMK_METAR]) == 0
    out = capsys.readouterr().out
    assert "30,01 inHg" in out and "1,2 km" in out


def test_lang_works_before_and_after_the_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--lang", "fr", "decode", "--date", "2026-10-13", RMK_METAR]) == 0
    before = capsys.readouterr().out
    assert main(["decode", "--lang", "fr", "--date", "2026-10-13", RMK_METAR]) == 0
    assert capsys.readouterr().out == before
    assert "Vent" in before


def test_decode_defaults_to_english(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["decode", "--date", "2026-10-13", RMK_METAR]) == 0
    assert "Flight category:" in capsys.readouterr().out


def test_an_unknown_language_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stop:
        main(["decode", "--lang", "xx", RMK_METAR])
    assert stop.value.code == 2
    assert "unknown language 'xx'" in capsys.readouterr().err


def test_tui_help_text_is_translated() -> None:
    parser_help = {lang: Translator.load(lang).t(K.CLI_HELP_DEMO) for lang in LANGUAGES}
    assert len(set(parser_help.values())) == len(LANGUAGES)
