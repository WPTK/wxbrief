"""The TAF timeline: slices, BECMG transitions, overlay inheritance and the hourly cells."""

from __future__ import annotations

from datetime import UTC, datetime

from wxbrief.decode.model import ChangeType, FlightCategory, ForecastElements, Taf
from wxbrief.decode.taf import parse_taf
from wxbrief.decode.timeline import (
    OVERLAY_TYPES,
    categorize_periods,
    category_of,
    expand_timeline,
    hourly_cells,
    merge,
    slice_at,
)

REF = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
VFR, MVFR, IFR, LIFR = FlightCategory.VFR, FlightCategory.MVFR, FlightCategory.IFR, FlightCategory.LIFR


def taf(body: str) -> Taf:
    return parse_taf(f"TAF KDEN 310500Z 3106/3118 {body}", REF)


def at(day: int, hour: int) -> datetime:
    return datetime(2026, 10, day, hour, tzinfo=UTC)


def elements(text: str) -> ForecastElements:
    """The elements of a one-group forecast."""
    base = parse_taf(f"TAF KDEN 310500Z 3106/3118 {text}", REF).base
    assert base is not None
    return base.elements


def spans(taf_: Taf) -> list[tuple[str, str]]:
    return [(s.start.strftime("%d%H"), s.end.strftime("%d%H")) for s in expand_timeline(taf_).slices]


# --- merge: what an overlay inherits ---------------------------------------------------------------------------------


def test_an_overlay_keeps_what_it_does_not_state() -> None:
    merged = merge(elements("18010KT 9999 BKN004"), elements("4000 BR"))
    assert merged.wind is not None and merged.wind.direction == 180  # inherited
    assert merged.sky[0].base is not None and merged.sky[0].base.value == 400  # the ceiling carries over
    assert merged.visibility is not None and merged.visibility.distance is not None
    assert merged.visibility.distance.value == 4000  # stated
    assert merged.weather  # stated


def test_a_stated_list_replaces_the_whole_list() -> None:
    merged = merge(elements("18010KT 9999 FEW010 BKN030"), elements("SCT020"))
    assert [(layer.cover.value, layer.base.value if layer.base else None) for layer in merged.sky] == [("SCT", 2000)]


def test_nsw_replaces_the_weather() -> None:
    merged = merge(elements("18010KT 9999 -RA BKN030"), elements("NSW"))
    assert len(merged.weather) == 1 and merged.weather[0].nsw


def test_nothing_stated_changes_nothing() -> None:
    prevailing = elements("18010KT 9999 -RA BKN030")
    assert merge(prevailing, ForecastElements()) == prevailing


def test_cavok_stated_replaces_visibility_weather_and_sky() -> None:
    merged = merge(elements("18010KT 3000 BR BKN004"), elements("CAVOK"))
    assert merged.visibility is not None and merged.visibility.cavok
    assert merged.weather == () and merged.sky == ()
    assert category_of(merged) is VFR


def test_a_prevailing_cavok_is_spelled_out_when_an_overlay_changes_part_of_it() -> None:
    merged = merge(elements("18010KT CAVOK"), elements("BKN004"))
    assert merged.visibility is not None and not merged.visibility.cavok
    assert merged.visibility.distance is not None and merged.visibility.distance.value == 10000
    assert category_of(merged) is LIFR  # 10 km, a 400 ft ceiling
    visibility_only = merge(elements("18010KT CAVOK"), elements("4000 BR"))
    assert visibility_only.sky[0].cover.value == "NSC"  # no significant cloud, still
    assert visibility_only.weather[0].phenomena  # the stated weather, not the spelled-out NSW
    assert category_of(visibility_only) is IFR


def test_extra_groups_inherit_too() -> None:
    merged = merge(elements("18010KT 9999 SCT030 QNH2992INS WS020/30035KT"), elements("3000 BR"))
    assert merged.altimeter is not None and merged.wind_shear is not None


# --- slices ------------------------------------------------------------------------------------------------------


def test_a_plain_forecast_is_one_slice_over_the_valid_period() -> None:
    timeline = expand_timeline(taf("18010KT 9999 SKC"))
    (only,) = timeline.slices
    assert (only.start, only.end) == (at(31, 6), at(31, 18))
    assert (timeline.start, timeline.end) == (at(31, 6), at(31, 18))
    assert only.category is VFR and only.worst_category is VFR
    assert not only.becoming and only.overlays == ()


def test_fm_replaces_everything_from_its_time() -> None:
    timeline = expand_timeline(taf("18010KT 3000 BR OVC004 FM311200 20010KT 9999 SKC"))
    before, after = timeline.slices
    assert before.category is LIFR
    assert after.category is VFR
    assert after.prevailing.visibility is not None and after.prevailing.visibility.distance is not None
    assert after.prevailing.visibility.distance.value == 10000
    assert after.period == 1


def test_becmg_takes_effect_at_the_end_of_its_window() -> None:
    timeline = expand_timeline(taf("18010KT P6SM SKC BECMG 3108/3110 4SM BR OVC008"))
    first, during, after = timeline.slices
    assert (first.category, first.becoming) == (VFR, False)
    assert (during.start, during.end) == (at(31, 8), at(31, 10))
    assert during.becoming and during.becoming_index == 1
    assert during.category is VFR  # the old forecast still prevails inside the window
    assert (after.start, after.end, after.category, after.becoming) == (at(31, 10), at(31, 18), IFR, False)
    assert after.period == 1


def test_the_worst_case_counts_a_becmg_from_the_start_of_its_window() -> None:
    raw = "TAF KXXX 311130Z 3112/0112 18010KT P6SM SKC BECMG 0110/0112 1/4SM FG VV001"
    parsed = parse_taf(raw, REF)
    timeline = expand_timeline(parsed)
    during = timeline.slices[-1]
    assert during.becoming and during.category is VFR  # the category is still the prevailing one
    assert during.worst_category is LIFR
    assert timeline.worst_category is LIFR
    assert parsed.worst_category is LIFR
    assert hourly_cells(timeline)[-1].worst_category is LIFR


def test_becmg_merges_over_the_old_forecast() -> None:
    timeline = expand_timeline(taf("18010KT 4SM BR OVC008 BECMG 3108/3110 27015KT"))
    after = timeline.slices[-1]
    assert after.prevailing.wind is not None and after.prevailing.wind.direction == 270  # changed
    assert after.prevailing.visibility is not None  # kept
    assert after.category is IFR


def test_a_later_fm_supersedes_a_becmg_still_in_progress() -> None:
    timeline = expand_timeline(taf("18010KT 9999 SCT050 BECMG 3110/3116 BKN004 FM311300 20010KT 9999 SKC"))
    assert [(s.start.hour, s.end.hour, s.becoming, s.category) for s in timeline.slices] == [
        (6, 10, False, VFR),
        (10, 13, True, VFR),  # flagged, but the change never lands
        (13, 18, False, VFR),
    ]
    # it may have taken effect at any moment before the FM, so the worst case still counts it
    assert [s.worst_category for s in timeline.slices] == [VFR, LIFR, VFR]
    assert timeline.worst_category is LIFR


def test_a_becmg_that_ends_before_the_next_fm_does_land() -> None:
    timeline = expand_timeline(taf("18010KT 9999 SCT050 BECMG 3108/3110 BKN004 FM311300 20010KT 9999 SKC"))
    assert [(s.start.hour, s.category) for s in timeline.slices] == [(6, VFR), (8, VFR), (10, LIFR), (13, VFR)]


# --- overlays --------------------------------------------------------------------------------------------------------


def test_tempo_is_laid_over_the_prevailing_forecast_without_changing_it() -> None:
    timeline = expand_timeline(taf("18010KT 9999 SCT050 TEMPO 3108/3112 BKN004"))
    assert spans(taf("18010KT 9999 SCT050 TEMPO 3108/3112 BKN004")) == [("3106", "3108"), ("3108", "3112"), ("3112", "3118")]
    quiet, tempo, after = timeline.slices
    assert quiet.overlays == () and after.overlays == ()
    assert tempo.category is VFR  # prevailing is untouched
    assert tempo.worst_category is LIFR
    (overlay,) = tempo.overlays
    assert (overlay.change, overlay.probability, overlay.category) == (ChangeType.TEMPO, None, LIFR)
    assert overlay.index == 1
    assert timeline.worst_category is LIFR


def test_an_overlay_inherits_the_prevailing_elements_for_its_category() -> None:
    """``TEMPO 4000 BR`` says nothing about cloud: the ceiling that prevails decides with the new visibility."""
    ifr = expand_timeline(taf("18010KT 9999 SCT050 TEMPO 3108/3112 4000 BR")).slices[1].overlays[0].category
    lifr = expand_timeline(taf("18010KT 9999 OVC004 TEMPO 3108/3112 4000 BR")).slices[1].overlays[0].category
    assert (ifr, lifr) == (IFR, LIFR)


def test_overlays_inherit_from_a_becmg_that_has_taken_effect() -> None:
    timeline = expand_timeline(taf("18010KT 9999 SKC BECMG 3106/3108 OVC004 TEMPO 3110/3112 4000 BR"))
    tempo = next(s for s in timeline.slices if s.overlays)
    assert tempo.category is LIFR  # BECMG done
    assert tempo.overlays[0].category is LIFR  # the TEMPO sits on the changed ceiling


def test_overlapping_overlays_are_listed_in_report_order_and_the_worst_wins() -> None:
    timeline = expand_timeline(taf("18010KT 9999 SCT050 TEMPO 3108/3112 BKN004 PROB30 3110/3116 2000 BR"))
    assert [(s.start.hour, s.end.hour) for s in timeline.slices] == [(6, 8), (8, 10), (10, 12), (12, 16), (16, 18)]
    both = timeline.slices[2]
    assert [o.change for o in both.overlays] == [ChangeType.TEMPO, ChangeType.PROB]
    assert [o.probability for o in both.overlays] == [None, 30]
    assert both.worst_category is LIFR
    assert timeline.slices[3].worst_category is IFR  # only the PROB30 is left


def test_prob_tempo_and_inter_are_overlays_too() -> None:
    for keyword, change in (("PROB30 TEMPO", ChangeType.PROB_TEMPO), ("INTER", ChangeType.INTER), ("PROB30 INTER", ChangeType.PROB_INTER)):
        timeline = expand_timeline(taf(f"18010KT 9999 SKC {keyword} 3108/3110 BKN004"))
        assert timeline.slices[1].overlays[0].change is change
        assert change in OVERLAY_TYPES


def test_a_later_fm_cuts_an_overlay_short() -> None:
    timeline = expand_timeline(taf("18010KT 9999 SKC TEMPO 3108/3116 BKN004 FM311100 20010KT 9999 SKC"))
    assert [(s.start.hour, s.end.hour, bool(s.overlays)) for s in timeline.slices] == [
        (6, 8, False),
        (8, 11, True),
        (11, 18, False),
    ]


def test_cavok_with_a_tempo() -> None:
    timeline = expand_timeline(taf("CAVOK TEMPO 3108/3110 4000 BR"))
    assert timeline.slices[1].overlays[0].category is IFR
    assert timeline.slices[1].category is VFR


# --- categories per group ---------------------------------------------------------------------------------------------


def test_period_categories_use_the_same_rules() -> None:
    forecast = taf("18010KT 9999 OVC004 BECMG 3108/3110 BKN030 TEMPO 3112/3114 2SM FM311600 20010KT 9999 SKC")
    assert [p.flight_category for p in forecast.periods] == [LIFR, MVFR, IFR, VFR]  # the TEMPO's 2 SM beats the 3000 ft ceiling
    assert categorize_periods(forecast.periods, forecast.valid_from) == [p.flight_category for p in forecast.periods]


def test_a_group_without_a_start_inherits_the_running_forecast() -> None:
    forecast = parse_taf("TAF KDEN 310500Z 3106/3118 18010KT 9999 OVC004 TEMPO 4000 BR", REF)
    assert forecast.changes[0].start is None
    assert forecast.changes[0].flight_category is LIFR


def test_category_of_needs_visibility_or_sky() -> None:
    assert category_of(ForecastElements()) is None


# --- navigating the timeline -------------------------------------------------------------------------------------------


def test_slice_at_includes_the_start_and_excludes_the_end() -> None:
    timeline = expand_timeline(taf("18010KT 9999 SCT050 TEMPO 3108/3112 BKN004"))
    inside = slice_at(timeline, at(31, 8))
    assert inside is not None and inside.overlays
    assert slice_at(timeline, datetime(2026, 10, 31, 7, 59, tzinfo=UTC)) is timeline.slices[0]
    assert slice_at(timeline, at(31, 12)) is timeline.slices[2]
    assert slice_at(timeline, at(31, 18)) is None
    assert slice_at(timeline, at(31, 5)) is None
    assert timeline.at(at(31, 9)) is timeline.slices[1]


def test_hourly_cells_cover_every_hour_of_the_valid_period() -> None:
    timeline = expand_timeline(taf("18010KT 9999 SCT050 TEMPO 3108/3112 BKN004"))
    cells = hourly_cells(timeline)
    assert [cell.start.hour for cell in cells] == list(range(6, 18))
    assert all(cell.end - cell.start == (cells[0].end - cells[0].start) for cell in cells)
    assert [cell.category for cell in cells] == [VFR] * 12
    assert [cell.worst_category for cell in cells] == [VFR] * 2 + [LIFR] * 4 + [VFR] * 6
    assert [cell.overlay for cell in cells] == [False] * 2 + [True] * 4 + [False] * 6
    assert cells[2].overlay_category is LIFR and cells[0].overlay_category is None
    assert timeline.hourly() == cells


def test_hourly_cells_mark_the_becmg_window() -> None:
    cells = hourly_cells(expand_timeline(taf("18010KT P6SM SKC BECMG 3108/3110 4SM BR OVC008")))
    assert [cell.becoming for cell in cells] == [False] * 2 + [True] * 2 + [False] * 8
    assert [cell.category for cell in cells] == [VFR] * 4 + [IFR] * 8


def test_an_hour_takes_the_worst_slice_that_touches_it() -> None:
    forecast = parse_taf("TAF KDEN 310500Z 3106/3118 18010KT 9999 SKC FM310830 20010KT 3000 BR OVC004", REF)
    cells = hourly_cells(expand_timeline(forecast))
    assert cells[2].start.hour == 8 and cells[2].category is LIFR  # half VFR, half LIFR
    assert len(cells[2].slices) == 2


# --- degenerate forecasts ------------------------------------------------------------------------------------------------


def test_a_forecast_with_no_valid_period_has_an_empty_timeline() -> None:
    timeline = expand_timeline(parse_taf("TAF LFPB 311000Z NIL", REF))
    assert timeline.slices == () and timeline.hourly() == () and timeline.worst_category is None
    assert timeline.at(at(31, 10)) is None


def test_the_span_falls_back_to_the_groups_when_the_header_has_no_period() -> None:
    forecast = parse_taf("TAF KDEN 310500Z 18010KT 9999 SKC TEMPO 3108/3110 BKN004", REF)
    timeline = expand_timeline(forecast)
    assert forecast.valid_from is None
    assert timeline.start == at(31, 8) and timeline.end == at(31, 10)
