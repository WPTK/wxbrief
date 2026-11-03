"""Red-team property tests: grammar-built METAR/TAF text decodes to the facts it was built from.

Unlike tests/test_fuzz.py (which only asks that the decoder never raises), the oracle here is the grammar in
``grammar.py``. Runs are deterministic: ``derandomize=True`` and no example database.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from grammar import Draw, metar, taf
from hypothesis import HealthCheck, given, settings

from wxbrief.decode.flightcat import visibility_sm
from wxbrief.decode.metar import parse_metar
from wxbrief.decode.taf import parse_taf

EXAMPLES = int(os.environ.get("WXBRIEF_RT_EXAMPLES", "400"))
RT = settings(
    max_examples=EXAMPLES,
    deadline=None,
    derandomize=True,
    database=None,
    suppress_health_check=list(HealthCheck),
)
REF = datetime(2026, 10, 29, 23, 59, tzinfo=UTC)
M_PER_SM = 1609.34


def expected_category(facts: dict) -> str:
    ceiling = min((h * 100 for c, h in facts.get("layers", []) if c in ("BKN", "OVC", "VV")), default=float("inf"))
    vis = facts.get("vis_sm")
    if vis is None:
        vis = 10.0 if facts["vis_m"] == 9999 else facts["vis_m"] / M_PER_SM
    if ceiling < 500 or vis < 1:
        return "LIFR"
    if ceiling < 1000 or vis < 3:
        return "IFR"
    if ceiling <= 3000 or vis <= 5:
        return "MVFR"
    return "VFR"


@RT
@given(metar())
def test_grammar_metar_decodes_to_its_facts(draw: Draw) -> None:
    m, f = parse_metar(draw.text, REF), draw.facts
    assert m.warnings == (), draw.text
    assert (m.station, m.temperature.value, m.dewpoint.value) == (f["station"], f["temp"], f["dew"])
    assert m.observed is not None and (m.observed.day, m.observed.hour, m.observed.minute) == (
        f["day"],
        f["hour"],
        f["minute"],
    )
    assert m.wind is not None and m.wind.speed.value == f["wind_speed"]
    if f["wind_speed"]:
        assert m.wind.direction == f["wind_dir"]
    assert (m.wind.gust.value if m.wind.gust else None) == f["wind_gust"]
    pressure = m.altimeters[0]
    assert pressure.value == f.get("alt_inhg", f.get("qnh_hpa"))
    assert pressure.unit.name == ("INHG" if f["system"] == "us" else "HPA")
    if f.get("layers"):
        assert [(layer.cover.name, round(layer.base.feet / 100)) for layer in m.sky] == f["layers"]


@RT
@given(metar())
def test_grammar_metar_flight_category_follows_tokens(draw: Draw) -> None:
    """Category from the actual visibility and BKN/OVC/VV tokens only (FEW/SCT never make a ceiling)."""
    m = parse_metar(draw.text, REF)
    assert m.flight_category is not None and m.flight_category.name == expected_category(draw.facts), draw.text
    if draw.facts.get("vis_m", 1) != 0 and not draw.facts.get("cavok"):
        sm = visibility_sm(m.visibility)
        want = draw.facts.get("vis_sm", draw.facts.get("vis_m", 0) / M_PER_SM)
        if draw.facts.get("vis_m") == 9999:
            want = 10.0
        assert abs(sm - want) < 1e-6


@RT
@given(metar(units="us"))
def test_us_report_with_foreign_station_prefix_still_reads_statute_miles(draw: Draw) -> None:
    """Station prefix (E, L, R, V, C, K, P) never decides units: ``SM`` and ``A####`` do."""
    m = parse_metar(draw.text, REF)
    assert m.visibility.distance.unit.name == "SM"
    assert m.altimeters[0].unit.name == "INHG"


@RT
@given(metar(units="icao"))
def test_icao_report_with_us_station_prefix_still_reads_metres(draw: Draw) -> None:
    m = parse_metar(draw.text, REF)
    assert m.altimeters[0].unit.name == "HPA"
    if "vis_m" in draw.facts:
        assert m.visibility.distance.unit.name == "M"


KINDS = {
    "FM": "FM",
    "BECMG": "BECMG",
    "TEMPO": "TEMPO",
    "PROB30": "PROB",
    "PROB40": "PROB",
    "PROB30 TEMPO": "PROB_TEMPO",
    "PROB40 TEMPO": "PROB_TEMPO",
    "BASE": "BASE",
}


@RT
@given(taf())
def test_grammar_taf_groups_and_times(draw: Draw) -> None:
    f = draw.facts
    issued = datetime(2026, 10, f["day"], f["hour"], 50, tzinfo=UTC)
    t = parse_taf(draw.text, issued)
    assert t.warnings == (), draw.text
    assert [p.change.name for p in t.periods] == [KINDS[g["change"]] for g in f["groups"]]
    origin = datetime(2026, 10, 1, tzinfo=UTC) - timedelta(hours=24)
    assert t.valid_from == origin + timedelta(hours=f["start_total"])
    assert t.valid_to == t.valid_from + timedelta(hours=24)
    for period, group in zip(t.periods[1:], f["groups"][1:], strict=True):
        assert period.start == origin + timedelta(hours=group["start"]), draw.text
        if group["change"] not in ("FM", "BECMG"):
            assert period.end == origin + timedelta(hours=group["end"]), draw.text
    probs = [p.probability for p in t.periods if p.probability]
    assert probs == [int(g["change"][4:6]) for g in f["groups"] if g["change"].startswith("PROB")]
