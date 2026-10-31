"""Splitting pasted text into reports and decoding each as a METAR/SPECI or a TAF."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from wxbrief.decode.model import Metar, ReportType, Taf
from wxbrief.decode.split import Kind, detect_kind, parse_any, split_reports

REF = datetime(2026, 10, 13, 15, 0, tzinfo=UTC)
M1 = "METAR KDEN 131453Z 06007KT 10SM CLR 09/08 A3001"
M2 = "METAR KSEA 131453Z 18014KT 2SM +RA BR OVC007 12/11 A2972"
T1 = "TAF KDEN 131130Z 1312/1418 06007KT P6SM SKC"
T2 = "TAF KSEA 131130Z 1312/1418 18014KT P6SM SKC"


# --- split_reports ---------------------------------------------------------------------------------------------------


def test_one_report_per_line() -> None:
    assert split_reports(f"{M1}\n{M2}") == [M1, M2]


def test_blank_lines_separate_reports_and_any_number_of_them() -> None:
    assert split_reports(f"{M1}\n\n\n{T1}\r\n\r\n{M2}\n") == [M1, T1, M2]


def test_the_equals_sign_ends_a_report_and_stays_on_it() -> None:
    assert split_reports(f"{M1}= {M2}=") == [f"{M1}=", f"{M2}="]
    assert split_reports(f"{T1}=\n{M1}=") == [f"{T1}=", f"{M1}="]


def test_a_taf_wrapped_over_lines_is_one_report() -> None:
    wrapped = f"{T1}\n  FM131800 18010KT P6SM SCT050\n  TEMPO 1320/1324 3SM BR"
    assert split_reports(wrapped) == [wrapped]
    assert split_reports(f"{wrapped}\n{T2}") == [wrapped, T2]


@pytest.mark.parametrize(
    "continuation",
    ["FM131800 18010KT", "BECMG 1315/1317 VRB03KT", "TEMPO 1320/1324 3SM", "INTER 1320/1324 3SM", "PROB30 1320/1324 3SM"],
)
def test_change_group_lines_continue_a_taf_even_without_indentation(continuation: str) -> None:
    text = f"{T1}\n{continuation}"
    assert split_reports(text) == [text]


@pytest.mark.parametrize("continuation", ["TX20/1318Z TN10/1410Z", "TXM02/1318Z", "RMK NXT FCST BY 131700Z", "NOSIG"])
def test_trailer_lines_continue_a_report(continuation: str) -> None:
    text = f"{T1}\n{continuation}"
    assert split_reports(text) == [text]


def test_an_indented_line_continues_whatever_came_before() -> None:
    text = f"{M1}\n      RMK AO2"
    assert split_reports(text) == [text]


def test_a_line_that_continues_nothing_starts_a_report() -> None:
    assert split_reports(f"{T1}\n{M1}") == [T1, M1]
    assert split_reports(f"{M1}\nKSEA 131453Z 18014KT 2SM OVC007 12/11 A2972") == [
        M1,
        "KSEA 131453Z 18014KT 2SM OVC007 12/11 A2972",
    ]


def test_the_nws_bulletin_form_is_one_report_with_its_modifier() -> None:
    text = "TAF AMD\nKDEN 131130Z 1312/1418 06007KT P6SM SKC"
    assert split_reports(text) == [text]
    taf = parse_any(text, REF)[0]
    assert isinstance(taf, Taf) and taf.station == "KDEN" and taf.amended


def test_a_taf_wrapped_before_a_plain_group_is_one_report() -> None:
    text = "TAF KDEN 131130Z 1312/1418 06007KT VRB03KT\nP6SM SKC\nFM131800 18010KT P6SM SKC"
    assert split_reports(text) == [text]
    assert split_reports(f"{text}\n{M1}") == [text, M1]
    assert split_reports(f"{text}\nKSEA 131453Z 18014KT 2SM OVC007 12/11 A2972")[1].startswith("KSEA")


def test_two_reports_on_one_line_are_cut_at_the_second_keyword() -> None:
    assert split_reports(f"{M1} {T1}") == [M1, T1]
    assert split_reports(f"{T1} {M2}") == [T1, M2]


def test_a_keyword_that_does_not_start_a_report_does_not_split() -> None:
    text = "METAR METAR KDEN 131453Z 06007KT 10SM CLR 09/08 A3001"
    assert split_reports(text) == [text]
    assert split_reports("AMD TAF") == ["AMD TAF"]


def test_a_keyword_inside_remarks_is_text_not_a_new_report() -> None:
    one_line = f"{T1} RMK SEE TAF FROM KDEN LATER"
    assert split_reports(one_line) == [one_line]
    wrapped = f"{T1} RMK AMENDED BY\nTAF FROM THE DUTY FORECASTER"
    assert split_reports(wrapped) == [wrapped]
    metar = f"{M1} RMK AO2 SEE TAF KSEA"
    assert split_reports(metar) == [metar]
    assert split_reports(f"{T1} RMK TEST {M2}") == [f"{T1} RMK TEST", M2]
    assert split_reports(f"{T1} RMK TEST\n{T2}") == [f"{T1} RMK TEST", T2]


@pytest.mark.parametrize("header", ["TAF AMD", "TAF", "METAR", "METAR COR"])
def test_a_header_only_line_after_a_report_with_remarks_still_starts_one(header: str) -> None:
    previous = f"{M1} RMK AO2"
    body = "KJFK 311130Z 3112/0112 06007KT P6SM SKC"
    assert split_reports(f"{previous}\n{header}\n{body}") == [previous, f"{header}\n{body}"]


def test_original_line_breaks_are_kept_inside_a_report() -> None:
    wrapped = f"{T1}\n  FM131800 18010KT"
    (report,) = split_reports(wrapped.replace("\n", "\r\n"))
    assert report == wrapped  # CRLF is normalised to LF, the rest is untouched


def test_old_mac_line_ends_work_too() -> None:
    assert split_reports(f"{M1}\r{M2}") == [M1, M2]


@pytest.mark.parametrize("text", ["", " ", "\n\n", " \t\r\n  \n"])
def test_blank_input_has_no_reports(text: str) -> None:
    assert split_reports(text) == []


def test_every_non_blank_character_lands_in_exactly_one_report() -> None:
    text = f"  {M1}=\n{T1}\n   FM131800 18010KT\n\n{M2} {T2}=\n=\nRMK"
    reports = split_reports(text)
    assert "".join("".join(r.split()) for r in reports) == "".join(text.split())


# --- detect_kind -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("report", "kind"),
    [
        (M1, Kind.METAR),
        ("SPECI KSEA 131500Z 18014KT 2SM OVC007 12/11 A2972", Kind.METAR),
        (T1, Kind.TAF),
        ("taf kden 131130z 1312/1418 06007kt", Kind.TAF),
        ("TAF AMD KDEN", Kind.TAF),
        # no keyword: the groups give it away
        ("KDEN 131130Z 1312/1418 06007KT P6SM SKC", Kind.TAF),
        ("KDEN 131130Z 06007KT P6SM SKC FM131800 18010KT", Kind.TAF),
        ("KDEN 06007KT P6SM SKC PROB30 3SM", Kind.TAF),
        ("LFPG BECMG 3110/3112 9999", Kind.TAF),
        ("KDEN 131453Z 06007KT 10SM CLR 09/08 A3001", Kind.METAR),
        ("EGLL 311050Z 24010KT CAVOK 12/08 Q1013 TEMPO 3000", Kind.METAR),  # a trend, with a temperature group
        ("EGLL 141150Z 24015KT 9999 FEW030 Q1018 BECMG 3000 RA", Kind.METAR),  # a pressure group means METAR
        ("KDEN 141150Z 24015KT 9999 FEW030 A2992 TEMPO 3000 RA", Kind.METAR),
        ("", Kind.METAR),
        ("hello", Kind.METAR),
    ],
)
def test_detect_kind(report: str, kind: Kind) -> None:
    assert detect_kind(report) is kind


def test_a_trailing_equals_does_not_hide_the_keyword() -> None:
    assert detect_kind("TAF=") is Kind.TAF


# --- parse_any -------------------------------------------------------------------------------------------------------


def test_parse_any_decodes_a_mixed_blob() -> None:
    blob = f"{M1}\n{T1}\n  FM131800 18010KT P6SM SCT050\n\nSPECI KSEA 131500Z 18014KT 2SM OVC007 12/11 A2972\n{T2}="
    reports = parse_any(blob, REF)
    assert [type(r) for r in reports] == [Metar, Taf, Metar, Taf]
    assert [r.station for r in reports] == ["KDEN", "KDEN", "KSEA", "KSEA"]
    taf = reports[1]
    assert isinstance(taf, Taf)
    assert len(taf.changes) == 1  # the continuation line is part of that TAF
    assert reports[2].report_type is ReportType.SPECI
    assert all(r.warnings == () for r in reports)


def test_parse_any_passes_the_reference_to_both_parsers() -> None:
    metar, taf = parse_any(f"{M1}\n{T1}", REF)
    assert isinstance(metar, Metar) and isinstance(taf, Taf)
    assert metar.observed == datetime(2026, 10, 13, 14, 53, tzinfo=UTC)
    assert taf.issue_time == datetime(2026, 10, 13, 11, 30, tzinfo=UTC)


def test_parse_any_without_a_keyword_guesses_the_kind() -> None:
    (report,) = parse_any("KDEN 131130Z 1312/1418 06007KT P6SM SKC", REF)
    assert isinstance(report, Taf)


def test_parse_any_reads_lower_case() -> None:
    reports = parse_any(f"{M1.lower()}\n{T1.lower()}", REF)
    assert [type(r) for r in reports] == [Metar, Taf]
    assert reports[0].warnings == ()


@pytest.mark.parametrize("text", ["", "   ", "\n"])
def test_parse_any_of_nothing_is_empty(text: str) -> None:
    assert parse_any(text, REF) == []


def test_parse_any_never_raises_on_garbage() -> None:
    assert len(parse_any("\x00 ☃ ???\n=\n/// ///", REF)) >= 1
