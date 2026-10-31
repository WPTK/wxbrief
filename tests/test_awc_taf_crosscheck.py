"""Cross-check of the decoded TAFs against AWC's structured JSON for every saved forecast.

AWC parses the same ``rawTAF`` text into ``fcsts`` (one entry per group). Our hand-written parser must agree with it
wherever the field exists: the valid period, each group's change type, probability and times (``timeFrom``,
``timeTo``, ``timeBec``), wind, wind shear, visibility, weather, clouds, vertical visibility, pressure, icing and
turbulence, and the temperature extremes.

How AWC models a TAF, learned by comparing (and encoded below, not guessed):

* A ``BECMG`` entry carries on whatever the group does not list, so it shows the forecast as it stands once the change
  has taken effect; ``FM``, the base and ``TEMPO``/``PROB`` entries show only what they state (``awc_views``).
* ``timeTo`` of the base, an ``FM`` or a ``BECMG`` is where the next ``FM``/``BECMG`` starts (``taf.py:_close``).
* ``INTER`` and ``PROB30 TEMPO`` are ``TEMPO`` (the latter with a probability); a bare ``PROB30`` is ``PROB``.
* ``VV001`` is cover ``OVX`` plus ``vertVis`` in feet; ``CAVOK`` is ``6+``, cover ``NSC`` and sometimes ``NSW``.

A disagreement is a decoder bug or an AWC quirk. The quirks that were investigated are named rules in ``RULES``, each
with its reason, in the manner of ``test_flightcat.PARITY_RULES``: a rule must still cover a real disagreement and must
not hide an agreement. A new disagreement fails the test: fix the decoder, or investigate it and add a rule.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pytest
from corpus import awc_taf_rows, issue_time

from wxbrief.decode.model import ChangeType, ForecastElements, Intensity, SemanticKind, SkyCondition, Taf, TafPeriod
from wxbrief.decode.taf import parse_taf
from wxbrief.decode.timeline import merge
from wxbrief.decode.times import next_clock_time

HPA_TOLERANCE = 1  # AWC converts inches of mercury to hectopascals with its own rounding


def decode(row: dict[str, Any]) -> Taf:
    return parse_taf(row["rawTAF"], issue_time(row))


def epoch(moment: datetime | None) -> int | None:
    return int(moment.timestamp()) if moment is not None else None


def awc_views(taf: Taf) -> list[ForecastElements]:
    """What AWC shows for each group (a ``BECMG`` is merged into the running forecast in report order)."""
    running = ForecastElements()
    views: list[ForecastElements] = []
    for period in taf.periods:
        if period.change in (ChangeType.BASE, ChangeType.FM):
            running = period.elements
            views.append(period.elements)
        elif period.change is ChangeType.BECMG:
            running = merge(running, period.elements)
            views.append(running)
        else:
            views.append(period.elements)
    return views


# --- field extractors: each returns (ours, theirs) for one forecast group ---------------------------------------

Pair = tuple[Any, Any]
Extractor = Callable[[TafPeriod, ForecastElements, dict[str, Any]], Pair]

AWC_CHANGE = {
    ChangeType.BASE: None,
    ChangeType.FM: "FM",
    ChangeType.BECMG: "BECMG",
    ChangeType.TEMPO: "TEMPO",
    ChangeType.PROB: "PROB",
    ChangeType.PROB_TEMPO: "TEMPO",
    ChangeType.INTER: "TEMPO",
    ChangeType.PROB_INTER: "TEMPO",
}


def change(period: TafPeriod, view: ForecastElements, group: dict[str, Any]) -> Pair:
    return AWC_CHANGE[period.change], group["fcstChange"]


def probability(period: TafPeriod, view: ForecastElements, group: dict[str, Any]) -> Pair:
    return period.probability, group["probability"]


def time_from(period: TafPeriod, view: ForecastElements, group: dict[str, Any]) -> Pair:
    return epoch(period.start), group["timeFrom"]


def time_to(period: TafPeriod, view: ForecastElements, group: dict[str, Any]) -> Pair:
    return epoch(period.end), group["timeTo"]


def time_becoming(period: TafPeriod, view: ForecastElements, group: dict[str, Any]) -> Pair:
    return epoch(period.becoming_end), group["timeBec"]


def wind_direction(period: TafPeriod, view: ForecastElements, group: dict[str, Any]) -> Pair:
    if view.wind is None:
        return None, group["wdir"]
    return ("VRB" if view.wind.variable else view.wind.direction), group["wdir"]


def wind_speed(period: TafPeriod, view: ForecastElements, group: dict[str, Any]) -> Pair:
    wind = view.wind
    return (round(wind.speed.knots) if wind is not None and wind.speed is not None else None), group["wspd"]


def wind_gust(period: TafPeriod, view: ForecastElements, group: dict[str, Any]) -> Pair:
    wind = view.wind
    return (round(wind.gust.knots) if wind is not None and wind.gust is not None else None), group["wgst"]


def shear_height(period: TafPeriod, view: ForecastElements, group: dict[str, Any]) -> Pair:
    shear = period.elements.wind_shear
    return (round(shear.height.feet / 100) if shear is not None else None), group["wshearHgt"]


def shear_direction(period: TafPeriod, view: ForecastElements, group: dict[str, Any]) -> Pair:
    shear = period.elements.wind_shear
    return (shear.direction if shear is not None else None), group["wshearDir"]


def shear_speed(period: TafPeriod, view: ForecastElements, group: dict[str, Any]) -> Pair:
    shear = period.elements.wind_shear
    return (round(shear.speed.knots) if shear is not None else None), group["wshearSpd"]


def visibility(period: TafPeriod, view: ForecastElements, group: dict[str, Any]) -> Pair:
    """AWC: ``6+`` for 9999, CAVOK and P6SM; otherwise statute miles to two decimals; ``""`` when not stated."""
    vis = view.visibility
    theirs = group["visib"]
    if vis is None or vis.not_reported:
        return "", theirs
    if vis.cavok or vis.unlimited:
        return "6+", theirs
    assert vis.distance is not None
    miles = vis.distance.statute_miles
    if vis.prefix is not None and vis.prefix.value == "P" and miles >= 6:
        return "6+", theirs
    return round(miles, 2), theirs


def split_weather(view: ForecastElements) -> list[str]:
    """Our weather groups the way AWC prints them: one entry per phenomenon with intensity and descriptor."""
    found: list[str] = []
    for group in view.weather:
        if group.nsw:
            found.append("NSW")
            continue
        prefix = {Intensity.LIGHT: "-", Intensity.HEAVY: "+", Intensity.MODERATE: ""}[group.intensity]
        if group.vicinity:
            prefix = "VC"
        descriptor = group.descriptor.value if group.descriptor is not None else ""
        if not group.phenomena:
            found.append(prefix + descriptor)
        else:
            found.extend(prefix + descriptor + phenomenon.value for phenomenon in group.phenomena)
    return found


def weather(period: TafPeriod, view: ForecastElements, group: dict[str, Any]) -> Pair:
    """Weather strings, without ``NSW`` unless the group says it.

    ``CAVOK`` implies no significant weather, and AWC spells that out as ``NSW`` for some CAVOK forecasts and not for
    others (never when a ``TX``/``TN`` group follows it), so a ``NSW`` that comes only from ``CAVOK`` is not compared.
    """
    ours = [item for item in split_weather(view) if item != "NSW"]
    theirs = [item for item in (group["wxString"] or "").split() if item != "NSW"]
    if any(item.nsw for item in period.elements.weather):
        ours.append("NSW")
        if "NSW" in (group["wxString"] or "").split():
            theirs.append("NSW")
    return sorted(ours), sorted(theirs)


def clouds(period: TafPeriod, view: ForecastElements, group: dict[str, Any]) -> Pair:
    ours: list[tuple[str, int | None, str | None]] = []
    if view.visibility is not None and view.visibility.cavok:
        ours.append(("NSC", None, None))
    for layer in view.sky:
        if layer.cover is SkyCondition.VV:
            if layer.base is not None:
                ours.append(("OVX", None, None))
            continue
        base = round(layer.base.feet) if layer.base is not None else None
        ours.append((layer.cover.value, base, layer.cloud_type.value if layer.cloud_type is not None else None))
    theirs = [(item["cover"], item["base"], item["type"]) for item in group["clouds"]]
    return ours, theirs


def vertical_visibility(period: TafPeriod, view: ForecastElements, group: dict[str, Any]) -> Pair:
    found = [layer.base for layer in view.sky if layer.cover is SkyCondition.VV and layer.base is not None]
    feet = round(found[0].feet) if found else 0
    return (feet or None), group["vertVis"]


def pressure(period: TafPeriod, view: ForecastElements, group: dict[str, Any]) -> Pair:
    theirs = group["altim"]
    if view.altimeter is None:
        return None, theirs
    ours = round(view.altimeter.hpa)
    if theirs is not None and abs(ours - theirs) <= HPA_TOLERANCE:
        return theirs, theirs
    return ours, theirs


def hazards(period: TafPeriod, view: ForecastElements, group: dict[str, Any]) -> Pair:
    """Icing and turbulence as AWC prints them: ``intensity`` digit, base ``minAlt``, top ``maxAlt``.

    AWC lists only the groups a forecast states itself (a ``BECMG`` does not carry hazards over), so this uses the
    group's own elements.
    """
    ours: list[tuple[str, int | None, int | None, int | None]] = []
    for kind, items in (("ICE", period.elements.icing), ("TURB", period.elements.turbulence)):
        for item in items:
            number = int(item.intensity.value) if item.intensity.value.isdigit() else None
            if number == 0:
                ours.append((kind, None, None, None))
                continue
            base = round(item.base.feet)
            top = base + round(item.thickness.feet) if item.thickness is not None else None
            ours.append((kind, number, base or None, top))
    theirs = [(item["impactVar"], item["intensity"], item["minAlt"], item["maxAlt"]) for item in group["icgTurb"]]
    return sorted(ours, key=str), sorted(theirs, key=str)


GROUP_FIELDS: dict[str, Extractor] = {
    "fcstChange": change,
    "probability": probability,
    "timeFrom": time_from,
    "timeTo": time_to,
    "timeBec": time_becoming,
    "wdir": wind_direction,
    "wspd": wind_speed,
    "wgst": wind_gust,
    "wshearHgt": shear_height,
    "wshearDir": shear_direction,
    "wshearSpd": shear_speed,
    "visib": visibility,
    "wxString": weather,
    "clouds": clouds,
    "vertVis": vertical_visibility,
    "altim": pressure,
    "icgTurb": hazards,
}


# --- named rules for the disagreements that were investigated ---------------------------------------------------


@dataclass(frozen=True)
class Rule:
    """A known difference: ``applies`` picks the group (taf, position in the forecast, AWC's entry)."""

    name: str
    field: str
    reason: str
    applies: Callable[[Taf, int, dict[str, Any]], bool]


def has_unknown_height_vv(period: TafPeriod) -> bool:
    return any(layer.cover is SkyCondition.VV and layer.base is None for layer in period.elements.sky)


def becmg_with_new_cloud(taf: Taf, number: int, group: dict[str, Any]) -> bool:
    """A BECMG that lists cloud layers (none of them a vertical visibility) while AWC still shows a vertVis."""
    period = taf.periods[number]
    layers = period.elements.sky
    new_cloud = bool(layers) and all(layer.cover is not SkyCondition.VV for layer in layers)
    return period.change is ChangeType.BECMG and new_cloud and group["vertVis"] is not None


def becmg_with_unknown_vv(taf: Taf, number: int, group: dict[str, Any]) -> bool:
    return taf.periods[number].change is ChangeType.BECMG and has_unknown_height_vv(taf.periods[number])


def mentions_grid(taf: Taf, number: int, group: dict[str, Any]) -> bool:
    return any(token.text == "GRID" for token in taf.periods[number].tokens)


def typo_window(taf: Taf, number: int, group: dict[str, Any]) -> bool:
    period = taf.periods[number]
    return period.change is ChangeType.BECMG and period.start is not None and period.becoming_end is None


RULES: tuple[Rule, ...] = (
    Rule(
        "stale-vertical-visibility",
        "vertVis",
        "A BECMG that lists new cloud layers ends the vertical visibility of the forecast before it, but AWC carries "
        "the old vertVis over next to the new layers. We drop it.",
        becmg_with_new_cloud,
    ),
    Rule(
        "vv-unknown-height-inherits-cloud",
        "clouds",
        "AWC cannot decode VV/// (vertical visibility not available), so a BECMG with it keeps the cloud layers of "
        "the forecast before. We take VV/// as the sky and so replace them.",
        becmg_with_unknown_vv,
    ),
    Rule(
        "grid-winds-read-as-hail",
        "wxString",
        "The Antarctic note 'ALL WINDS GRID' ends in GR, which AWC reads as the hail code and adds to the weather. "
        "We leave the note undecoded.",
        mentions_grid,
    ),
    Rule(
        "typo-in-becmg-window",
        "timeBec",
        "A BECMG window '3120/3021' ends before it starts (a typo for 3121): we flag the end as invalid_time and leave "
        "it empty, AWC resolves it to a month later.",
        typo_window,
    ),
)


def rule_for(field: str, taf: Taf, number: int, group: dict[str, Any]) -> Rule | None:
    return next((rule for rule in RULES if rule.field == field and rule.applies(taf, number, group)), None)


def compared(field: str) -> list[tuple[Taf, int, dict[str, Any], Pair, str]]:
    """Every forecast group with its (ours, theirs) pair for ``field``, and the raw text."""
    compare = GROUP_FIELDS[field]
    found: list[tuple[Taf, int, dict[str, Any], Pair, str]] = []
    for row in awc_taf_rows():
        taf = decode(row)
        if len(taf.periods) != len(row["fcsts"]):
            continue  # reported by test_group_counts_match
        for number, (period, view, group) in enumerate(zip(taf.periods, awc_views(taf), row["fcsts"], strict=True)):
            found.append((taf, number, group, compare(period, view, group), row["rawTAF"]))
    return found


@pytest.mark.parametrize("field", sorted(GROUP_FIELDS))
def test_group_field_matches_awc(field: str) -> None:
    found = [
        f"{field}[{number}]: ours={ours!r} awc={theirs!r} :: {raw}"
        for taf, number, group, (ours, theirs), raw in compared(field)
        if ours != theirs and rule_for(field, taf, number, group) is None
    ]
    assert not found, "\n".join(found)


def awc_undecoded(row: dict[str, Any]) -> set[str]:
    return {word for group in row["fcsts"] for word in (group["notDecoded"] or "").split()}


def our_undecoded(taf: Taf) -> set[str]:
    return {token.text for token in taf.tokens if token.kind is SemanticKind.UNKNOWN}


UNDECODED_EXCEPTIONS: dict[str, str] = {
    "VV///": "AWC lists VV/// (vertical visibility not available) as not decoded; we decode it as vertical visibility "
    "with no height and flag the forecast as missing data.",
}
UNDECODED_NOTES: dict[str, str] = {
    "TAF KRIV": "'WND 230V330' (a wind-direction variation note): we leave both words undecoded, AWC ignores 'WND' and "
    "lists '230V330', on the next group.",
    "TAF NZSP": "'WND21008KT AFT 3122 ALL WINDS GRID' (Antarctic grid winds) is a note neither side decodes; AWC "
    "ignores it silently.",
}


def undecoded_difference(row: dict[str, Any]) -> tuple[set[str], set[str]]:
    """(words only we leave undecoded, words only AWC lists as not decoded) once the explained ones are removed."""
    taf = decode(row)
    ours, theirs = our_undecoded(taf), awc_undecoded(row)
    only_ours, only_theirs = ours - theirs, theirs - ours
    only_theirs -= {word for word in UNDECODED_EXCEPTIONS if any(has_unknown_height_vv(p) for p in taf.periods)}
    if any(row["rawTAF"].startswith(prefix) for prefix in UNDECODED_NOTES):
        only_ours, only_theirs = set(), set()
    return only_ours, only_theirs


def test_undecoded_words_match_awc() -> None:
    """The words we leave ``UNKNOWN`` are the words AWC lists as not decoded (AWC repeats them on later groups)."""
    found = [
        f"only ours={sorted(only_ours)} only awc={sorted(only_theirs)} :: {row['rawTAF']}"
        for row in awc_taf_rows()
        for only_ours, only_theirs in [undecoded_difference(row)]
        if only_ours or only_theirs
    ]
    assert not found, "\n".join(found)


def test_undecoded_exceptions_are_not_stale() -> None:
    rows = awc_taf_rows()
    assert any("VV///" in awc_undecoded(row) and "VV///" not in our_undecoded(decode(row)) for row in rows)
    for prefix in UNDECODED_NOTES:
        matching = [row for row in rows if row["rawTAF"].startswith(prefix)]
        assert matching, prefix
        assert any(our_undecoded(decode(row)) != awc_undecoded(row) for row in matching), prefix


@pytest.mark.parametrize("rule", RULES, ids=lambda rule: rule.name)
def test_rule_covers_a_real_disagreement_and_hides_no_agreement(rule: Rule) -> None:
    covered = [
        (ours == theirs, raw)
        for taf, number, group, (ours, theirs), raw in compared(rule.field)
        if rule.applies(taf, number, group)
    ]
    assert covered, f"{rule.name} no longer applies to any saved forecast; delete it"
    hidden = [raw for agrees, raw in covered if agrees]
    assert not hidden, f"{rule.name} covers groups where AWC agrees with us: {hidden[:2]}"


def test_valid_period_matches_awc() -> None:
    found: list[str] = []
    for row in awc_taf_rows():
        taf = decode(row)
        ours = (epoch(taf.valid_from), epoch(taf.valid_to))
        theirs = (row["validTimeFrom"], row["validTimeTo"])
        if ours != theirs:
            found.append(f"ours={ours} awc={theirs} :: {row['rawTAF']}")
    assert not found, "\n".join(found)


def test_group_counts_match() -> None:
    found = [
        f"ours={len(decode(row).periods)} awc={len(row['fcsts'])} :: {row['rawTAF']}"
        for row in awc_taf_rows()
        if len(decode(row).periods) != len(row["fcsts"])
    ]
    assert not found, "\n".join(found)


def test_issue_time_matches_awc() -> None:
    """The issue time is AWC's ``issueTime`` whenever the forecast carries a ``DDHHMMZ`` group (some do not)."""
    checked = 0
    for row in awc_taf_rows():
        taf = decode(row)
        if any(token.kind is SemanticKind.TIME and token.text.endswith("Z") for token in taf.tokens):
            assert taf.issue_time == issue_time(row), row["rawTAF"]
            checked += 1
        else:
            assert taf.issue_time is None, row["rawTAF"]
    assert checked > 150


def test_temperature_extremes_match_awc() -> None:
    """AWC hangs ``TX``/``TN`` on one of the groups; compared over the whole forecast, they are the same set.

    AWC ignores the day in ``TX19/3114Z`` and puts the extreme at the first such hour from the start of the valid
    period (``TN05/0106Z`` on a forecast valid from 31/06 becomes 31/06, a day early; ``TX15/3014Z`` before the valid
    period becomes the 31st). We keep the day the report states (``test_temperature_times_follow_the_stated_day``), so
    the times are compared the way AWC derives them.
    """
    found: list[str] = []
    for row in awc_taf_rows():
        taf = decode(row)
        assert taf.valid_from is not None
        ours = sorted(
            (item.kind.value, int(item.temperature.value), epoch(next_clock_time(item.hour, 0, taf.valid_from)))
            for item in taf.temperatures
        )
        theirs = sorted(
            (entry["maxOrMin"], entry["surfaceTemp"], entry["validTime"])
            for group in row["fcsts"]
            for entry in group.get("temp") or []
        )
        if ours != theirs:
            found.append(f"ours={ours} awc={theirs} :: {row['rawTAF']}")
    assert not found, "\n".join(found)


def test_temperature_times_follow_the_stated_day() -> None:
    """Our ``TX``/``TN`` times use the day in the group: the report's own ``DDHHZ``, resolved next to the forecast."""
    for row in awc_taf_rows():
        for item in decode(row).temperatures:
            assert item.time is not None
            assert (item.time.day, item.time.hour) == (item.day, item.hour % 24), row["rawTAF"]
            assert abs(item.time - issue_time(row)).days <= 2, row["rawTAF"]


def test_modifiers_match_the_header_text() -> None:
    """``AMD`` and ``COR`` in the header are read as modifiers (AWC's ``remarks`` field repeats the ``AMD``)."""
    for row in awc_taf_rows():
        taf = decode(row)
        words = row["rawTAF"].split()[:3]
        assert ("AMD" in words) == taf.amended, row["rawTAF"]
        assert ("COR" in words) == any(item.value == "COR" for item in taf.modifiers), row["rawTAF"]


def test_the_batches_exercise_the_interesting_groups() -> None:
    """The check is only worth something if the saved forecasts contain the shapes it is meant to cover."""
    rows = awc_taf_rows()
    assert len(rows) >= 150
    groups = [group for row in rows for group in row["fcsts"]]
    assert {None, "FM", "BECMG", "TEMPO", "PROB"} <= {group["fcstChange"] for group in groups}
    assert any(group["probability"] for group in groups)
    assert any(group["icgTurb"] for group in groups)
    assert any(group["altim"] for group in groups)
    assert any(group["vertVis"] for group in groups)
    assert any(group["wgst"] for group in groups)
    assert any(entry for row in rows for group in row["fcsts"] for entry in group.get("temp") or [])
