"""Sentences for trends, colour states, runway state, recent weather, wind shear, sea state and remarks."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from test_remarks import CASES, all_variants

from wxbrief.decode.metar import parse_metar
from wxbrief.decode.model import (
    ColorCode,
    ColorForecast,
    ColorState,
    ColorStateGroup,
    Flag,
    FreeText,
    Metar,
    SemanticKind,
    TrendKind,
)
from wxbrief.decode.units import Temperature, UnitsMode
from wxbrief.i18n import Translator
from wxbrief.render import measure, phrases
from wxbrief.render.jsonout import to_dict
from wxbrief.render.plain import render_plain

T = Translator.load("en")
US, METRIC, MIXED = UnitsMode.US, UnitsMode.METRIC, UnitsMode.MIXED
REF = datetime(2026, 10, 31, 11, 56, tzinfo=UTC)


def decode(text: str) -> Metar:
    return parse_metar(text, REF)


def icao(tail: str) -> Metar:
    return decode(f"METAR EGLL 311150Z 24010KT 9999 FEW040 12/08 Q1013 {tail}")


def us(rmk: str) -> Metar:
    return decode(f"METAR KDEN 311153Z 18006KT 10SM CLR 08/06 A3004 RMK {rmk}")


# --- trends ----------------------------------------------------------------------------------------------------


def test_nosig() -> None:
    assert phrases.describe_trend(T, icao("NOSIG").trends[0], MIXED) == "No significant change expected in the next 2 hours"


def test_becoming_with_times() -> None:
    trend = icao("BECMG FM1130 TL1230 0350 FG").trends[0]
    assert phrases.describe_trend(T, trend, MIXED) == (
        "Lasting change from 11:30 UTC until 12:30 UTC: visibility 350 m (3/16 SM); fog"
    )


def test_tempo_without_times() -> None:
    trend = icao("TEMPO 3000 TSRA BKN010CB").trends[0]
    text = phrases.describe_trend(T, trend, METRIC)
    assert text == "Temporary fluctuation: visibility 3 km; thunderstorm with rain; sky broken clouds at 305 m (1,000 ft), cumulonimbus"


def test_trend_with_wind_and_gusts_in_metres_per_second() -> None:
    trend = icao("TEMPO 35008G13MPS").trends[0]
    assert phrases.describe_trend(T, trend, METRIC).startswith("Temporary fluctuation: wind from 350")
    assert "gusting to 13 m/s" in phrases.describe_trend(T, trend, METRIC)


def test_trend_cavok_and_nsw() -> None:
    assert "CAVOK" in phrases.describe_trend(T, icao("BECMG CAVOK").trends[0], MIXED)
    assert phrases.describe_trend(T, icao("BECMG NSW").trends[0], MIXED) == "Lasting change: no significant weather"


def test_trend_without_details() -> None:
    assert phrases.describe_trend(T, icao("TEMPO").trends[0], MIXED) == "Temporary fluctuation: no details given"
    assert phrases.describe_trend(T, icao("BECMG AT1200").trends[0], MIXED) == "Lasting change at 12:00 UTC: no details given"


def test_trend_time_uses_the_resolved_moment() -> None:
    metar = decode("METAR EGLL 312350Z 24010KT 9999 FEW040 12/08 Q1013 BECMG TL0030 4000")
    assert phrases.describe_trend_time(T, metar.trends[0].times[0]) == "until 00:30 UTC"
    metar = decode("METAR EGLL 311150Z 24010KT 9999 FEW040 12/08 Q1013 BECMG TL2400 4000")
    assert phrases.describe_trend_time(T, metar.trends[0].times[0]) == "until 00:00 UTC"


# --- colour states ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (ColorState(ColorCode.BLU), "Blue (BLU)"),
        (ColorState(ColorCode.BLU, plus=True), "Blue plus (BLU+): visibility 8 km or more, no ceiling below 20,000 ft"),
        (ColorState(ColorCode.YLO1), "Yellow 1 (YLO1)"),
        (ColorState(ColorCode.YLO2), "Yellow 2 (YLO2)"),
        (ColorState(ColorCode.YLO), "Yellow (YLO)"),
        (ColorState(ColorCode.AMB), "Amber (AMB)"),
        (ColorState(ColorCode.RED), "Red (RED)"),
        (ColorState(ColorCode.RED, black=True), "Airfield closed for reasons other than weather (BLACK); weather state Red (RED)"),
        (ColorState(None, black=True), "Airfield closed for reasons other than weather (BLACK)"),
        (ColorState(None, not_reported=True), "Not reported"),
    ],
)
def test_color_code(state: ColorState, expected: str) -> None:
    assert phrases.describe_color_code(T, state) == expected


def test_color_group_with_forecast() -> None:
    group = ColorStateGroup(
        ColorState(ColorCode.GRN),
        (ColorForecast(ColorState(ColorCode.WHT)), ColorForecast(ColorState(ColorCode.GRN), TrendKind.TEMPO)),
    )
    assert phrases.describe_color_state(T, group) == (
        "Green (GRN); forecast: White (WHT) expected, temporarily Green (GRN)"
    )
    becoming = ColorStateGroup(ColorState(ColorCode.RED), (ColorForecast(ColorState(ColorCode.AMB), TrendKind.BECMG),))
    assert phrases.describe_color_state(T, becoming) == "Red (RED); forecast: becoming Amber (AMB)"
    assert phrases.describe_color_state(T, ColorStateGroup(ColorState(ColorCode.BLU))) == "Blue (BLU)"
    assert phrases.describe_color_state(T, ColorStateGroup(None, (ColorForecast(ColorState(ColorCode.YLO2), TrendKind.TEMPO),))) == (
        "Forecast: temporarily Yellow 2 (YLO2)"
    )
    assert phrases.describe_color_state(T, ColorStateGroup(None)) == "Not reported"


def test_plain_decode_shows_a_colour_state_and_flags_one_below_green() -> None:
    text = render_plain(icao("YLO1 YLO1"), T, MIXED)
    assert "Color state:" in text
    assert "Yellow 1 (YLO1); forecast: Yellow 1 (YLO1) expected" in text
    assert "Color state below Green" in text


def test_plain_decode_shows_the_computed_state_only_when_it_is_not_confirmed() -> None:
    matching = render_plain(decode("METAR ETNL 310820Z 35004KT 9999 OVC012 10/07 Q1032 GRN"), T, MIXED)
    assert "(computed)" not in matching
    differing = render_plain(decode("METAR ETNL 310820Z 35004KT 9999 OVC012 10/07 Q1032 BLU"), T, MIXED)
    assert "Color state (computed): Green (GRN)" in differing
    unreported = render_plain(decode("METAR ETNL 310820Z AUTO 35004KT 9999 // ////// 10/07 Q1032 ///"), T, MIXED)
    assert "Color state:" in unreported
    assert "Not reported" in unreported
    assert "Color state (computed): Blue (BLU)" in unreported


# --- runway state ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("group", "expected"),
    [
        (
            "R24L/290255",
            "Runway 24L: wet or water patches; 51 to 100% of the runway covered; 2 mm deep; braking coefficient 0.55",
        ),
        (
            "8849//91",
            "All runways: dry snow; 51 to 100% of the runway covered; depth not significant or not measurable; "
            "braking action poor",
        ),
        ("R06R/CLRD62", "Runway 06R: contamination has ceased or been cleared, braking coefficient 0.62"),
        ("R09/CLRD//", "Runway 09: contamination has ceased or been cleared"),
        ("R/SNOCLO", "Aerodrome closed by snow"),
        ("SNOCLO", "Aerodrome closed by snow"),
        ("99//////", "Runway state repeated from the previous report"),
        ("R25L/0///72", "Runway 25L: clear and dry; depth not significant or not measurable; braking coefficient 0.72"),
        ("R24L/6///99", "Runway 24L: slush; depth not significant or not measurable; braking not reliable"),
        ("R24L///////", "Runway 24L: depth not significant or not measurable"),
        ("R24L/7550//", "Runway 24L: ice; 26 to 50% of the runway covered; 50 mm deep"),
        (
            "R24L/4999//",
            "Runway 24L: dry snow; 51 to 100% of the runway covered; "
            "runway not operational because of the deposit (depth not reported)",
        ),
        ("R24L/7591//", "Runway 24L: ice; 26 to 50% of the runway covered; depth code reserved"),
    ],
)
def test_runway_state(group: str, expected: str) -> None:
    metar = icao(group)
    assert len(metar.runway_states) == 1
    assert phrases.describe_runway_state(T, metar.runway_states[0], METRIC) == expected


def test_runway_state_depths_in_the_other_system() -> None:
    state = icao("R24L/290255").runway_states[0]
    assert phrases.describe_runway_state(T, state, US) == (
        "Runway 24L: wet or water patches; 51 to 100% of the runway covered; 0.08 in (2 mm) deep; "
        "braking coefficient 0.55"
    )
    deep = icao("R24L/7595//").runway_states[0]
    assert phrases.describe_runway_state(T, deep, METRIC).endswith("25 cm deep")
    assert phrases.describe_runway_state(T, deep, US).endswith("9.84 in (25 cm) deep")
    assert phrases.describe_runway_state(T, icao("R24L/7598//").runway_states[0], METRIC).endswith("40 cm deep or more")


def test_runway_state_row_in_the_plain_decode() -> None:
    text = render_plain(icao("R24L/290255 NOSIG"), T, MIXED)
    assert "Runway state:" in text
    assert "Runway 24L: wet or water patches" in text
    assert "Contaminated" not in text  # wet is not a contaminating deposit for the flag


def test_contaminated_flag() -> None:
    assert Flag.RUNWAY_CONTAMINATED in icao("R24L/490255").flags  # dry snow
    assert Flag.RUNWAY_CONTAMINATED in icao("R/SNOCLO").flags
    assert Flag.RUNWAY_CONTAMINATED not in icao("R24L/290255").flags  # wet
    assert Flag.RUNWAY_CONTAMINATED not in icao("R24L/CLRD62").flags


# --- recent weather, wind shear, sea state ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("group", "expected"),
    [
        ("RERA", "Rain since the last report, now ended"),
        ("RETSRA", "Thunderstorm with rain since the last report, now ended"),
        ("RESHRA", "Rain showers since the last report, now ended"),
        ("REFZRA", "Freezing rain since the last report, now ended"),
        ("RETS", "Thunderstorm since the last report, now ended"),
        ("RE+RA", "Heavy rain since the last report, now ended"),
        ("REBLSN", "Blowing snow since the last report, now ended"),
    ],
)
def test_recent_weather(group: str, expected: str) -> None:
    assert phrases.describe_recent_weather(T, icao(group).recent_weather[0]) == expected


def test_wind_shear() -> None:
    assert phrases.describe_wind_shear(T, icao("WS ALL RWY").wind_shear) == "Wind shear on all runways"
    assert phrases.describe_wind_shear(T, icao("WS R24L").wind_shear) == "Wind shear on runway 24L"
    assert phrases.describe_wind_shear(T, icao("WS R24L R24R").wind_shear) == "Wind shear on runway 24L and runway 24R"
    assert Flag.WIND_SHEAR in icao("WS R24L").flags


@pytest.mark.parametrize(
    ("group", "units", "expected"),
    [
        ("W15/S3", MIXED, "Water temperature 15 °C (59 °F), sea state 3 (slight)"),
        ("W15/S3", US, "Water temperature 59 °F (15 °C), sea state 3 (slight)"),
        ("WM02/S9", METRIC, "Water temperature -2 °C, sea state 9 (phenomenal)"),
        ("W15/H10", METRIC, "Water temperature 15 °C, significant wave height 1 m"),
        ("W12/H025", US, "Water temperature 54 °F (12 °C), significant wave height 8.2 ft (2.5 m)"),
        ("W///S/", MIXED, "No details reported"),
    ],
)
def test_sea_state(group: str, units: UnitsMode, expected: str) -> None:
    metar = icao(group)
    assert metar.sea_state is not None
    assert phrases.describe_sea_state(T, metar.sea_state, units) == expected


# --- remarks ---------------------------------------------------------------------------------------------------


def described(rmk: str, units: UnitsMode = MIXED) -> list[str]:
    return [phrases.describe_remark(T, remark, units) for remark in us(rmk).remarks]


@pytest.mark.parametrize(
    ("rmk", "expected"),
    [
        ("AO2", "Automated station with a precipitation discriminator"),
        ("AO1", "Automated station without a precipitation discriminator (cannot tell rain from snow)"),
        ("PK WND 28045/1547", "Peak wind from 280° (W) at 45 kt (83 km/h), at 15:47 UTC"),
        ("PK WND 20032/25", "Peak wind from 200° (SSW) at 32 kt (59 km/h), at 25 min past the hour"),
        ("WSHFT 1715", "Wind shift began at 17:15 UTC"),
        ("WSHFT 30 FROPA", "Wind shift began at 30 min past the hour, with a frontal passage"),
        ("TWR VIS 2", "Visibility from the control tower: 2 SM (3.2 km)"),
        ("SFC VIS 3/4", "Surface visibility: 3/4 SM (1.2 km)"),
        ("VIS 3/4V1 1/2", "Visibility varying between 3/4 SM (1.2 km) and 1 1/2 SM (2.4 km)"),
        ("VIS NE 2 1/2", "Visibility 2 1/2 SM (4 km) toward northeast"),
        ("VIS 3/4 RWY11", "Visibility 3/4 SM (1.2 km) at runway 11"),
        ("FRQ LTG CG NE", "Frequent cloud-to-ground lightning, northeast"),
        ("LTG DSNT SW", "Lightning, distant southwest"),
        ("OCNL LTGICCG OHD", "Occasional in-cloud and cloud-to-ground lightning, overhead"),
        ("CONS LTG", "Continuous lightning"),
        ("RAB07E45", "Rain began at 7 min past the hour and ended at 45 min past the hour"),
        ("TSB0159E30", "Thunderstorm began at 01:59 UTC and ended at 30 min past the hour"),
        ("SHRAB25", "Rain showers began at 25 min past the hour"),
        ("DZB04E37RAB37", "Drizzle began at 4 min past the hour and ended at 37 min past the hour; Rain began at 37 min past the hour"),
        ("-SNB10", "Light snow began at 10 min past the hour"),
        ("CIG 013V017", "Ceiling varying between 1,300 ft (396 m) and 1,700 ft (518 m)"),
        ("CIG 017 RWY11", "Ceiling 1,700 ft (518 m) at runway 11"),
        ("PRESRR", "Pressure rising rapidly"),
        ("PRESFR", "Pressure falling rapidly"),
        ("SLP177", "Sea-level pressure 1017.7 hPa (30.05 inHg)"),
        ("SLPNO", "Sea-level pressure not available"),
        ("P0003", "Precipitation since the last report: 0.03 in (0.8 mm)"),
        ("P0000", "Precipitation since the last report: a trace"),
        ("P////", "Precipitation since the last report: not reported"),
        ("60009", "Precipitation in the past 6 hours: 0.09 in (2.3 mm)"),
        ("70015", "Precipitation in the past 24 hours: 0.15 in (3.8 mm)"),
        ("T02330200", "Temperature 23.3 °C (73.9 °F), dew point 20.0 °C (68.0 °F)"),
        ("T10171028", "Temperature -1.7 °C (28.9 °F), dew point -2.8 °C (27.0 °F)"),
        ("10233", "6-hour maximum temperature 23.3 °C (73.9 °F)"),
        ("20189", "6-hour minimum temperature 18.9 °C (66.0 °F)"),
        ("1////", "6-hour maximum temperature not reported"),
        ("400461006", "24-hour maximum temperature 4.6 °C (40.3 °F), minimum -0.6 °C (30.9 °F)"),
        ("53008", "Pressure 0.8 hPa (0.02 inHg) higher than 3 hours ago (falling or steady, then rising, or rising more quickly)"),
        ("58033", "Pressure 3.3 hPa (0.10 inHg) lower than 3 hours ago (steady or rising, then falling, or falling more quickly)"),
        ("54000", "Pressure the same as 3 hours ago (steady)"),
        ("RVRNO", "Runway visual range sensor not operating"),
        ("PWINO", "Present-weather sensor not operating"),
        ("PNO", "Precipitation gauge not operating"),
        ("FZRANO", "Freezing-rain sensor not operating"),
        ("TSNO", "Lightning sensor not operating"),
        ("VISNO RWY11", "Visibility sensor not operating (at runway 11)"),
        ("CHINO", "Cloud-height sensor not operating"),
        ("$", "The automated system needs maintenance"),
        ("4/012", "Snow depth on the ground: 12 in (304.8 mm)"),
        ("SNINCR 2/10", "Snow depth increased by 2 in (50.8 mm) in the past hour, now 10 in (254 mm) on the ground"),
        ("8/208", "Cloud types: low: cumulus mediocris or congestus; middle: no middle cloud; high: cirrostratus not covering the whole sky"),
        ("GR 1 3/4", "Hail up to 1.75 in (44.4 mm)"),
        ("GR LESS THAN 1/4", "Hail smaller than 0.25 in (6.3 mm)"),
        ("DENSITY ALT 2500FT", "Density altitude 2,500 ft (762 m)"),
        ("SC5AC2", "Cloud layers: stratocumulus covering 5/8 of the sky; altocumulus covering 2/8 of the sky"),
        ("AC1 AC TR", "Cloud layers: altocumulus covering 1/8 of the sky; altocumulus, a trace"),
        ("A3007", "Altimeter setting 30.07 inHg (1018 hPa)"),
        ("QFE756/1008", "Station pressure (QFE): 756 mmHg (1008 hPa)"),
        ("QNH766", "Pressure reduced to sea level (QNH): 766 mmHg"),
        ("QFE992", "Station pressure (QFE): 992 hPa"),
        ("RWY17L 02008KT", "Wind at runway 17L: from 020° (NNE) at 8 kt (15 km/h)"),
        ("R06/31003MPS", "Wind at runway 06: from 310° (NW) at 3 m/s (6 kt)"),
        ("WIND 2600FT 19040KT", "Wind at 2,600 ft (792 m): from 190° (S) at 40 kt (74 km/h)"),
        ("YLO1 YLO1", "Color state: Yellow 1 (YLO1); forecast: Yellow 1 (YLO1) expected"),
    ],
)
def test_remark_sentences(rmk: str, expected: str) -> None:
    sentences = described(rmk)
    assert sentences == [expected]


def test_the_period_precipitation_sentence_follows_the_report_time() -> None:
    three = decode("METAR KDEN 311453Z 18006KT 10SM CLR 08/06 A3004 RMK AO2 60009")
    assert phrases.describe_remark(T, three.remarks[1], MIXED) == "Precipitation in the past 3 hours: 0.09 in (2.3 mm)"
    other = decode("METAR KDEN 311053Z 18006KT 10SM CLR 08/06 A3004 RMK AO2 60009")
    assert phrases.describe_remark(T, other.remarks[1], MIXED) == "Precipitation over the 3 or 6-hour period: 0.09 in (2.3 mm)"


def test_remark_units() -> None:
    assert described("P0003", US) == ["Precipitation since the last report: 0.03 in"]
    assert described("P0003", METRIC) == ["Precipitation since the last report: 0.8 mm (0.03 in)"]
    assert described("T02330200", US) == ["Temperature 73.9 °F (23.3 °C), dew point 68.0 °F (20.0 °C)"]
    assert described("SLP177", US) == ["Sea-level pressure 30.05 inHg (1017.7 hPa)"]
    assert described("53008", METRIC)[0].startswith("Pressure 0.8 hPa higher")


def test_every_variant_has_a_sentence() -> None:
    """``describe_remark`` falls back to the class name for a variant it does not know: that must never show."""
    seen = set()
    for text, expected in CASES:
        for remark in expected:
            sentence = phrases.describe_remark(T, remark, MIXED)
            assert sentence
            assert sentence != type(remark).__name__, text
            seen.add(type(remark))
    assert seen == all_variants()


# --- free text -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("CB DSNT NW", "Cumulonimbus distant northwest"),
        ("TCU DSNT NE-E AND NW", "Towering cumulus distant northeast to east and northwest"),
        ("MTNS OBSC NE-SE", "Mountains obscured northeast to southeast"),
        ("TORNADO B25 N MOV E", "Tornado began at 25 min past the hour north moving east"),
        ("FUNNEL CLOUD E1230", "Funnel cloud ended at 12:30 UTC"),
        ("CVCTV CLD EMBD", "Convective cloud embedded"),
        ("VIRGA", "Virga"),
        ("OBST OBSC", "Obstructions obscured"),
        ("ZZZ CB", "ZZZ cumulonimbus"),
    ],
)
def test_free_text_words(text: str, expected: str) -> None:
    assert phrases.describe_free_text(T, text) == expected


def test_undecoded_free_text_is_listed_in_a_raw_row() -> None:
    metar = us("AO2 SLP135 VIRGA FOO BAR 933008")
    assert phrases.undecoded_free_text(T, metar) == ["FOO BAR 933008"]
    lines = render_plain(metar, T, MIXED).splitlines()
    assert any(line.startswith("Remark:") and line.endswith("Virga FOO BAR 933008") for line in lines)
    assert any(line.startswith("Remarks (not decoded):") and line.endswith("FOO BAR 933008") for line in lines)


def test_fully_decoded_free_text_has_no_raw_row() -> None:
    metar = us("AO2 CB DSNT NW")
    assert phrases.undecoded_free_text(T, metar) == []
    assert "not decoded" not in render_plain(metar, T, MIXED)


def test_raw_remarks_row_is_absent_without_remarks() -> None:
    text = render_plain(icao("NOSIG"), T, MIXED)
    assert "Remark" not in text


# --- the plain decode of the three acceptance reports -----------------------------------------------------------


def test_remarks_heavy_us_report_is_fully_decoded() -> None:
    raw = (
        "METAR KJAX 310556Z 01005KT 10SM OVC007 21/20 A3015 RMK AO2 DZB24E40 SLP208 P0000 60000 T02110200 "
        "10211 20206 58003 $"
    )
    metar = parse_metar(raw, datetime(2026, 10, 31, 6, 0, tzinfo=UTC))
    text = render_plain(metar, T, MIXED)
    assert metar.warnings == ()
    assert "Unrecognized" not in text
    assert "not decoded" not in text
    for expected in (
        "Drizzle began at 24 min past the hour and ended at 40 min past the hour",
        "Sea-level pressure 1020.8 hPa",
        "Precipitation in the past 6 hours: a trace",
        "Temperature 21.1 °C",
        "6-hour maximum temperature 21.1 °C",
        "6-hour minimum temperature 20.6 °C",
        "Pressure 0.3 hPa",
        "The automated system needs maintenance",
    ):
        assert expected in text


def test_military_report_with_a_color_state_is_fully_decoded() -> None:
    raw = "METAR ETMN 310820Z 00000KT 4500 BR BKN022 10/10 Q1033 GRN WHT TEMPO GRN"
    metar = parse_metar(raw, datetime(2026, 10, 31, 9, 0, tzinfo=UTC))
    text = render_plain(metar, T, MIXED)
    assert metar.warnings == ()
    assert "Color state:" in text
    assert "Green (GRN); forecast: White (WHT) expected, temporarily Green (GRN)" in text
    assert "Unrecognized" not in text


def test_russian_report_with_a_runway_state_is_fully_decoded() -> None:
    raw = "METAR UUWW 310830Z 13003MPS CAVOK 07/M01 Q1024 R24/000062 NOSIG"
    metar = parse_metar(raw, datetime(2026, 10, 31, 9, 0, tzinfo=UTC))
    text = render_plain(metar, T, MIXED)
    assert metar.warnings == ()
    assert "Runway 24: clear and dry; no contamination; less than 1 mm deep; braking coefficient 0.62" in text
    assert "Trend:" in text
    assert "Unrecognized" not in text


# --- JSON ------------------------------------------------------------------------------------------------------


def test_json_names_the_remark_variant() -> None:
    data = to_dict(us("AO2 SLP177 FOO"))
    json.dumps(data)
    assert [remark["variant"] for remark in data["remarks"]] == ["AutomatedStationType", "SeaLevelPressure", "FreeText"]
    assert data["remarks"][1]["pressure"] == {"value": 1017.7, "unit": "HPA"}
    assert data["remarks"][2]["text"] == "FOO"


def test_json_covers_the_tail_nodes() -> None:
    data = to_dict(decode("METAR ETHB 311050Z 27008KT 9999 SCT025 08/03 Q1018 RERA WS R24 R24L/290255 W11/S5 BLU TEMPO YLO NOSIG"))
    assert data["color_state"]["current"]["code"] == "BLU"
    assert data["color_state"]["forecast"][0] == {"state": {"code": "YLO", "black": False, "plus": False, "not_reported": False}, "change": "TEMPO"}
    assert data["runway_states"][0]["deposit"] == "WET"
    assert data["recent_weather"][0]["weather"]["phenomena"] == ["RA"]
    assert data["wind_shear"] == [{"runway": "24", "all_runways": False}]
    assert data["sea_state"]["state"] == 5
    assert data["trends"][0]["kind"] == "NOSIG"
    assert data["computed_color_state"] == "BLU"


# --- measure ---------------------------------------------------------------------------------------------------


def test_measure_inches_and_millimetres() -> None:
    assert measure.format_inches(0.03, US) == "0.03 in"
    assert measure.format_inches(0.03, MIXED) == "0.03 in (0.8 mm)"
    assert measure.format_inches(1.75, METRIC) == "44.4 mm (1.75 in)"
    assert measure.format_millimeters(2, METRIC) == "2 mm"
    assert measure.format_millimeters(250, METRIC) == "25 cm"
    assert measure.format_millimeters(250, US) == "9.84 in (25 cm)"
    assert measure.format_wave_height(2.5, MIXED) == "2.5 m (8.2 ft)"


def test_measure_precise_values() -> None:
    from wxbrief.decode.units import Pressure, PressureUnit, Temperature

    assert measure.format_temperature(Temperature(23.3), MIXED, precise=True) == "23.3 °C (73.9 °F)"
    assert measure.format_temperature(Temperature(20.0), METRIC, precise=True) == "20.0 °C"
    assert measure.format_temperature(Temperature(20.0), US, precise=True) == "68.0 °F (20.0 °C)"
    assert measure.format_pressure(Pressure(1017.7, PressureUnit.HPA), MIXED, precise=True) == "1017.7 hPa (30.05 inHg)"
    assert measure.format_pressure(Pressure(1017.7, PressureUnit.HPA), MIXED) == "1018 hPa (30.05 inHg)"
    assert measure.format_pressure_change(1.1, MIXED) == "1.1 hPa (0.03 inHg)"
    assert measure.format_pressure_change(1.1, US) == "0.03 inHg (1.1 hPa)"


# --- finer token kinds -----------------------------------------------------------------------------------------


def test_trend_and_remark_tokens_carry_finer_kinds() -> None:
    metar = decode("METAR EGLL 311150Z 24010KT 9999 FEW040 12/08 Q1013 BECMG FM1200 25015G25KT 4000 -RA BKN010 RMK SLP177 FOO")
    kinds = {tok.text: tok.kind for tok in metar.tokens}
    assert kinds["BECMG"] is SemanticKind.TREND
    assert kinds["FM1200"] is SemanticKind.TREND
    assert kinds["25015G25KT"] is SemanticKind.WIND
    assert kinds["4000"] is SemanticKind.VISIBILITY
    assert kinds["-RA"] is SemanticKind.WEATHER
    assert kinds["BKN010"] is SemanticKind.SKY
    assert kinds["SLP177"] is SemanticKind.PRESSURE
    assert kinds["FOO"] is SemanticKind.REMARK
    assert isinstance(metar.remarks[-1], FreeText)


def test_a_temperature_that_rounds_to_zero_is_not_shown_as_negative_zero() -> None:
    # -17.8 C is -0.04 F
    assert measure.format_temperature(Temperature(-17.8), US, precise=True) == "0.0 °F (-17.8 °C)"
    text = render_plain(parse_metar("METAR KDEN 141153Z 06007KT 10SM CLR M18/M18 A3001 RMK AO2 T11281178", REF), T, US)
    assert "-0.0" not in text
    assert "dew point 0.0 °F (-17.8 °C)" in text
