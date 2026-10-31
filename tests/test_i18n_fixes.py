"""Regional meta fallback, German sentence case, intensity wording and the Discord block in other languages."""

from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest

from wxbrief.decode.model import Metar
from wxbrief.decode.split import parse_any
from wxbrief.decode.units import UnitsMode
from wxbrief.i18n import Catalog, Translator, _read_catalog
from wxbrief.i18n.keys import K
from wxbrief.render.discord import render_discord
from wxbrief.render.phrases import summary_line

REF = datetime(2026, 10, 13, tzinfo=UTC)
RAIN = "METAR KDEN 131453Z 24015G25KT 3/4SM -RA BR OVC003 09/08 A3001 RMK AO2 SLP132 52012 T00890078"
FUNCTION_WORDS = ("Aus", "Mit", "Und", "Bei", "In", "Nicht", "Kein", "Keine")


def metar(text: str = RAIN) -> Metar:
    (report,) = parse_any(text, REF)
    assert isinstance(report, Metar)
    return report


@pytest.mark.parametrize("lang", ["de", "fr"])
def test_discord_uses_the_language_decimal_separator(lang: str) -> None:
    out = render_discord(metar(), Translator.load(lang), UnitsMode.METRIC, outer_fence=False)
    assert "1013,2 mb" in out
    assert re.search(r"[+-]\d,\d mb/3h", out)
    assert not re.search(r"\d\.\d mb", out)


def test_discord_in_english_keeps_the_point() -> None:
    out = render_discord(metar(), Translator.load("en"), UnitsMode.METRIC, outer_fence=False)
    assert "1013.2 mb" in out


def test_german_has_no_capitalised_function_word_mid_sentence() -> None:
    text = summary_line(Translator.load("de"), metar(), UnitsMode.US)
    body = text.split(": ", 1)[1]
    for word in FUNCTION_WORDS:
        assert not re.search(rf"[\w°),] {word}\b", body), body
    assert "Wind aus 240°" in body
    assert "Regen" in body  # nouns keep their capital


def test_german_lower_first_only_touches_listed_words() -> None:
    t = Translator.load("de")
    assert t.lower_first("Aus 240° (WSW) mit 15 kt") == "aus 240° (WSW) mit 15 kt"
    assert t.lower_first("Regen von leichter Intensität") == "Regen von leichter Intensität"
    assert t.lower_first("Nicht gemeldet") == "nicht gemeldet"
    assert Translator.load("fr").lower_first("Brume") == "brume"


@pytest.mark.parametrize(
    ("lang", "phrase"),
    [
        ("de", "Regen von leichter Intensität"),
        ("fr", "pluie d'intensité faible"),
        ("pt", "chuva de intensidade fraca"),
        ("es", "lluvia débil"),
    ],
)
def test_intensity_wording_has_no_gender_clash(lang: str, phrase: str) -> None:
    t = Translator.load(lang)
    rain = t.t(K.WX_PHENOMENON_RA)
    body = t.t(K.WX_WITH_INTENSITY, intensity=t.t(K.WX_INTENSITY_LIGHT), body=rain)
    assert body.lower() == phrase.lower()


def test_a_regional_catalog_without_meta_uses_its_base_language() -> None:
    base = _read_catalog("pt")
    english = _read_catalog("en")
    assert base is not None and english is not None
    t = Translator([Catalog("pt-BR", {K.WIND_CALM: "Calmaria"}, {}), base, english])
    assert t.numbers.decimal == ","
    assert t.language_name == "Português"
    assert t.plural(K.WARN_HEADING, 0) == "0 aviso"  # pt counts 0 as singular
    assert t.t(K.WIND_CALM) == "Calmaria"
    assert t.lang == "pt-BR"


def test_french_groups_with_a_narrow_no_break_space() -> None:
    assert Translator.load("fr").numbers.integer(10000) == "10 000"  # noqa: RUF001
