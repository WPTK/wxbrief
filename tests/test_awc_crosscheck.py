"""Cross-check of the decoded remarks and weather against AWC's own structured fields on every saved report.

AWC parses the same report text into JSON (``slp``, ``presTend``, ``maxT``, ...). Our hand-written parser must agree
with it wherever the field exists. A disagreement is either a decoder bug or an AWC quirk; the quirks that were
investigated are listed in ``EXCEPTIONS`` with the reason, keyed by field and raw report. A new disagreement fails
the test: fix the decoder, or investigate and add the reason here.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

import pytest
from corpus import awc_rows

from wxbrief.decode.metar import parse_metar
from wxbrief.decode.model import (
    DailyPrecipitation,
    DailyTemperatureExtremes,
    HourlyPrecipitation,
    MaxTemperature6Hour,
    Metar,
    MinTemperature6Hour,
    PeriodPrecipitation,
    PreciseTemperature,
    PressureTendency,
    SeaLevelPressure,
    SemanticKind,
    SnowDepth,
    TendencyDirection,
)

TOLERANCE = 0.051  # AWC rounds to a tenth
TRACE_INCHES = 0.005  # AWC stores a trace (P0000, 60000) as half a hundredth


def decode(row: dict[str, Any]) -> Metar:
    return parse_metar(row["rawOb"], datetime.fromisoformat(row["reportTime"].replace("Z", "+00:00")))


NORWAY_WIND = "Norwegian `RMK WIND <height>FT <wind>` remarks: AWC fills maxT/minT with values that are not in the text."
ZERO_TENDENCY = "A pressure tendency of 0.0 hPa: AWC leaves presTend empty, we keep the group (character and zero)."
RECENT_MERGED = "AWC adds the recent-weather group RESHRA to wxString as SHRA; we keep recent weather separate."

EXCEPTIONS: dict[tuple[str, str], str] = {
    ("maxT", "METAR ENVA 310650Z 11005KT 9999 FEW004 04/04 Q1027 NOSIG RMK WIND 670FT 11007KT"): NORWAY_WIND,
    ("minT", "METAR ENEV 310750Z 19013KT 9999 BKN039 12/06 Q1018 RMK WIND 1400FT 21024G35KT"): NORWAY_WIND,
    ("minT", "METAR ENEV 310720Z 19013KT 9999 BKN037 11/06 Q1018 RMK WIND 1400FT 20021KT"): NORWAY_WIND,
    (
        "minT",
        "METAR ENTC 310820Z 19017KT 9999 -RA FEW031 BKN039 09/04 Q1015 TEMPO 21022G32KT RADZ BKN014 RMK WIND 2600FT 19040KT",
    ): NORWAY_WIND,
    (
        "presTend",
        "METAR KCVG 310552Z 08008KT 10SM SCT250 13/03 A3034 RMK AO2 SLP270 T01330033 10178 20133 51000 $",
    ): ZERO_TENDENCY,
    (
        "wxString",
        "METAR YSCB 310800Z AUTO 32009KT 9999 VCTS -SHRA FEW026 SCT061 17/15 Q1011 RETS RESHRA",
    ): RECENT_MERGED,
    (
        "wxString",
        "SPECI YSCB 310759Z AUTO 33009KT 9999 VCTS -SHRA FEW026 SCT061 18/15 Q1011 RETS RESHRA",
    ): RECENT_MERGED,
}


def near(ours: float | None, theirs: float | None, tolerance: float = TOLERANCE) -> bool:
    if ours is None or theirs is None:
        return ours is theirs
    return abs(ours - theirs) <= tolerance


def slp(metar: Metar, row: dict[str, Any]) -> tuple[float | None, float | None]:
    found = metar.remarks_of(SeaLevelPressure)
    ours = found[0].pressure.hpa if found and found[0].pressure is not None else None
    return ours, row.get("slp")


def tendency(metar: Metar, row: dict[str, Any]) -> tuple[float | None, float | None]:
    found = metar.remarks_of(PressureTendency)
    if not found:
        return None, row.get("presTend")
    sign = {TendencyDirection.HIGHER: 1, TendencyDirection.LOWER: -1, TendencyDirection.SAME: 0}[found[0].direction]
    return sign * found[0].change_hpa, row.get("presTend")


def six_hour_max(metar: Metar, row: dict[str, Any]) -> tuple[float | None, float | None]:
    found = metar.remarks_of(MaxTemperature6Hour)
    ours = found[0].temperature.value if found and found[0].temperature is not None else None
    return ours, row.get("maxT")


def six_hour_min(metar: Metar, row: dict[str, Any]) -> tuple[float | None, float | None]:
    found = metar.remarks_of(MinTemperature6Hour)
    ours = found[0].temperature.value if found and found[0].temperature is not None else None
    return ours, row.get("minT")


def day_max(metar: Metar, row: dict[str, Any]) -> tuple[float | None, float | None]:
    found = metar.remarks_of(DailyTemperatureExtremes)
    ours = found[0].maximum.value if found and found[0].maximum is not None else None
    return ours, row.get("maxT24")


def day_min(metar: Metar, row: dict[str, Any]) -> tuple[float | None, float | None]:
    found = metar.remarks_of(DailyTemperatureExtremes)
    ours = found[0].minimum.value if found and found[0].minimum is not None else None
    return ours, row.get("minT24")


def hourly_precipitation(metar: Metar, row: dict[str, Any]) -> tuple[float | None, float | None]:
    found = metar.remarks_of(HourlyPrecipitation)
    if not found or found[0].inches is None:
        return None, row.get("precip")
    return (TRACE_INCHES if found[0].trace else found[0].inches), row.get("precip")


def six_hour_precipitation(metar: Metar, row: dict[str, Any]) -> tuple[float | None, float | None]:
    found = [item for item in metar.remarks_of(PeriodPrecipitation) if item.hours == 6]
    if not found or found[0].inches is None:
        return None, row.get("pcp6hr")
    return (TRACE_INCHES if found[0].trace else found[0].inches), row.get("pcp6hr")


def three_hour_precipitation(metar: Metar, row: dict[str, Any]) -> tuple[float | None, float | None]:
    found = [item for item in metar.remarks_of(PeriodPrecipitation) if item.hours == 3]
    if not found or found[0].inches is None:
        return None, row.get("pcp3hr")
    return (TRACE_INCHES if found[0].trace else found[0].inches), row.get("pcp3hr")


def daily_precipitation(metar: Metar, row: dict[str, Any]) -> tuple[float | None, float | None]:
    found = metar.remarks_of(DailyPrecipitation)
    if not found or found[0].inches is None:
        return None, row.get("pcp24hr")
    return (TRACE_INCHES if found[0].trace else found[0].inches), row.get("pcp24hr")


def snow_depth(metar: Metar, row: dict[str, Any]) -> tuple[float | None, float | None]:
    found = metar.remarks_of(SnowDepth)
    return (found[0].inches if found else None), row.get("snow")


def precise_temperature(metar: Metar, row: dict[str, Any]) -> tuple[float | None, float | None]:
    """The T-group is AWC's ``temp`` whenever there is one."""
    found = metar.remarks_of(PreciseTemperature)
    return (found[0].temperature.value if found else row.get("temp")), row.get("temp")


def precise_dewpoint(metar: Metar, row: dict[str, Any]) -> tuple[float | None, float | None]:
    found = metar.remarks_of(PreciseTemperature)
    if found and found[0].dewpoint is not None:
        return found[0].dewpoint.value, row.get("dewp")
    return row.get("dewp"), row.get("dewp")


FIELDS: dict[str, Callable[[Metar, dict[str, Any]], tuple[float | None, float | None]]] = {
    "slp": slp,
    "presTend": tendency,
    "maxT": six_hour_max,
    "minT": six_hour_min,
    "maxT24": day_max,
    "minT24": day_min,
    "precip": hourly_precipitation,
    "pcp6hr": six_hour_precipitation,
    "pcp3hr": three_hour_precipitation,
    "pcp24hr": daily_precipitation,
    "snow": snow_depth,
    "temp": precise_temperature,
    "dewp": precise_dewpoint,
}

# Fields AWC lists but the saved reports never populate (no 15Z/21Z, 12Z or snow-reporting station was in the
# batches); the checks still run and pass vacuously, and the decoders are covered by tests/test_remarks.py.
SPARSE = {"pcp3hr", "pcp24hr", "snow"}


def mismatches(field: str) -> list[str]:
    compare = FIELDS[field]
    found: list[str] = []
    for row in awc_rows():
        if (field, row["rawOb"]) in EXCEPTIONS:
            continue
        ours, theirs = compare(decode(row), row)
        tolerance = 0.0051 if field in ("precip", "pcp6hr", "pcp3hr", "pcp24hr") else TOLERANCE
        if not near(ours, theirs, tolerance):
            found.append(f"{field}: ours={ours} awc={theirs} :: {row['rawOb']}")
    return found


@pytest.mark.parametrize("field", sorted(FIELDS))
def test_decoded_field_matches_awc(field: str) -> None:
    assert not mismatches(field)


@pytest.mark.parametrize("field", sorted(set(FIELDS) - SPARSE))
def test_enough_reports_carry_the_field(field: str) -> None:
    """The check is only worth something if AWC supplied the field on a good number of saved reports."""
    populated = sum(1 for row in awc_rows() if row.get(field) is not None)
    assert populated >= 20, field


def test_weather_strings_match_awc() -> None:
    """Present weather: our weather groups of the body against AWC's ``wxString`` (order differs, ``//`` is dropped)."""
    found: list[str] = []
    for row in awc_rows():
        if ("wxString", row["rawOb"]) in EXCEPTIONS:
            continue
        metar = decode(row)
        stop = metar.tail_index if metar.tail_index is not None else metar.remarks_index
        body = metar.tokens[:stop] if stop is not None else metar.tokens
        ours = sorted(tok.text for tok in body if tok.kind is SemanticKind.WEATHER and tok.text != "//")
        theirs = sorted((row.get("wxString") or "").split())
        if ours != theirs:
            found.append(f"ours={ours} awc={theirs} :: {row['rawOb']}")
    assert not found, "\n".join(found)


def test_exceptions_are_not_stale() -> None:
    """Every excused report is still in the saved batches and still disagrees (otherwise delete the entry)."""
    rows = {row["rawOb"]: row for row in awc_rows()}
    for field, raw in EXCEPTIONS:
        assert raw in rows, raw
        if field == "wxString":
            continue  # covered by the explicit comparison above
        ours, theirs = FIELDS[field](decode(rows[raw]), rows[raw])
        assert not near(ours, theirs, 0.0051 if field.startswith(("precip", "pcp")) else TOLERANCE), (field, raw)


def test_the_synoptic_groups_fall_on_synoptic_reports() -> None:
    """6- and 3-hour precipitation periods come from the report time; AWC only reports them on those hours."""
    for row in awc_rows():
        metar = decode(row)
        for item in metar.remarks_of(PeriodPrecipitation):
            assert item.hours in (3, 6), row["rawOb"]
