from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from wxbrief.solar import HORIZON_DEG, is_daylight, solar_elevation

TOLERANCE_MIN = 6  # sunrise/sunset tables agree with the NOAA formula to a few minutes


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def test_noon_and_midnight_elevation_at_the_equinox() -> None:
    assert abs(solar_elevation(0, 0, at("2026-03-20T12:00:00")) - 90) < 3  # the equinox falls at 14:46Z
    assert solar_elevation(0, 0, at("2026-03-20T00:00:00")) < -85


def test_denver_sunrise_and_sunset_on_the_solstice() -> None:
    # 2026-06-21, Denver (39.74, -104.99): sunrise 05:32 MDT = 11:32Z, sunset 20:31 MDT = 02:31Z next day.
    lat, lon = 39.74, -104.99
    for when in ("2026-06-21T11:32:00", "2026-06-22T02:31:00"):
        assert abs(solar_elevation(lat, lon, at(when)) - HORIZON_DEG) < 1.0, when
    assert is_daylight(lat, lon, at("2026-06-21T11:32:00") - timedelta(minutes=TOLERANCE_MIN)) is False
    assert is_daylight(lat, lon, at("2026-06-21T11:32:00") + timedelta(minutes=TOLERANCE_MIN)) is True
    assert is_daylight(lat, lon, at("2026-06-22T02:31:00") - timedelta(minutes=TOLERANCE_MIN)) is True
    assert is_daylight(lat, lon, at("2026-06-22T02:31:00") + timedelta(minutes=TOLERANCE_MIN)) is False


def test_old_fixed_hours_were_wrong_in_summer_evening_and_winter() -> None:
    # 20:30 local in Denver in June is still light; 16:50 local in Denver in December is already dark.
    assert is_daylight(39.74, -104.99, at("2026-06-22T02:30:00")) is True  # 20:30 MDT
    assert is_daylight(39.74, -104.99, at("2026-12-21T23:50:00")) is False  # 16:50 MST


def test_polar_day_and_night() -> None:
    # Longyearbyen (78.25, 15.47): midnight sun in June, polar night in December.
    assert is_daylight(78.25, 15.47, at("2026-06-21T00:00:00")) is True
    assert is_daylight(78.25, 15.47, at("2026-12-21T12:00:00")) is False
    # McMurdo (-77.85, 166.67): the reverse.
    assert is_daylight(-77.85, 166.67, at("2026-12-21T00:00:00")) is True
    assert is_daylight(-77.85, 166.67, at("2026-06-21T12:00:00")) is False


def test_zone_aware_times_are_converted() -> None:
    est = timezone(timedelta(hours=-5))
    noon_utc = at("2026-03-20T12:00:00")
    assert abs(solar_elevation(0, 0, noon_utc) - solar_elevation(0, 0, noon_utc.astimezone(est))) < 1e-9


def test_unknown_time_is_unknown() -> None:
    assert is_daylight(39.74, -104.99, None) is None


def test_naive_times_are_taken_as_utc() -> None:
    naive = datetime(2026, 6, 21, 12, 0)
    assert solar_elevation(39.74, -104.99, naive) == solar_elevation(39.74, -104.99, naive.replace(tzinfo=UTC))


def test_tui_copy_path_uses_the_station_position() -> None:
    # CopyActions._discord with a stub screen: 03:00Z at Denver is dark, and swapped lat/lon would say day.
    from types import SimpleNamespace

    from wxbrief.data.stations import bundled
    from wxbrief.decode.metar import parse_metar
    from wxbrief.decode.units import UnitsMode
    from wxbrief.i18n import Translator
    from wxbrief.state import StationReports
    from wxbrief.ui.copying import CopyActions

    observed = datetime(2026, 10, 31, 3, 0, tzinfo=UTC)
    report = parse_metar("METAR KDEN 310300Z 00000KT 10SM CLR 10/00 A3001")
    awc = SimpleNamespace(observed=observed)
    entry = StationReports(icao="KDEN", awc_metar=awc)  # type: ignore[arg-type]
    ctx = SimpleNamespace(station=bundled().get, translator=Translator.load("en"), units=UnitsMode.US)
    screen = SimpleNamespace(app=SimpleNamespace(ctx=ctx))
    text = CopyActions._discord(screen, report, entry)  # type: ignore[arg-type]
    assert "\U0001f319 KDEN" in text
