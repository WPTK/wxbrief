"""The groups that only occur in TAFs: windows, change keywords, wind shear, temperatures, QNH, icing, turbulence, notes."""

from __future__ import annotations

import pytest

from wxbrief.decode.groups.tafgroups import (
    DayHour,
    DayHourMinute,
    fm_of,
    legacy_fm_of,
    legacy_valid_of,
    legacy_window_of,
    parse_icing,
    parse_note,
    parse_qnh,
    parse_taf_temperature,
    parse_turbulence,
    parse_wind_shear_layer,
    probability_of,
    starts_change_group,
    window_of,
)
from wxbrief.decode.model import IcingIntensity, SemanticKind, TemperatureExtreme, TurbulenceIntensity
from wxbrief.decode.tokens import Cursor, tokenize
from wxbrief.decode.units import (
    Distance,
    DistanceUnit,
    Pressure,
    PressureUnit,
    Speed,
    SpeedUnit,
    Temperature,
    TemperatureUnit,
)


def cursor(text: str) -> Cursor:
    return Cursor(tokenize(text))


# --- times -----------------------------------------------------------------------------------------------------


def test_window_is_two_day_hour_pairs() -> None:
    assert window_of("3106/3108") == (DayHour(31, 6), DayHour(31, 8))
    assert window_of("3023/0106") == (DayHour(30, 23), DayHour(1, 6))


@pytest.mark.parametrize("text", ["31063108", "3106/310", "TEMPO", "310608/3108", ""])
def test_window_rejects_other_text(text: str) -> None:
    assert window_of(text) is None


def test_legacy_forms() -> None:
    assert legacy_valid_of("131212") == (13, 12, 12)
    assert legacy_valid_of("13121") is None
    assert legacy_window_of("1315") == (13, 15)
    assert legacy_window_of("131") is None
    assert legacy_fm_of("FM1800") == (18, 0)
    assert legacy_fm_of("FM180030") is None  # that is the six-digit form


def test_fm_carries_day_hour_and_minute() -> None:
    assert fm_of("FM311500") == DayHourMinute(31, 15, 0)
    assert fm_of("FM010030") == DayHourMinute(1, 0, 30)
    assert fm_of("FM1500") is None


def test_probability() -> None:
    assert probability_of("PROB30") == 30
    assert probability_of("PROB40") == 40
    assert probability_of("PROB3") is None
    assert probability_of("PROB") is None


@pytest.mark.parametrize("text", ["TEMPO", "BECMG", "INTER", "FM101200", "FM1200", "PROB30", "PROB40"])
def test_these_start_a_change_group(text: str) -> None:
    assert starts_change_group(text)


@pytest.mark.parametrize("text", ["RMK", "3106/3108", "TX21/3115Z", "NSW", "PROB", "FM", "9999"])
def test_these_do_not(text: str) -> None:
    assert not starts_change_group(text)


# --- wind shear -------------------------------------------------------------------------------------------------


def test_wind_shear_layer() -> None:
    shear = parse_wind_shear_layer(cursor("WS020/30035KT"))
    assert shear is not None
    assert shear.height == Distance(2000, DistanceUnit.FT)
    assert shear.direction == 300
    assert shear.speed == Speed(35, SpeedUnit.KT)
    assert shear.gust is None


def test_wind_shear_layer_variable_with_gust_and_other_units() -> None:
    shear = parse_wind_shear_layer(cursor("WS005/VRB20G30KT"))
    assert shear is not None
    assert shear.direction is None
    assert shear.gust == Speed(30, SpeedUnit.KT)
    metric = parse_wind_shear_layer(cursor("WS010/25012MPS"))
    assert metric is not None and metric.speed == Speed(12, SpeedUnit.MPS)


def test_wind_shear_declines_and_consumes_nothing() -> None:
    cur = cursor("WS020 WS/30035KT")
    assert parse_wind_shear_layer(cur) is None
    assert cur.pos == 0


def test_wind_shear_consumes_exactly_one_token() -> None:
    cur = cursor("WS020/30035KT 9999")
    assert parse_wind_shear_layer(cur) is not None
    assert cur.pos == 1


# --- temperature extremes ---------------------------------------------------------------------------------------


def test_temperature_extremes() -> None:
    top = parse_taf_temperature(cursor("TX19/3114Z"))
    assert top is not None
    assert (top.kind, top.temperature, top.day, top.hour) == (
        TemperatureExtreme.MAX,
        Temperature(19, TemperatureUnit.C),
        31,
        14,
    )
    bottom = parse_taf_temperature(cursor("TNM02/0105Z"))
    assert bottom is not None
    assert (bottom.kind, bottom.temperature, bottom.day, bottom.hour) == (
        TemperatureExtreme.MIN,
        Temperature(-2, TemperatureUnit.C),
        1,
        5,
    )


def test_temperature_without_the_z_is_accepted() -> None:
    group = parse_taf_temperature(cursor("TN05/3114"))
    assert group is not None and group.temperature.value == 5


@pytest.mark.parametrize("text", ["TX99/", "TZ05/3114Z", "TX5/3114Z", "TX05/31Z"])
def test_temperature_declines(text: str) -> None:
    assert parse_taf_temperature(cursor(text)) is None


# --- QNH ----------------------------------------------------------------------------------------------------------


def test_qnh_in_inches_and_hectopascals() -> None:
    assert parse_qnh(cursor("QNH2992INS")) == Pressure(29.92, PressureUnit.INHG)
    assert parse_qnh(cursor("QNH1013")) == Pressure(1013.0, PressureUnit.HPA)


def test_qnh_that_is_clearly_inches_is_read_as_inches_without_ins() -> None:
    assert parse_qnh(cursor("QNH3009")) == Pressure(30.09, PressureUnit.INHG)


def test_qnh_declines_other_text() -> None:
    assert parse_qnh(cursor("Q1013")) is None
    assert parse_qnh(cursor("QNH")) is None


# --- icing, turbulence ----------------------------------------------------------------------------------------------


def test_icing_group() -> None:
    icing = parse_icing(cursor("620604"))
    assert icing is not None
    assert icing.intensity is IcingIntensity.LIGHT_IN_CLOUD
    assert icing.base == Distance(6000, DistanceUnit.FT)
    assert icing.thickness == Distance(4000, DistanceUnit.FT)


def test_icing_thickness_zero_is_unspecified() -> None:
    icing = parse_icing(cursor("610000"))
    assert icing is not None
    assert icing.intensity is IcingIntensity.LIGHT
    assert icing.base == Distance(0, DistanceUnit.FT)
    assert icing.thickness is None


def test_icing_severe() -> None:
    icing = parse_icing(cursor("690604"))
    assert icing is not None and icing.intensity is IcingIntensity.SEVERE_IN_PRECIPITATION


def test_turbulence_group() -> None:
    turbulence = parse_turbulence(cursor("520009"))
    assert turbulence is not None
    assert turbulence.intensity is TurbulenceIntensity.MODERATE_CLEAR_OCCASIONAL
    assert turbulence.base == Distance(0, DistanceUnit.FT)
    assert turbulence.thickness == Distance(9000, DistanceUnit.FT)
    other = parse_turbulence(cursor("510708"))
    assert other is not None
    assert (other.intensity, other.base, other.thickness) == (
        TurbulenceIntensity.LIGHT,
        Distance(7000, DistanceUnit.FT),
        Distance(8000, DistanceUnit.FT),
    )


def test_icing_and_turbulence_do_not_read_each_other() -> None:
    assert parse_icing(cursor("520604")) is None
    assert parse_turbulence(cursor("620604")) is None
    assert parse_icing(cursor("62060")) is None


# --- military notes -------------------------------------------------------------------------------------------------


def test_note_takes_its_words_and_times_and_stops_at_the_next_group() -> None:
    cur = cursor("LAST NO AMDS AFT 3023 NEXT 0207 TX21/3122Z")
    assert parse_note(cur) == "LAST NO AMDS AFT 3023 NEXT 0207"
    following = cur.peek()
    assert following is not None and following.text == "TX21/3122Z"
    assert all(cur.kind_at(i) is SemanticKind.REMARK for i in range(7))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("AMD NOT SKED", "AMD NOT SKED"),
        ("FS30217", "FS30217"),
        ("AUTOMATED SENSOR METWATCH 3106 TIL 3113", "AUTOMATED SENSOR METWATCH 3106 TIL 3113"),
    ],
)
def test_other_notes(text: str, expected: str) -> None:
    assert parse_note(cursor(text)) == expected


def test_a_lone_amd_is_not_a_note() -> None:
    cur = cursor("AMD 9999")
    assert parse_note(cur) is None
    assert cur.pos == 0
