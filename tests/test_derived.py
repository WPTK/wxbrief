"""Derived values: ceiling, flags, header condition, relative humidity; plus flavor detection."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from wxbrief.decode.derived import DAY_END_HOUR, DAY_START_HOUR, refine_clear, relative_humidity
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


def test_clear_is_refined_by_local_hour() -> None:
    assert refine_clear(Condition.CLEAR, DAY_START_HOUR) is Condition.CLEAR_DAY
    assert refine_clear(Condition.CLEAR, DAY_END_HOUR - 1) is Condition.CLEAR_DAY
    assert refine_clear(Condition.CLEAR, DAY_END_HOUR) is Condition.CLEAR_NIGHT
    assert refine_clear(Condition.CLEAR, 3) is Condition.CLEAR_NIGHT
    assert refine_clear(Condition.RAIN, 12) is Condition.RAIN
    assert refine_clear(None, 12) is None


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


def test_the_station_prefix_is_not_a_signal() -> None:
    # A "K" station reporting in metres and QNH is still ICAO flavor; an "EG" station in SM and inHg is US flavor.
    assert detect_flavor(tokenize("KXYZ 131453Z 24010KT 9999 Q1013")).flavor is Flavor.ICAO
    assert detect_flavor(tokenize("EGXX 131453Z 24010KT 10SM A3001")).flavor is Flavor.US
