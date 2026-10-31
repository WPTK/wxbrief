"""Derived values: ceiling, flags, header condition, relative humidity; plus flavor detection."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from wxbrief.decode.derived import refine_clear, relative_humidity
from wxbrief.decode.detect import detect_flavor
from wxbrief.decode.metar import parse_metar
from wxbrief.decode.model import Condition, Flag, Flavor
from wxbrief.decode.tokens import tokenize
from wxbrief.decode.units import Temperature, TemperatureUnit

REF = datetime(2026, 10, 13, 15, 0, tzinfo=UTC)


def decode(body: str) -> object:
    return parse_metar(f"METAR KXYZ 131453Z {body}", REF)


def flags_of(body: str) -> set[Flag]:
    return set(parse_metar(f"METAR KXYZ 131453Z {body}", REF).flags)


def condition_of(body: str) -> Condition | None:
    return parse_metar(f"METAR KXYZ 131453Z {body}", REF).condition


# --- flags ----------------------------------------------------------------------------------------------------


def test_no_flags_on_a_quiet_report() -> None:
    assert flags_of("06007KT 10SM FEW040 09/08 A3001") == set()


def test_cumulonimbus_and_towering_cumulus() -> None:
    assert flags_of("06007KT 10SM SCT040CB 09/08 A3001") == {Flag.CB}
    assert flags_of("06007KT 10SM SCT040TCU 09/08 A3001") == {Flag.TCU}
    assert flags_of("06007KT 10SM SCT040CB BKN050TCU 09/08 A3001") == {Flag.CB, Flag.TCU}


def test_low_ceiling_and_visibility() -> None:
    assert flags_of("06007KT 10SM BKN009 09/08 A3001") == {Flag.LOW_CEILING}
    assert flags_of("06007KT 10SM BKN010 09/08 A3001") == set()
    assert flags_of("06007KT 2SM BR 09/08 A3001") == {Flag.LOW_VISIBILITY}
    assert flags_of("06007KT 3SM BR 09/08 A3001") == set()
    assert flags_of("06007KT 2500 BR 09/08 Q1013") == {Flag.LOW_VISIBILITY}


def test_gusts() -> None:
    assert flags_of("06007G15KT 10SM CLR 09/08 A3001") == {Flag.GUSTS}


def test_freezing_precipitation_but_not_freezing_fog() -> None:
    assert Flag.FREEZING_PRECIP in flags_of("06007KT 3SM FZRA OVC010 M02/M03 A3001")
    assert Flag.FREEZING_PRECIP in flags_of("06007KT 3SM -FZDZ OVC010 M02/M03 A3001")
    assert Flag.FREEZING_PRECIP not in flags_of("06007KT 1/2SM FZFG VV002 M02/M03 A3001")


def test_thunderstorm_including_vicinity() -> None:
    assert Flag.THUNDERSTORM in flags_of("06007KT 3SM +TSRA BKN015CB 22/20 A3001")
    assert Flag.THUNDERSTORM in flags_of("06007KT 10SM VCTS SCT040CB 22/20 A3001")
    assert Flag.THUNDERSTORM not in flags_of("06007KT 3SM -SHRA BKN015 22/20 A3001")


def test_report_status_flags() -> None:
    assert parse_metar("METAR KXYZ 131453Z COR 06007KT 10SM CLR 09/08 A3001", REF).flags == (Flag.CORRECTED,)
    assert parse_metar("METAR KXYZ 131453Z AUTO 06007KT 10SM CLR 09/08 A3001", REF).flags == (Flag.AUTOMATED,)
    assert parse_metar("SPECI KXYZ 131453Z 06007KT 10SM CLR 09/08 A3001", REF).flags == (Flag.SPECIAL_REPORT,)
    assert parse_metar("METAR KXYZ 131453Z CCA 06007KT 10SM CLR 09/08 A3001", REF).flags == (Flag.CORRECTED,)


def test_flags_follow_the_enum_order() -> None:
    flags = parse_metar("SPECI KXYZ 131453Z AUTO 06007G15KT 1SM +TSRA BKN005CB 22/20 A3001", REF).flags
    assert list(flags) == sorted(flags, key=list(Flag).index)
    assert {Flag.CB, Flag.LOW_CEILING, Flag.LOW_VISIBILITY, Flag.GUSTS, Flag.THUNDERSTORM, Flag.AUTOMATED} <= set(flags)


def icao_flags(tail: str, body: str = "24010KT 9999 FEW040 12/08 Q1013") -> set[Flag]:
    return set(parse_metar(f"METAR EGLL 131453Z {body} {tail}", REF).flags)


def test_wind_shear_flag() -> None:
    assert Flag.WIND_SHEAR in icao_flags("WS R24L")
    assert Flag.WIND_SHEAR in icao_flags("WS ALL RWY NOSIG")
    assert Flag.WIND_SHEAR not in icao_flags("NOSIG")


@pytest.mark.parametrize(
    ("tail", "expected"),
    [
        ("BLU", False),
        ("WHT", False),
        ("GRN", False),
        ("YLO", True),
        ("YLO1", True),
        ("YLO2", True),
        ("AMB", True),
        ("RED", True),
        ("BLACKRED", True),
        ("BLACK", False),
        ("BLU TEMPO RED", False),  # only the current state counts
        ("RED BECMG BLU", True),
        ("///", False),
        ("NOSIG", False),
    ],
)
def test_color_below_green_flag(tail: str, expected: bool) -> None:
    assert (Flag.COLOR_BELOW_GRN in icao_flags(tail)) is expected


def test_color_below_green_flag_from_the_remarks() -> None:
    assert Flag.COLOR_BELOW_GRN in icao_flags("NOSIG RMK AMB TEMPO RED")
    assert Flag.COLOR_BELOW_GRN not in icao_flags("NOSIG RMK BLU BLU")


def test_rapid_pressure_change_flag() -> None:
    assert Flag.RAPID_PRESSURE_CHANGE in icao_flags("RMK PRESRR")
    assert Flag.RAPID_PRESSURE_CHANGE in icao_flags("RMK PRESFR")
    assert Flag.RAPID_PRESSURE_CHANGE not in icao_flags("RMK SLP135")


def test_maintenance_flag() -> None:
    assert Flag.MAINTENANCE in icao_flags("RMK AO2 SLP135 $")
    assert Flag.MAINTENANCE not in icao_flags("RMK AO2 SLP135")


@pytest.mark.parametrize(
    ("body", "tail", "expected"),
    [
        ("24010KT 9999 VA FEW040 12/08 Q1013", "", True),
        ("24010KT 9999 VCVA FEW040 12/08 Q1013", "", True),
        ("24010KT 9999 FEW040 12/08 Q1013", "REVA", True),
        ("24010KT 9999 FEW040 12/08 Q1013", "TEMPO 3000 VA", True),
        ("24010KT 9999 FEW040 12/08 Q1013", "RERA", False),
        ("24010KT 9999 -RA FEW040 12/08 Q1013", "", False),
    ],
)
def test_volcanic_ash_flag(body: str, tail: str, expected: bool) -> None:
    assert (Flag.VOLCANIC_ASH in icao_flags(tail, body)) is expected


@pytest.mark.parametrize(
    ("body", "tail", "expected"),
    [
        ("24010KT 9999 FEW040 12/08 Q1013", "RMK RVRNO", True),
        ("24010KT 9999 FEW040 12/08 Q1013", "RMK PWINO", True),
        ("24010KT 9999 FEW040 12/08 Q1013", "RMK SLPNO", True),
        ("24010KT 9999 // FEW040 12/08 Q1013", "", True),
        ("24010KT //// FEW040 12/08 Q1013", "", True),
        ("24010KT 9999 //////  12/08 Q1013", "", True),
        ("24010KT 9999 BKN/// 12/08 Q1013", "", True),
        ("24010KT 0300 FG VV/// 12/08 Q1013", "", True),
        ("24010KT 9999 FEW040 12/08 Q1013", "RMK SLP135", False),
        ("24010KT 9999 FEW040 12/08 Q1013", "", False),
    ],
)
def test_missing_data_flag(body: str, tail: str, expected: bool) -> None:
    assert (Flag.MISSING_DATA in icao_flags(tail, body)) is expected


def test_flag_order_follows_the_enum_with_the_new_flags() -> None:
    flags = parse_metar("METAR EGLL 131453Z AUTO 24010G20KT 0300 FG VV002 12/08 Q1013 WS R24L AMB RMK PRESRR $ RVRNO", REF).flags
    assert list(flags) == [flag for flag in Flag if flag in flags]
    assert {Flag.WIND_SHEAR, Flag.COLOR_BELOW_GRN, Flag.RAPID_PRESSURE_CHANGE, Flag.MAINTENANCE, Flag.MISSING_DATA} <= set(flags)


# --- ceiling ---------------------------------------------------------------------------------------------------


def test_ceiling_value() -> None:
    m = parse_metar("METAR KXYZ 131453Z 06007KT 10SM FEW010 BKN030 OVC050 09/08 A3001", REF)
    assert m.ceiling is not None
    assert m.ceiling.feet == 3000
    assert parse_metar("METAR KXYZ 131453Z 06007KT 10SM FEW010 09/08 A3001", REF).ceiling is None


# --- condition -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("06007KT 3SM +TSRA OVC010 22/20 A3001", Condition.THUNDERSTORM),
        ("06007KT 10SM VCTS SCT040 22/20 A3001", Condition.THUNDERSTORM),
        ("06007KT 3SM -SN OVC010 M02/M03 A3001", Condition.SNOW),
        ("06007KT 3SM FZRA OVC010 M02/M03 A3001", Condition.SNOW),
        ("06007KT 3SM BLSN OVC010 M02/M03 A3001", Condition.SNOW),
        ("06007KT 3SM GR OVC010 22/20 A3001", Condition.SNOW),
        ("06007KT 3SM -RA OVC010 22/20 A3001", Condition.RAIN),
        ("06007KT 3SM -DZ OVC010 22/20 A3001", Condition.RAIN),
        ("06007KT 3SM -SHRA BKN010 22/20 A3001", Condition.RAIN),
        ("06007KT 3SM BR OVC010 22/20 A3001", Condition.OBSCURATION),
        ("06007KT 1/2SM FG VV002 22/20 A3001", Condition.OBSCURATION),
        ("06007KT 3SM HZ SCT040 22/20 A3001", Condition.OBSCURATION),
        ("06007KT 10SM OVC010 22/20 A3001", Condition.OVERCAST),
        ("06007KT 10SM VV002 22/20 A3001", Condition.OVERCAST),
        ("06007KT 10SM BKN010 22/20 A3001", Condition.BROKEN),
        ("06007KT 10SM BKN010 OVC020 22/20 A3001", Condition.OVERCAST),
        ("06007KT 10SM FEW010 22/20 A3001", Condition.PARTLY_CLOUDY),
        ("06007KT 10SM SCT010 22/20 A3001", Condition.PARTLY_CLOUDY),
        ("06007KT 10SM CLR 22/20 A3001", Condition.CLEAR),
        ("06007KT 10SM SKC 22/20 A3001", Condition.CLEAR),
        ("06007KT 10SM NSC 22/20 A3001", Condition.CLEAR),
        ("06007KT CAVOK 22/20 Q1013", Condition.CLEAR),
    ],
)
def test_condition_priority(body: str, expected: Condition) -> None:
    assert condition_of(body) is expected


def test_vicinity_weather_other_than_thunderstorms_does_not_override_the_sky() -> None:
    assert condition_of("06007KT 9999 VCFG NSC 08/07 Q1030") is Condition.CLEAR
    assert condition_of("06007KT 9999 VCSH BKN040 08/07 Q1030") is Condition.BROKEN


def test_condition_is_none_without_weather_or_sky() -> None:
    assert condition_of("06007KT A3001") is None


def test_clear_is_refined_by_daylight() -> None:
    assert refine_clear(Condition.CLEAR, True) is Condition.CLEAR_DAY
    assert refine_clear(Condition.CLEAR, False) is Condition.CLEAR_NIGHT
    assert refine_clear(Condition.RAIN, True) is Condition.RAIN
    assert refine_clear(None, True) is None


# --- relative humidity -----------------------------------------------------------------------------------------


def test_relative_humidity() -> None:
    assert relative_humidity(Temperature(10), Temperature(10)) == 100.0
    assert relative_humidity(Temperature(20), Temperature(10)) == pytest.approx(52.5, abs=0.5)
    assert relative_humidity(Temperature(68, TemperatureUnit.F), Temperature(50, TemperatureUnit.F)) == pytest.approx(
        52.5, abs=0.5
    )
    assert relative_humidity(Temperature(5), Temperature(8)) == 100.0  # capped
    assert relative_humidity(None, Temperature(5)) is None
    assert relative_humidity(Temperature(5), None) is None


def test_relative_humidity_on_a_report() -> None:
    m = parse_metar("METAR KDEN 131453Z 06007KT 3/4SM BR OVC003 09/08 A3001", REF)
    assert m.relative_humidity == pytest.approx(93.5, abs=0.5)


# --- flavor detection ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "flavor", "military"),
    [
        ("KDEN 131453Z 06007KT 10SM CLR 09/08 A3001 RMK AO2", Flavor.US, False),
        ("EGLL 311050Z 24010KT CAVOK 12/08 Q1013", Flavor.ICAO, False),
        ("UUEE 310730Z 08003MPS 9999 M02/M04 Q1024", Flavor.ICAO, False),
        ("EGVN 311550Z 29006KT 9999 10/04 Q1021 BLU", Flavor.ICAO, True),
        ("MMMX 131453Z 32005KT 6SM SKC 17/10 A3012 NOSIG", Flavor.MIXED, False),
        ("KDEN 131453Z", Flavor.UNKNOWN, False),
        ("R35L/P6000FT", Flavor.US, False),
        ("R12/1000U", Flavor.ICAO, False),
    ],
)
def test_detect_flavor(text: str, flavor: Flavor, military: bool) -> None:
    detection = detect_flavor(tokenize(text))
    assert (detection.flavor, detection.military) == (flavor, military)


@pytest.mark.parametrize(
    ("text", "military"),
    [
        ("EGVN 311550Z 29006KT 9999 10/04 Q1021 BLU+", True),
        ("EGVN 311550Z 29006KT 9999 10/04 Q1021 BLACKRED", True),
        ("EGVN 311550Z 29006KT 9999 10/04 Q1021 BLACK", False),  # closed for other reasons: no weather state
        ("ETHB 311550Z AUTO 29006KT 9999 10/04 Q1021 ///", False),  # a colour that was not reported
        ("EGVN 311550Z 29006KT 9999 10/04 Q1021 NOSIG", False),
    ],
)
def test_a_colour_state_marks_a_military_report(text: str, military: bool) -> None:
    assert detect_flavor(tokenize(text)).military is military


def test_the_station_prefix_is_not_a_signal() -> None:
    # A "K" station reporting in metres and QNH is still ICAO flavor; an "EG" station in SM and inHg is US flavor.
    assert detect_flavor(tokenize("KXYZ 131453Z 24010KT 9999 Q1013")).flavor is Flavor.ICAO
    assert detect_flavor(tokenize("EGXX 131453Z 24010KT 10SM A3001")).flavor is Flavor.US


def test_a_metar_two_weeks_before_the_reference_is_dated_in_the_same_month() -> None:
    m = parse_metar("METAR KDEN 141153Z 06007KT 10SM CLR 09/08 A3001", datetime(2026, 10, 31, 12, 0, tzinfo=UTC))
    assert m.observed == datetime(2026, 10, 14, 11, 53, tzinfo=UTC)
