"""Translator, plural rules, key constants and the tables that point into the catalog."""

from __future__ import annotations

import pytest

from wxbrief.decode import tables
from wxbrief.decode.model import (
    CloudType,
    Descriptor,
    Flag,
    FlightCategory,
    Intensity,
    Modifier,
    Phenomenon,
    ReportType,
    RvrTrend,
    SkyCondition,
)
from wxbrief.i18n import Catalog, Translator, fallback_chain, parse_catalog
from wxbrief.i18n.keys import K
from wxbrief.i18n.plurals import plural_category


def constants() -> dict[str, str]:
    return {name: value for name, value in vars(K).items() if name.isupper()}


@pytest.fixture(scope="module")
def english() -> Translator:
    return Translator.load("en")


def test_key_constants_equal_the_english_catalog_exactly(english: Translator) -> None:
    assert set(constants().values()) == set(english.keys)


def test_key_constant_names_follow_the_keys() -> None:
    for name, key in constants().items():
        assert name == key.upper().replace(".", "_")
    assert len(set(constants().values())) == len(constants())


def test_catalog_declares_its_metadata(english: Translator) -> None:
    assert english.lang == "en"
    assert english.meta["status"] == "complete"
    assert english.meta["plural_rule"] == "one_other"
    assert not any(key.startswith("meta.") for key in english.keys)


def test_lookup_and_parameters(english: Translator) -> None:
    assert english.t(K.WIND_CALM) == "Calm"
    assert english.t(K.WIND_STEADY, direction="060", compass="ENE", speed="7 kt") == "From 060° (ENE) at 7 kt"


def test_missing_parameters_stay_visible(english: Translator) -> None:
    assert english.t(K.WIND_STEADY, direction="060") == "From 060° ({compass}) at {speed}"


def test_missing_key_comes_back_as_itself(english: Translator) -> None:
    assert english.t("no.such.key") == "no.such.key"
    assert english.plural("no.such.key", 2) == "no.such.key"


def test_plural_entries(english: Translator) -> None:
    assert english.plural(K.WARN_HEADING, 1) == "1 warning"
    assert english.plural(K.WARN_HEADING, 2) == "2 warnings"
    assert english.plural(K.WARN_HEADING, 0) == "0 warnings"
    assert english.t(K.WARN_HEADING, n=3) == "3 warnings"  # a plural entry read with t() uses "other"


def test_plural_on_a_plain_entry_formats_it(english: Translator) -> None:
    assert english.plural(K.WIND_CALM, 5) == "Calm"


def test_plural_rule() -> None:
    assert plural_category("one_other", 1) == "one"
    assert plural_category("one_other", 0) == "other"
    assert plural_category("one_other", 2) == "other"
    assert plural_category("unknown_rule", 1) == "one"


def test_fallback_chain() -> None:
    assert fallback_chain("en") == ["en"]
    assert fallback_chain("pt") == ["pt", "en"]
    assert fallback_chain("pt-BR") == ["pt-BR", "pt", "en"]
    assert fallback_chain("pt_BR") == ["pt-BR", "pt", "en"]


def test_unknown_language_falls_back_to_english() -> None:
    translator = Translator.load("xx-YY")
    assert translator.lang == "en"
    assert translator.t(K.WIND_CALM) == "Calm"


def test_hostile_language_codes_are_not_paths() -> None:
    assert Translator.load("../../etc/passwd").lang == "en"
    assert Translator.load("").lang == "en"


def test_a_translated_catalog_overrides_and_falls_back_key_by_key() -> None:
    english = Translator.load("en")
    spanish = parse_catalog(
        "es",
        '[meta]\nplural_rule = "one_other"\n[wind]\ncalm = "En calma"\n[warn.heading]\none = "{n} aviso"\nother = "{n} avisos"\n',
    )
    chain = Translator([spanish, *english._catalogs])
    assert chain.lang == "es"
    assert chain.t(K.WIND_CALM) == "En calma"
    assert chain.plural(K.WARN_HEADING, 2) == "2 avisos"
    assert chain.t(K.WIND_NOT_REPORTED) == "Not reported"  # not translated yet: English shows through


def test_parse_catalog_flattens_and_detects_plurals() -> None:
    catalog = parse_catalog(
        "xx",
        '[meta]\nstatus = "seeded"\n[a.b]\nc = "one"\n[a.n]\none = "{n} item"\nother = "{n} items"\n[a.not_plural]\none = "x"\nthing = "y"\n',
    )
    assert isinstance(catalog, Catalog)
    assert catalog.meta == {"status": "seeded"}
    assert catalog.entries == {
        "a.b.c": "one",
        "a.n": {"one": "{n} item", "other": "{n} items"},
        "a.not_plural.one": "x",
        "a.not_plural.thing": "y",
    }


def test_a_translator_needs_a_catalog() -> None:
    with pytest.raises(ValueError, match="at least one catalog"):
        Translator([])


def test_bad_format_specs_do_not_raise() -> None:
    catalog = parse_catalog("xx", '[a]\nb = "{x:d}"\n')
    assert Translator([catalog]).t("a.b", x="not a number") == "{x:d}"


# --- the tables in decode/ point at real catalog keys --------------------------------------------------------------


def table_values() -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for name in dir(tables):
        if name.endswith("_KEYS"):
            for member, key in getattr(tables, name).items():
                out[f"{name}[{member}]"] = key
    return out


def test_every_table_key_exists_in_the_catalog(english: Translator) -> None:
    values = table_values()
    assert len(values) > 80
    for where, key in values.items():
        if key is not None:
            assert key in english.keys, where


@pytest.mark.parametrize(
    ("table", "enum"),
    [
        (tables.REPORT_TYPE_KEYS, ReportType),
        (tables.MODIFIER_KEYS, Modifier),
        (tables.INTENSITY_KEYS, Intensity),
        (tables.DESCRIPTOR_ALONE_KEYS, Descriptor),
        (tables.DESCRIPTOR_WITH_KEYS, Descriptor),
        (tables.PHENOMENON_KEYS, Phenomenon),
        (tables.SKY_COVER_KEYS, SkyCondition),
        (tables.CLOUD_TYPE_KEYS, CloudType),
        (tables.RVR_TREND_KEYS, RvrTrend),
        (tables.FLIGHT_CATEGORY_KEYS, FlightCategory),
        (tables.FLAG_KEYS, Flag),
    ],
)
def test_tables_cover_every_enum_member(table: dict[object, object], enum: type) -> None:
    expected = set(enum)
    if enum is SkyCondition:
        expected -= {SkyCondition.VV}  # vertical visibility has its own sentence
    assert set(table) == expected


def test_compass_points() -> None:
    assert len(tables.COMPASS_KEYS) == 16
    assert tables.compass_point(0) == "N"
    assert tables.compass_point(60) == "ENE"
    assert tables.compass_point(90) == "E"
    assert tables.compass_point(180) == "S"
    assert tables.compass_point(270) == "W"
    assert tables.compass_point(360) == "N"
    assert tables.compass_point(350) == "N"
    assert tables.compass_point(-10) == "N"


def test_code_tables_round_trip() -> None:
    assert tables.PHENOMENON_CODES["RA"] is Phenomenon.RA
    assert tables.DESCRIPTOR_CODES["TS"] is Descriptor.TS
    assert tables.MODIFIER_CODES["COR"] is Modifier.COR
    assert tables.SKY_COVER_CODES["OVC"] is SkyCondition.OVC
    assert tables.CLOUD_TYPE_CODES["CB"] is CloudType.CB
    assert tables.RVR_TREND_CODES["U"] is RvrTrend.UP
