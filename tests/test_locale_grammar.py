"""Locale wording that needs no gender agreement, and the footer's palette label in each language.

The wording was written without a native speaker of es, fr, de or pt reviewing it; these tests pin what was changed,
they do not certify the language.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from wxbrief.decode.model import Metar
from wxbrief.decode.split import parse_any
from wxbrief.decode.units import UnitsMode
from wxbrief.i18n import Translator
from wxbrief.i18n.keys import K
from wxbrief.render.phrases import describe_weather_group, summary_line
from wxbrief.ui.bindings import relabel

REF = datetime(2026, 10, 13, tzinfo=UTC)


def metar(text: str) -> Metar:
    (report,) = parse_any(text, REF)
    assert isinstance(report, Metar)
    return report


def weather(lang: str, code: str) -> str:
    return describe_weather_group(Translator.load(lang), metar(f"METAR KDEN 131453Z 06007KT 1/2SM {code} OVC003 09/08 A3001").weather[0])


# A past participle after a feminine noun (nieve levantado, arena arrastrado, neige soulevé, neve levantado) was
# wrong; the phrases below do not inflect, so they agree with any noun.
@pytest.mark.parametrize(
    ("lang", "code", "expected"),
    [
        ("es", "BLSN", "nieve en suspensión por el viento"),
        ("es", "DRSA", "arena a ras de suelo"),
        ("es", "MIFG", "niebla superficial"),
        ("fr", "BLSN", "neige en suspension dans le vent"),
        ("fr", "DRSA", "sable au ras du sol"),
        ("fr", "FZRA", "pluie en surfusion"),
        ("pt", "BLSN", "neve em suspensão pelo vento"),
        ("pt", "DRSA", "areia rente ao solo"),
        ("de", "SHRA", "Schauer mit Regen"),
    ],
)
def test_descriptor_phrases_do_not_inflect(lang: str, code: str, expected: str) -> None:
    assert weather(lang, code) == expected


def test_french_timing_remark_reads_as_a_noun_phrase() -> None:
    t = Translator.load("fr")
    assert t.t(K.REMARK_TIMING, weather="Pluie", events="début à la minute 5") == "Pluie : début à la minute 5"
    assert t.t(K.REMARK_WORD_DSNT) == "distants"


def test_german_flat_fog_is_lowercase_after_the_colon() -> None:
    line = summary_line(Translator.load("de"), metar("METAR KDEN 131453Z 06007KT 1/2SM MIFG OVC003 09/08 A3001"), UnitsMode.US)
    assert "): flacher Nebel" in line


@pytest.mark.parametrize("lang", ["es", "fr", "de", "pt"])
def test_the_palette_binding_has_its_own_label(lang: str) -> None:
    t = Translator.load(lang)
    assert t.t(K.UI_BINDING_PALETTE) != ""
    app = make_app_for_labels()
    relabel(app, t)
    bindings = [b for bs in app._bindings.key_to_bindings.values() for b in bs if b.action == "command_palette"]
    assert [b.description for b in bindings] == [t.t(K.UI_BINDING_PALETTE)]


def make_app_for_labels() -> object:
    from wxbrief.app import WxBriefApp

    return WxBriefApp()
