"""The TAF parser: header, modifiers, the base forecast, every kind of change group, times and tolerance."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from wxbrief.decode.model import (
    ChangeType,
    Flag,
    Flavor,
    FlightCategory,
    Modifier,
    ReportType,
    SemanticKind,
    SkyCondition,
    Taf,
    TemperatureExtreme,
)
from wxbrief.decode.taf import parse_taf

REF = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)


def utc(day: int, hour: int, month: int = 10, minute: int = 0) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=UTC)


def decode(raw: str, reference: datetime = REF) -> Taf:
    return parse_taf(raw, reference)


def codes(taf: Taf) -> list[str]:
    return [w.code for w in taf.warnings]


# --- the header ------------------------------------------------------------------------------------------------------


def test_header_and_base_forecast() -> None:
    taf = decode("TAF KDEN 301130Z 3012/3112 06007KT P6SM SKC")
    assert taf.report_type is ReportType.TAF
    assert taf.station == "KDEN"
    assert taf.issue_time == utc(30, 11, minute=30)
    assert (taf.valid_from, taf.valid_to) == (utc(30, 12), utc(31, 12))
    assert taf.modifiers == ()
    assert taf.warnings == ()
    assert taf.base is not None
    assert taf.base.change is ChangeType.BASE
    assert (taf.base.start, taf.base.end) == (utc(30, 12), utc(31, 12))
    assert taf.base.elements.wind is not None and taf.base.elements.wind.direction == 60
    assert taf.base.flight_category is FlightCategory.VFR
    assert taf.changes == ()
    assert taf.periods == (taf.base,)


def test_the_keyword_is_optional_and_case_does_not_matter() -> None:
    plain = decode("KDEN 301130Z 3012/3112 06007KT P6SM SKC")
    lower = decode("taf kden 301130z 3012/3112 06007kt p6sm skc")
    assert plain.station == lower.station == "KDEN"
    assert plain.base is not None and lower.base is not None
    assert plain.base.elements == lower.base.elements


@pytest.mark.parametrize(
    ("raw", "modifier"),
    [("TAF AMD", Modifier.AMD), ("TAF COR", Modifier.COR)],
)
def test_amendments_and_corrections(raw: str, modifier: Modifier) -> None:
    taf = decode(f"{raw} KDEN 301130Z 3012/3112 06007KT P6SM SKC")
    assert taf.modifiers == (modifier,)
    assert taf.station == "KDEN"
    assert taf.base is not None
    assert (Flag.AMENDED if modifier is Modifier.AMD else Flag.CORRECTED) in taf.flags


def test_a_cancellation_has_no_forecast() -> None:
    taf = decode("TAF AMD LFPG 311000Z 3110/3118 CNL")
    assert taf.modifiers == (Modifier.AMD, Modifier.CNL)
    assert taf.cancelled and taf.amended
    assert taf.base is None and taf.changes == ()
    assert taf.periods == ()
    assert taf.warnings == ()
    assert taf.worst_category is None


def test_a_nil_forecast_has_no_times() -> None:
    taf = decode("TAF LFPB 311000Z NIL")
    assert taf.nil
    assert taf.station == "LFPB"
    assert taf.valid_from is None and taf.valid_to is None
    assert taf.periods == ()
    assert taf.warnings == ()


def test_terminator_is_kept_as_a_token_and_is_not_a_warning() -> None:
    taf = decode("TAF KBOS 310500Z 3106/0112 VRB03KT P6SM SKC=")
    assert taf.tokens[-1].kind is SemanticKind.TERMINATOR
    assert taf.warnings == ()


def test_a_forecast_with_no_issue_time() -> None:
    taf = decode("TAF KNID 3023/3123 19020G30KT 9999 FEW080")
    assert taf.station == "KNID"
    assert taf.issue_time is None
    assert (taf.valid_from, taf.valid_to) == (utc(30, 23), utc(31, 23))
    assert taf.warnings == ()


# --- times ---------------------------------------------------------------------------------------------------------


def test_the_valid_period_runs_into_the_next_month() -> None:
    taf = decode("TAF KJFK 312200Z 3122/0106 06007KT P6SM SKC", utc(31, 23))
    assert taf.issue_time == utc(31, 22)
    assert (taf.valid_from, taf.valid_to) == (utc(31, 22), utc(1, 6, month=11))


def test_the_issue_day_resolves_to_the_most_recent_such_day_before_the_reference() -> None:
    taf = decode("TAF KJFK 312200Z 3122/0106 06007KT P6SM SKC", datetime(2026, 11, 1, 3, tzinfo=UTC))
    assert taf.issue_time == utc(31, 22)


def test_group_windows_are_resolved_against_the_valid_period() -> None:
    taf = decode(
        "TAF KJFK 312200Z 3122/0106 06007KT P6SM SKC BECMG 0100/0102 VRB03KT TEMPO 0103/0105 3SM BR", utc(31, 23)
    )
    becmg, tempo = taf.changes
    assert (becmg.change, becmg.start) == (ChangeType.BECMG, utc(1, 0, month=11))
    assert becmg.becoming_end == utc(1, 2, month=11)
    assert (tempo.start, tempo.end) == (utc(1, 3, month=11), utc(1, 5, month=11))


def test_a_becmg_keeps_going_to_the_next_change_or_the_end_of_the_forecast() -> None:
    taf = decode("TAF KJFK 310500Z 3106/3118 06007KT P6SM SKC BECMG 3108/3110 VRB03KT FM311400 18010KT")
    becmg, fm = taf.changes
    assert (becmg.start, becmg.becoming_end, becmg.end) == (utc(31, 8), utc(31, 10), utc(31, 14))
    assert (fm.start, fm.end) == (utc(31, 14), utc(31, 18))
    assert taf.base is not None and taf.base.end == utc(31, 8)


def test_fm_groups_end_where_the_next_begins() -> None:
    taf = decode("TAF KLGA 310821Z 3108/0112 30013KT P6SM FEW250 FM010000 34006KT P6SM SKC")
    assert taf.base is not None
    assert (taf.base.start, taf.base.end) == (utc(31, 8), utc(1, 0, month=11))
    (fm,) = taf.changes
    assert (fm.change, fm.start, fm.end) == (ChangeType.FM, utc(1, 0, month=11), utc(1, 12, month=11))


# --- change groups ---------------------------------------------------------------------------------------------------


def test_every_change_keyword() -> None:
    taf = decode(
        "TAF EGGW 310900Z 3109/3124 09005KT 3000 BR BKN003 "
        "BECMG 3110/3112 9999 NSW "
        "TEMPO 3112/3114 4000 BR "
        "INTER 3114/3116 4000 SHRA "
        "PROB30 3116/3118 -DZ "
        "PROB40 TEMPO 3118/3120 0800 FG "
        "PROB30 INTER 3120/3122 4000 SHRA "
        "FM312200 27010KT 9999 SKC"
    )
    assert taf.warnings == ()
    assert [(p.change, p.probability) for p in taf.changes] == [
        (ChangeType.BECMG, None),
        (ChangeType.TEMPO, None),
        (ChangeType.INTER, None),
        (ChangeType.PROB, 30),
        (ChangeType.PROB_TEMPO, 40),
        (ChangeType.PROB_INTER, 30),
        (ChangeType.FM, None),
    ]


def test_a_prob_group_without_tempo_keeps_its_probability() -> None:
    taf = decode("TAF EGUW 301332Z 3015/3018 14008KT 9999 FEW025 PROB30 3016/3018 SCT010")
    (prob,) = taf.changes
    assert (prob.change, prob.probability) == (ChangeType.PROB, 30)
    assert (prob.start, prob.end) == (utc(30, 16), utc(30, 18))
    assert prob.elements.sky[0].cover is SkyCondition.SCT


def test_change_group_elements_carry_only_what_is_stated() -> None:
    taf = decode("TAF EDDF 310500Z 3106/0112 VRB03KT CAVOK BECMG 3106/3109 05007KT PROB30 TEMPO 3106/3108 2000 BR")
    becmg, prob = taf.changes
    assert becmg.elements.wind is not None and becmg.elements.wind.direction == 50
    assert becmg.elements.visibility is None and becmg.elements.sky == ()
    assert prob.elements.wind is None
    assert prob.elements.visibility is not None and prob.elements.visibility.distance is not None
    assert prob.elements.visibility.distance.value == 2000
    assert len(prob.elements.weather) == 1


def test_nsw_and_cavok_in_a_forecast() -> None:
    taf = decode("TAF EGLC 310907Z 3109/3113 09004KT 0300 FG BKN001 BECMG 3109/3112 9999 NSW FEW018")
    assert taf.changes[0].elements.weather[0].nsw
    taf = decode("TAF LFPO 310500Z 3106/0112 05006KT CAVOK")
    assert taf.base is not None and taf.base.elements.visibility is not None
    assert taf.base.elements.visibility.cavok


def test_groups_without_a_base_forecast() -> None:
    taf = decode("TAF KJFK 312200Z 3122/0106 BECMG 0100/0102 VRB03KT")
    assert taf.base is None
    assert [p.change for p in taf.periods] == [ChangeType.BECMG]


def test_change_groups_after_remarks_are_not_read() -> None:
    taf = decode("TAF CYXY 310540Z 3106/3118 14012G22KT P6SM BKN240 RMK NXT FCST BY 311200Z")
    assert taf.remarks == "NXT FCST BY 311200Z"
    assert taf.changes == ()
    assert taf.warnings == ()


# --- TAF-only groups ---------------------------------------------------------------------------------------------------


def test_temperature_extremes_are_collected_wherever_they_sit() -> None:
    taf = decode("TAF SBPA 310900Z 3112/0112 15008KT 9999 BKN030 TX23/3117Z TN15/0105Z BECMG 3117/3118 08007KT SCT030")
    high, low = taf.temperatures
    assert (high.kind, high.temperature.value, high.time) == (TemperatureExtreme.MAX, 23, utc(31, 17))
    assert (low.kind, low.temperature.value, low.time) == (TemperatureExtreme.MIN, 15, utc(1, 5, month=11))
    assert taf.base is not None and taf.base.elements.wind is not None  # the extremes did not end the base forecast


def test_negative_extremes() -> None:
    taf = decode("TAF CYYZ 310800Z 3108/0112 27012KT P6SM BKN040 TXM02/3118Z TNM08/0108Z")
    assert [t.temperature.value for t in taf.temperatures] == [-2, -8]


def test_wind_shear_belongs_to_its_period() -> None:
    taf = decode("TAF ENGM 310500Z 3106/3118 24015KT 9999 FEW030 WS020/30035KT TEMPO 3110/3114 VRB20G35KT 3000 TSRA")
    assert taf.base is not None and taf.base.elements.wind_shear is not None
    assert taf.base.elements.wind_shear.speed.value == 35
    assert taf.changes[0].elements.wind_shear is None
    assert Flag.WIND_SHEAR in taf.flags


def test_icing_turbulence_and_qnh_belong_to_their_period() -> None:
    taf = decode(
        "TAF AMD KHIF 310100Z 3101/0103 18006KT 9000 -SHRA OVC050 520009 QNH2992INS "
        "BECMG 3104/3105 15010KT 9999 VCSH BKN050 610505 QNH2995INS"
    )
    assert taf.base is not None
    assert len(taf.base.elements.turbulence) == 1 and taf.base.elements.icing == ()
    assert taf.base.elements.altimeter is not None and taf.base.elements.altimeter.value == 29.92
    becmg = taf.changes[0]
    assert len(becmg.elements.icing) == 1 and becmg.elements.turbulence == ()
    assert Flag.ICING in taf.flags and Flag.TURBULENCE in taf.flags


def test_military_closing_notes_become_the_remarks() -> None:
    taf = decode("TAF KNID 3023/3123 19020G30KT 9999 FEW080 LAST NO AMDS AFT 3023 NEXT 0207 TX21/3122Z FS30217")
    assert taf.remarks == "LAST NO AMDS AFT 3023 NEXT 0207 FS30217"
    assert taf.warnings == ()
    assert len(taf.temperatures) == 1


# --- old-style forms -----------------------------------------------------------------------------------------------


def test_legacy_forms_decode_with_one_warning_each() -> None:
    taf = decode(
        "TAF KDEN 301130Z 301212 18010KT P6SM SCT050 BECMG 1517 27015G25KT FM2000 25008KT P6SM BKN100 TEMPO 0204 3SM -SHRA"
    )
    assert taf.legacy
    assert codes(taf) == ["legacy_format"] * 4
    assert (taf.valid_from, taf.valid_to) == (utc(30, 12), utc(31, 12))
    becmg, fm, tempo = taf.changes
    assert (becmg.start, becmg.becoming_end) == (utc(30, 15), utc(30, 17))
    assert fm.start == utc(30, 20)
    assert (tempo.start, tempo.end) == (utc(31, 2), utc(31, 4))
    assert taf.flavor is Flavor.US  # the four-digit windows are not metre visibilities


def test_modern_forms_are_not_legacy() -> None:
    assert not decode("TAF KDEN 301130Z 3012/3112 06007KT P6SM SKC").legacy


# --- tolerance -------------------------------------------------------------------------------------------------------


def test_a_change_group_without_a_window_warns_and_keeps_its_elements() -> None:
    taf = decode("TAF KJFK 312200Z 3122/0106 06007KT TEMPO 06007KT")
    assert codes(taf) == ["missing_time"]
    (tempo,) = taf.changes
    assert tempo.start is None and tempo.end is None
    assert tempo.elements.wind is not None


def test_unreadable_words_stay_unknown_with_a_warning() -> None:
    taf = decode("TAF KJFK 312200Z 3122/0106 06007KT XXXX P6SM FOO")
    assert [(w.code, w.text) for w in taf.warnings] == [("unknown_token", "XXXX"), ("unknown_token", "FOO")]
    assert taf.base is not None and taf.base.elements.visibility is not None


def test_a_window_that_is_not_a_date_is_unknown() -> None:
    taf = decode("TAF KJFK 312200Z 3122/0106 06007KT P6SM SKC BECMG 0100/0102 VRB03KT 3122/3199")
    assert [w.text for w in taf.warnings] == ["3122/3199"]


@pytest.mark.parametrize("group", ["997788", "130025", "321212", "131225"])
def test_a_six_digit_group_that_is_not_a_valid_period_is_unknown_not_legacy(group: str) -> None:
    taf = decode(f"TAF KJFK 312200Z {group} 06007KT P6SM SKC")
    assert not taf.legacy
    assert [(w.code, w.text) for w in taf.warnings] == [("unknown_token", group)]


@pytest.mark.parametrize("raw", ["", "   ", "TAF", "hello", "TAF KJFK", "METAR KDEN 131453Z 06007KT 10SM CLR 09/08 A3001"])
def test_nothing_raises_and_every_character_is_kept(raw: str) -> None:
    taf = decode(raw)
    assert [raw[t.start : t.end] for t in taf.tokens] == raw.split()


def test_tokens_cover_every_character_and_are_tagged() -> None:
    raw = "TAF AMD EGGW 310900Z 3109/3118 09005KT 3000 BR BKN003 PROB30 TEMPO 3109/3112 0800 FG VV001 RMK TEST=\nNEXT"
    taf = decode(raw)
    covered = [i for t in taf.tokens for i in range(t.start, t.end)]
    assert covered == [i for i, ch in enumerate(raw) if not ch.isspace()]
    kinds = {t.text: t.kind for t in taf.tokens}
    assert kinds["TAF"] is SemanticKind.TYPE
    assert kinds["EGGW"] is SemanticKind.STATION
    assert kinds["310900Z"] is SemanticKind.TIME
    assert kinds["PROB30"] is SemanticKind.TREND
    assert kinds["TEST"] is SemanticKind.REMARK
    assert kinds["="] is SemanticKind.TERMINATOR


def test_period_tokens_are_the_slice_of_the_report_the_group_came_from() -> None:
    taf = decode("TAF KDEN 301130Z 3012/3112 06007KT P6SM SKC TEMPO 3014/3016 3SM BR")
    tempo = taf.changes[0]
    assert [t.text for t in tempo.tokens] == ["TEMPO", "3014/3016", "3SM", "BR"]


def test_the_parser_never_raises_on_a_reference_without_a_timezone() -> None:
    taf = parse_taf("TAF KDEN 301130Z 3012/3112 06007KT P6SM SKC", datetime(2026, 10, 31, 12))
    assert taf.issue_time == utc(30, 11, minute=30)


def test_the_failsafe_result_when_the_parser_breaks(monkeypatch: pytest.MonkeyPatch) -> None:
    import wxbrief.decode.taf as module

    def boom(raw: str, reference: datetime | None) -> Taf:
        raise RuntimeError("boom")

    monkeypatch.setattr(module, "_parse", boom)
    taf = module.parse_taf("TAF KDEN 301130Z 3012/3112 06007KT")
    assert codes(taf) == ["parser_error"]
    assert taf.base is None
    assert "".join(t.text for t in taf.tokens) == "TAFKDEN301130Z3012/311206007KT"


# --- flight categories ------------------------------------------------------------------------------------------------


def test_worst_category_includes_the_overlays() -> None:
    taf = decode("TAF KDEN 301130Z 3012/3112 06007KT P6SM SKC TEMPO 3014/3016 1SM BR")
    assert taf.base is not None and taf.base.flight_category is FlightCategory.VFR
    assert taf.changes[0].flight_category is FlightCategory.IFR
    assert taf.worst_category is FlightCategory.IFR


def test_a_two_week_old_report_is_not_placed_in_next_month() -> None:
    # The nearest-month rule read these as 14 November, so a pasted TAF looked upcoming and never expired.
    now = utc(31, 12)
    taf = decode("TAF KDEN 141130Z 1412/1518 06007KT P6SM SKC", now)
    assert taf.issue_time == utc(14, 11, minute=30)
    assert (taf.valid_from, taf.valid_to) == (utc(14, 12), utc(15, 18))
    assert taf.valid_to is not None and taf.valid_to < now
