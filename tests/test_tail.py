"""The groups between the pressure and RMK, one parser at a time, then the dispatcher."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest

from wxbrief.decode.groups.colorstate import color_state_of, is_color_state, parse_color_state_group
from wxbrief.decode.groups.recentwx import parse_recent_weather, recent_weather_of
from wxbrief.decode.groups.runwaystate import decode_braking, decode_depth, is_runway_state, parse_runway_state
from wxbrief.decode.groups.seastate import parse_sea_state
from wxbrief.decode.groups.tail import parse_tail_group
from wxbrief.decode.groups.trend import parse_trend, parse_trend_time
from wxbrief.decode.groups.windshear import parse_wind_shear
from wxbrief.decode.model import (
    BrakingAction,
    CloudLayer,
    ColorCode,
    ColorForecast,
    ColorState,
    ColorStateGroup,
    Descriptor,
    Flavor,
    Intensity,
    Phenomenon,
    RecentWeather,
    RunwayBraking,
    RunwayDeposit,
    RunwayDepth,
    RunwayDepthKind,
    RunwayExtent,
    RunwayState,
    SeaState,
    SemanticKind,
    SkyCondition,
    Trend,
    TrendKind,
    TrendTime,
    TrendTimeKind,
    WeatherGroup,
    WindShearRunway,
)
from wxbrief.decode.tokens import Cursor, tokenize
from wxbrief.decode.units import Distance, DistanceUnit, Speed, SpeedUnit, Temperature, TemperatureUnit

OBSERVED = datetime(2026, 10, 31, 11, 20, tzinfo=UTC)


def run(parser: Callable[[Cursor], Any], text: str) -> tuple[Any, list[SemanticKind], int]:
    """Run ``parser`` on ``text``: the value, the kind of every token afterwards, and how many tokens were used."""
    cur = Cursor(tokenize(text))
    value = parser(cur)
    return value, [tok.kind for tok in cur.tagged()], cur.pos


def never_stops(_token: object) -> bool:
    return False


# --- colour states ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "code", "black", "plus"),
    [
        ("BLU", ColorCode.BLU, False, False),
        ("WHT", ColorCode.WHT, False, False),
        ("GRN", ColorCode.GRN, False, False),
        ("YLO", ColorCode.YLO, False, False),
        ("YLO1", ColorCode.YLO1, False, False),
        ("YLO2", ColorCode.YLO2, False, False),
        ("AMB", ColorCode.AMB, False, False),
        ("RED", ColorCode.RED, False, False),
        ("BLU+", ColorCode.BLU, False, True),
        ("BLACKRED", ColorCode.RED, True, False),
        ("BLACKBLU+", ColorCode.BLU, True, True),
        ("BLACK", None, True, False),
    ],
)
def test_color_state_codes(text: str, code: ColorCode | None, black: bool, plus: bool) -> None:
    assert color_state_of(text) == ColorState(code, black=black, plus=plus)
    assert is_color_state(text)


def test_slashes_are_a_colour_state_that_was_not_reported() -> None:
    assert color_state_of("///") == ColorState(None, not_reported=True)


@pytest.mark.parametrize("text", ["BLUE", "RE", "REDD", "GREEN", "BL", "YLO3", "+", "BLACK+", "BLACKS", "", "BLU++", "/"])
def test_not_colour_states(text: str) -> None:
    assert color_state_of(text) is None
    assert not is_color_state(text)


def test_a_single_colour() -> None:
    group, kinds, used = run(parse_color_state_group, "BLU NOSIG")
    assert group == ColorStateGroup(ColorState(ColorCode.BLU))
    assert used == 1
    assert kinds == [SemanticKind.COLOR_STATE, SemanticKind.UNKNOWN]


def test_current_and_forecast_colours() -> None:
    group, kinds, used = run(parse_color_state_group, "GRN WHT TEMPO GRN RMK")
    assert group == ColorStateGroup(
        ColorState(ColorCode.GRN),
        (ColorForecast(ColorState(ColorCode.WHT)), ColorForecast(ColorState(ColorCode.GRN), TrendKind.TEMPO)),
    )
    assert used == 4
    assert kinds[:4] == [
        SemanticKind.COLOR_STATE,
        SemanticKind.COLOR_STATE,
        SemanticKind.TREND,
        SemanticKind.COLOR_STATE,
    ]


def test_becoming_a_colour() -> None:
    group, _, used = run(parse_color_state_group, "RED BECMG AMB")
    assert group == ColorStateGroup(ColorState(ColorCode.RED), (ColorForecast(ColorState(ColorCode.AMB), TrendKind.BECMG),))
    assert used == 3


def test_a_group_may_start_with_a_trend_keyword_and_a_colour() -> None:
    group, _, used = run(parse_color_state_group, "TEMPO YLO2")
    assert group == ColorStateGroup(None, (ColorForecast(ColorState(ColorCode.YLO2), TrendKind.TEMPO),))
    assert used == 2


def test_a_trend_keyword_without_a_colour_is_left_for_the_trend_parser() -> None:
    group, _, used = run(parse_color_state_group, "BLU TEMPO 5000 -RA")
    assert group == ColorStateGroup(ColorState(ColorCode.BLU))
    assert used == 1
    assert run(parse_color_state_group, "TEMPO 5000")[0] is None
    assert run(parse_color_state_group, "NOSIG BLU")[0] is None
    assert run(parse_color_state_group, "")[0] is None


# --- trends ----------------------------------------------------------------------------------------------------


def trend(text: str) -> tuple[Trend | None, list[SemanticKind], int]:
    return run(lambda cur: parse_trend(cur, OBSERVED, lambda tok: tok.text == "RMK"), text)


def test_nosig() -> None:
    value, kinds, used = trend("NOSIG RMK")
    assert value == Trend(TrendKind.NOSIG)
    assert kinds == [SemanticKind.TREND, SemanticKind.UNKNOWN]
    assert used == 1


def test_becmg_with_times_and_visibility() -> None:
    value, kinds, used = trend("BECMG FM1130 TL1230 0350 TEMPO 3000")
    assert value is not None
    assert value.kind is TrendKind.BECMG
    assert [(item.kind, item.hour, item.minute) for item in value.times] == [
        (TrendTimeKind.FROM, 11, 30),
        (TrendTimeKind.UNTIL, 12, 30),
    ]
    assert value.elements.visibility is not None
    assert value.elements.visibility.distance == Distance(350, DistanceUnit.M)
    assert used == 4  # TEMPO starts the next group
    assert kinds[:4] == [SemanticKind.TREND, SemanticKind.TREND, SemanticKind.TREND, SemanticKind.VISIBILITY]


def test_trend_times_resolve_against_the_observation() -> None:
    value, _, _ = trend("BECMG AT1200 TL0030")
    assert value is not None
    assert value.times[0].moment == datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
    assert value.times[1].moment == datetime(2026, 10, 31, 0, 30, tzinfo=UTC)  # the nearest 00:30 is earlier today


def test_trend_times_after_midnight_resolve_to_the_next_day() -> None:
    late = datetime(2026, 10, 31, 23, 40, tzinfo=UTC)
    value, _, _ = run(lambda cur: parse_trend_time(cur, late), "TL0030")
    assert value is not None
    assert value.moment == datetime(2026, 11, 1, 0, 30, tzinfo=UTC)


def test_trend_time_at_hour_24_rolls_over() -> None:
    late = datetime(2026, 10, 31, 23, 40, tzinfo=UTC)
    value, _, _ = run(lambda cur: parse_trend_time(cur, late), "TL2400")
    assert value == TrendTime(TrendTimeKind.UNTIL, 24, 0, datetime(2026, 11, 1, 0, 0, tzinfo=UTC))


@pytest.mark.parametrize("text", ["FM2561", "TL1260", "FM24", "AT123", "FM2430", "FMXXXX", "1130"])
def test_bad_trend_times_are_not_times(text: str) -> None:
    assert run(lambda cur: parse_trend_time(cur, OBSERVED), text)[0] is None


def test_trend_time_without_an_observation_keeps_the_clock_only() -> None:
    value, _, _ = run(lambda cur: parse_trend_time(cur, None), "FM1130")
    assert value == TrendTime(TrendTimeKind.FROM, 11, 30, None)


def test_trend_carries_wind_weather_and_sky() -> None:
    value, kinds, used = trend("TEMPO 35008G13MPS 3000 +TSRA BKN010CB")
    assert value is not None
    elements = value.elements
    assert elements.wind is not None
    assert (elements.wind.direction, elements.wind.speed, elements.wind.gust) == (
        350,
        Speed(8, SpeedUnit.MPS),
        Speed(13, SpeedUnit.MPS),
    )
    assert elements.visibility is not None
    assert elements.weather == (WeatherGroup(Intensity.HEAVY, Descriptor.TS, (Phenomenon.RA,)),)
    assert [layer.cover for layer in elements.sky] == [SkyCondition.BKN]
    assert used == 5
    assert kinds == [
        SemanticKind.TREND,
        SemanticKind.WIND,
        SemanticKind.VISIBILITY,
        SemanticKind.WEATHER,
        SemanticKind.SKY,
    ]


def test_trend_nsw_cavok_and_clear_sky_codes() -> None:
    value, _, _ = trend("BECMG NSW")
    assert value is not None
    assert value.elements.weather == (WeatherGroup(nsw=True),)
    value, _, _ = trend("BECMG CAVOK")
    assert value is not None
    assert value.elements.visibility is not None
    assert value.elements.visibility.cavok
    value, _, _ = trend("BECMG NSC")
    assert value is not None
    assert value.elements.sky == (CloudLayer(SkyCondition.NSC),)


def test_trend_with_a_colour_state() -> None:
    value, kinds, _ = trend("TEMPO FM1000 AMB")
    assert value is not None
    assert value.elements.color_state == ColorState(ColorCode.AMB)
    assert kinds == [SemanticKind.TREND, SemanticKind.TREND, SemanticKind.COLOR_STATE]


def test_trend_without_a_body() -> None:
    value, _, used = trend("TEMPO RMK")
    assert value == Trend(TrendKind.TEMPO)
    assert value.elements.is_empty
    assert used == 1


def test_a_token_the_body_cannot_place_stays_unknown_and_the_body_carries_on() -> None:
    value, kinds, used = trend("TEMPO ZZZZ 3000")
    assert value is not None
    assert value.elements.visibility is not None
    assert used == 3
    assert kinds == [SemanticKind.TREND, SemanticKind.UNKNOWN, SemanticKind.VISIBILITY]


def test_a_second_wind_or_colour_in_one_body_is_unknown() -> None:
    _, kinds, _ = trend("TEMPO 35008KT 20010KT")
    assert kinds == [SemanticKind.TREND, SemanticKind.WIND, SemanticKind.UNKNOWN]
    _, kinds, _ = trend("TEMPO AMB RED")
    assert kinds == [SemanticKind.TREND, SemanticKind.COLOR_STATE, SemanticKind.UNKNOWN]


def test_trend_does_not_start_on_other_words() -> None:
    assert trend("RMK AO2")[0] is None
    assert trend("")[0] is None


# --- runway state ----------------------------------------------------------------------------------------------


def test_runway_state_with_a_designator() -> None:
    value, kinds, used = run(parse_runway_state, "R24L/290255 NOSIG")
    assert value == RunwayState(
        runway="24L",
        deposit=RunwayDeposit.WET,
        extent=RunwayExtent.FROM_51_TO_100,
        depth=RunwayDepth(RunwayDepthKind.MILLIMETERS, 2),
        braking=RunwayBraking(coefficient=0.55),
    )
    assert kinds[0] is SemanticKind.RUNWAY_STATE
    assert used == 1


def test_eight_digit_runway_state() -> None:
    value, _, _ = run(parse_runway_state, "88290192")
    assert value == RunwayState(
        all_runways=True,
        deposit=RunwayDeposit.WET,
        extent=RunwayExtent.FROM_51_TO_100,
        depth=RunwayDepth(RunwayDepthKind.MILLIMETERS, 1),
        braking=RunwayBraking(action=BrakingAction.MEDIUM_POOR),
    )


def test_the_reference_example() -> None:
    """From the reference notes: all runways, dry snow, 51-100% covered, depth not measurable, braking poor."""
    value, _, _ = run(parse_runway_state, "8849//91")
    assert value == RunwayState(
        all_runways=True,
        deposit=RunwayDeposit.DRY_SNOW,
        extent=RunwayExtent.FROM_51_TO_100,
        depth=RunwayDepth(RunwayDepthKind.NOT_SIGNIFICANT),
        braking=RunwayBraking(action=BrakingAction.POOR),
    )


@pytest.mark.parametrize(
    ("text", "runway"),
    [("01290255", "01"), ("36290255", "36"), ("51290255", "01R"), ("86290255", "36R"), ("26290255", "26")],
)
def test_eight_digit_runway_numbers(text: str, runway: str) -> None:
    value, _, _ = run(parse_runway_state, text)
    assert value is not None
    assert value.runway == runway


def test_eight_digit_repeat_and_invalid_runways() -> None:
    value, _, _ = run(parse_runway_state, "99//////")
    assert value is not None
    assert value.repeated
    assert value.runway is None
    for text in ("00290255", "37290255", "50290255", "87290255", "98290255"):
        assert run(parse_runway_state, text)[0] is None, text


def test_runway_cleared() -> None:
    value, _, _ = run(parse_runway_state, "R06R/CLRD62")
    assert value == RunwayState(runway="06R", cleared=True, braking=RunwayBraking(coefficient=0.62))
    value, _, _ = run(parse_runway_state, "R09/CLRD//")
    assert value == RunwayState(runway="09", cleared=True)


def test_snow_closed() -> None:
    assert run(parse_runway_state, "R/SNOCLO")[0] == RunwayState(snoclo=True, all_runways=True)
    assert run(parse_runway_state, "SNOCLO")[0] == RunwayState(snoclo=True)


def test_runway_88_and_99_in_the_designator_form() -> None:
    value, _, _ = run(parse_runway_state, "R88/CLRD//")
    assert value is not None
    assert value.all_runways
    assert value.cleared
    value, _, _ = run(parse_runway_state, "R99/290255")
    assert value is not None
    assert value.repeated


def test_not_reported_values_are_none() -> None:
    value, _, _ = run(parse_runway_state, "R25L/0///72")
    assert value == RunwayState(
        runway="25L",
        deposit=RunwayDeposit.CLEAR_DRY,
        depth=RunwayDepth(RunwayDepthKind.NOT_SIGNIFICANT),
        braking=RunwayBraking(coefficient=0.72),
    )
    value, _, _ = run(parse_runway_state, "R24///////")
    assert value == RunwayState(runway="24", depth=RunwayDepth(RunwayDepthKind.NOT_SIGNIFICANT))


@pytest.mark.parametrize(
    ("code", "kind", "mm"),
    [
        ("//", RunwayDepthKind.NOT_SIGNIFICANT, None),
        ("00", RunwayDepthKind.LESS_THAN_1, None),
        ("01", RunwayDepthKind.MILLIMETERS, 1),
        ("55", RunwayDepthKind.MILLIMETERS, 55),
        ("90", RunwayDepthKind.MILLIMETERS, 90),
        ("91", RunwayDepthKind.RESERVED, None),
        ("92", RunwayDepthKind.MILLIMETERS, 100),
        ("95", RunwayDepthKind.MILLIMETERS, 250),
        ("97", RunwayDepthKind.MILLIMETERS, 350),
        ("98", RunwayDepthKind.AT_LEAST, 400),
        ("99", RunwayDepthKind.NOT_OPERATIONAL, None),
    ],
)
def test_depth_codes(code: str, kind: RunwayDepthKind, mm: int | None) -> None:
    assert decode_depth(code) == RunwayDepth(kind, mm)


def test_half_missing_depth_is_unknown() -> None:
    assert decode_depth("5/") is None


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("00", RunwayBraking(coefficient=0.0)),
        ("35", RunwayBraking(coefficient=0.35)),
        ("90", RunwayBraking(coefficient=0.9)),
        ("91", RunwayBraking(action=BrakingAction.POOR)),
        ("93", RunwayBraking(action=BrakingAction.MEDIUM)),
        ("95", RunwayBraking(action=BrakingAction.GOOD)),
        ("99", RunwayBraking(unreliable=True)),
        ("96", None),
        ("//", None),
    ],
)
def test_braking_codes(code: str, expected: RunwayBraking | None) -> None:
    assert decode_braking(code) == expected


@pytest.mark.parametrize("text", ["9999", "R35L/P6000FT", "R12/1000U", "BKN010", "88290", "R24L/29025", "NOSIG"])
def test_not_runway_states(text: str) -> None:
    assert not is_runway_state(text)
    assert run(parse_runway_state, text)[0] is None


# --- recent weather --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "descriptor", "phenomena", "intensity"),
    [
        ("RERA", None, (Phenomenon.RA,), Intensity.MODERATE),
        ("RETSRA", Descriptor.TS, (Phenomenon.RA,), Intensity.MODERATE),
        ("RESHRA", Descriptor.SH, (Phenomenon.RA,), Intensity.MODERATE),
        ("REFZRA", Descriptor.FZ, (Phenomenon.RA,), Intensity.MODERATE),
        ("REBLSN", Descriptor.BL, (Phenomenon.SN,), Intensity.MODERATE),
        ("RETS", Descriptor.TS, (), Intensity.MODERATE),
        ("RERASN", None, (Phenomenon.RA, Phenomenon.SN), Intensity.MODERATE),
        ("RE+RA", None, (Phenomenon.RA,), Intensity.HEAVY),
        ("RE-SN", None, (Phenomenon.SN,), Intensity.LIGHT),
        ("REVA", None, (Phenomenon.VA,), Intensity.MODERATE),
        ("REFC", None, (Phenomenon.FC,), Intensity.MODERATE),
    ],
)
def test_recent_weather(text: str, descriptor: Descriptor | None, phenomena: tuple[Phenomenon, ...], intensity: Intensity) -> None:
    assert recent_weather_of(text) == RecentWeather(WeatherGroup(intensity, descriptor, phenomena))
    value, kinds, _ = run(parse_recent_weather, text)
    assert value is not None
    assert kinds == [SemanticKind.RECENT_WEATHER]


@pytest.mark.parametrize("text", ["RE", "REX", "REMARK", "RERAX", "REFZ", "RE+", "RESN1", "RERESN", "RA", "REDD"])
def test_not_recent_weather(text: str) -> None:
    assert recent_weather_of(text) is None
    assert run(parse_recent_weather, text)[0] is None


# --- wind shear ------------------------------------------------------------------------------------------------


def test_wind_shear_all_runways() -> None:
    value, kinds, used = run(parse_wind_shear, "WS ALL RWY NOSIG")
    assert value == (WindShearRunway(all_runways=True),)
    assert used == 3
    assert kinds[:3] == [SemanticKind.WIND_SHEAR] * 3
    assert kinds[3] is SemanticKind.UNKNOWN


@pytest.mark.parametrize(
    ("text", "used"),
    [("WS R24L", 2), ("WS RWY24L", 2), ("WS RWY 24L", 3), ("WS 24L", 2), ("WS R05", 2)],
)
def test_wind_shear_on_a_runway(text: str, used: int) -> None:
    value, _, consumed = run(parse_wind_shear, text)
    assert value is not None
    assert len(value) == 1
    assert value[0].runway == text.split()[-1].removeprefix("RWY").removeprefix("R")
    assert consumed == used


def test_wind_shear_on_several_runways() -> None:
    value, _, used = run(parse_wind_shear, "WS R24L R24R TEMPO")
    assert value == (WindShearRunway(runway="24L"), WindShearRunway(runway="24R"))
    assert used == 3


@pytest.mark.parametrize("text", ["WS", "WS NOSIG", "WS RWY", "WS020/30035KT", "ALL RWY", "WSHFT"])
def test_not_wind_shear(text: str) -> None:
    value, _, used = run(parse_wind_shear, text)
    assert value is None
    assert used == 0


# --- sea state -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("W15/S3", SeaState(Temperature(15, TemperatureUnit.C), state=3)),
        ("WM02/S4", SeaState(Temperature(-2, TemperatureUnit.C), state=4)),
        ("W15/H10", SeaState(Temperature(15, TemperatureUnit.C), wave_height_m=1.0)),
        ("W12/H025", SeaState(Temperature(12, TemperatureUnit.C), wave_height_m=2.5)),
        ("W///S/", SeaState()),
        ("W15/S/", SeaState(Temperature(15, TemperatureUnit.C))),
        ("W15/H///", SeaState(Temperature(15, TemperatureUnit.C))),
    ],
)
def test_sea_state(text: str, expected: SeaState) -> None:
    value, kinds, _ = run(parse_sea_state, text)
    assert value == expected
    assert kinds == [SemanticKind.SEA_STATE]


@pytest.mark.parametrize("text", ["W15", "W15/X3", "15/S3", "WW/S3", "W15/S33", "W15/H"])
def test_not_sea_state(text: str) -> None:
    assert run(parse_sea_state, text)[0] is None


# --- the dispatcher --------------------------------------------------------------------------------------------


def tail(text: str, flavor: Flavor = Flavor.ICAO) -> tuple[Any, list[SemanticKind], int]:
    return run(lambda cur: parse_tail_group(cur, flavor, OBSERVED), text)


def test_dispatcher_picks_the_right_parser() -> None:
    expected = {
        "NOSIG": (SemanticKind.TREND, "trend"),
        "BECMG 3000": (SemanticKind.TREND, "trend"),
        "BLU": (SemanticKind.COLOR_STATE, "color_state"),
        "TEMPO YLO": (SemanticKind.COLOR_STATE, "color_state"),
        "WS R24": (SemanticKind.WIND_SHEAR, "wind_shear"),
        "RERA": (SemanticKind.RECENT_WEATHER, "recent_weather"),
        "W15/S3": (SemanticKind.SEA_STATE, "sea_state"),
        "R24/290255": (SemanticKind.RUNWAY_STATE, "runway_state"),
        "88290192": (SemanticKind.RUNWAY_STATE, "runway_state"),
    }
    for text, (kind, field) in expected.items():
        result, _, _ = tail(text)
        assert result is not None, text
        assert result.kind is kind, text
        assert getattr(result, field), text


def test_a_weather_trend_after_a_colour_state() -> None:
    first, _, used = tail("BLU TEMPO 5000 -RA NOSIG")
    assert first.color_state == ColorStateGroup(ColorState(ColorCode.BLU))
    assert used == 1
    second, _, used = run(lambda cur: _skip_then_tail(cur), "BLU TEMPO 5000 -RA NOSIG")
    assert second.trend.kind is TrendKind.TEMPO
    assert second.trend.elements.weather == (WeatherGroup(Intensity.LIGHT, None, (Phenomenon.RA,)),)
    assert used == 4


def _skip_then_tail(cur: Cursor) -> Any:
    cur.take(SemanticKind.COLOR_STATE)
    return parse_tail_group(cur, Flavor.ICAO, OBSERVED)


def test_runway_state_is_not_looked_for_in_us_reports() -> None:
    assert tail("88290192", Flavor.US)[0] is None
    assert tail("R24L/290255", Flavor.US)[0] is None
    assert tail("88290192", Flavor.MIXED)[0] is not None


def test_a_trend_body_stops_at_the_next_tail_group() -> None:
    result, _, used = tail("TEMPO 3000 RESHRA R24/290255 NOSIG")
    assert result.trend.elements.visibility is not None
    assert used == 2


@pytest.mark.parametrize("text", ["9999", "FOO", "BKN010", "A3001", "RMK", "R35L/P6000FT", "AO2", ""])
def test_dispatcher_rejects(text: str) -> None:
    result, _, used = tail(text)
    assert result is None
    assert used == 0
