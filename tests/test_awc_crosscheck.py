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
    FlightCategory,
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


NORWAY_WIND = (
    "Norwegian `RMK WIND <height>FT <wind>` remarks: AWC fills maxT/minT with values that are not in the text."
)
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

NO_SKY = "The sky was not observed (`//////`): AWC gives no flight category, we classify on the visibility alone."
NO_CATEGORY = "AWC gives no flight category for a report whose cloud layers carry only `///` types; we classify it."
NO_VISIBILITY = "AWC leaves visib empty for a 9999 report whose cloud layers carry only `///` types."
ZERO_CEILING = "A layer at 0 ft (`OVC000`, `BKN000`): AWC drops it from `clouds`, we report a ceiling of 0 ft."
BGSF = (
    "METAR BGSF 310820Z AUTO 05008KT 9999NDV SCT080/// OVC100/// M01/M08 Q1001",
    "METAR BGSF 310750Z AUTO 04007KT 010V070 9999NDV BKN100/// BKN120/// M01/M07 Q1001",
    "METAR BGSF 310720Z AUTO 04007KT 9999NDV BKN110/// BKN120/// M01/M07 Q1001",
)
EXCEPTIONS.update(
    {
        ("fltCat", raw): NO_SKY
        for raw in (
            "METAR ETHB 310820Z AUTO 30002KT 1000 // ////// 08/07 Q1033 ///",
            "METAR ETHC 310820Z AUTO 27002KT 0900 // ////// 08/08 Q1033 ///",
            "METAR ETNW 310820Z AUTO 29005KT 3500 // ////// 08/08 Q1033 ///",
            "METAR ETNW 310720Z AUTO 28005KT 3200 // ////// 08/08 Q1033 ///",
            "METAR ETSL 310720Z AUTO 06001KT 2700 // ////// 03/03 Q1029 ///",
            "METAR ETHB 310720Z AUTO 27003KT 3000 // ////// 07/07 Q1033 ///",
            "METAR ETHC 310720Z AUTO VRB01KT 0600 // ////// 08/08 Q1033 ///",
            "METAR ETHS 310720Z AUTO 00000KT 4800 // ////// 09/08 Q1033 ///",
        )
    }
    | {("visib", raw): NO_VISIBILITY for raw in BGSF}
    | {("fltCat", raw): NO_CATEGORY for raw in BGSF}
    | {
        ("ceiling", raw): ZERO_CEILING
        for raw in (
            "METAR LFLL 310530Z 16001KT 5000 1700 BR BKN000 OVC003 07/07 Q1025 TEMPO 0300 FG VV///",
            "METAR EHVK 310825Z AUTO 05006KT 0300 FG OVC000 06/06 Q1033 RED",
            "METAR EHVK 310755Z AUTO 08007KT 0350 FG OVC000 07/07 Q1033 RED",
            "METAR ETNG 310750Z AUTO 07004KT 0350 // OVC000/// 05/04 Q1032",
            "METAR EHVK 310725Z AUTO 06006KT 0500 FG OVC000 06/06 Q1033 RED",
            "METAR EHVK 310655Z AUTO 09006KT 050V130 0550 FG OVC000 07/07 Q1033 RED",
        )
    }
)

KNOT_TOLERANCE = 0.51  # AWC reports whole knots
MILE_TOLERANCE = 0.06  # and visibility to a hundredth of a mile at most


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


def wind_direction(metar: Metar, row: dict[str, Any]) -> tuple[float | None, float | None]:
    wind = metar.wind
    theirs = row.get("wdir")
    return (wind.direction if wind and not wind.variable else None), (None if theirs == "VRB" else theirs)


def wind_speed(metar: Metar, row: dict[str, Any]) -> tuple[float | None, float | None]:
    wind = metar.wind
    return (wind.speed.knots if wind and wind.speed else None), row.get("wspd")


def wind_gust(metar: Metar, row: dict[str, Any]) -> tuple[float | None, float | None]:
    wind = metar.wind
    return (wind.gust.knots if wind and wind.gust else None), row.get("wgst")


def visibility(metar: Metar, row: dict[str, Any]) -> tuple[float | None, float | None]:
    """AWC caps what it reports at ``6+`` (a 9999 report) or ``10+``; ours is capped the same way before comparing."""
    seen = metar.visibility
    ours = None
    if seen is not None and seen.distance is not None:
        ours = seen.distance.statute_miles
    elif seen is not None and (seen.cavok or seen.unlimited):
        ours = 10.0
    theirs = row.get("visib")
    if isinstance(theirs, str):
        cap = float(theirs.rstrip("+"))
        return (None if ours is None else min(ours, cap)), cap
    return ours, theirs


def ceiling(metar: Metar, row: dict[str, Any]) -> tuple[float | None, float | None]:
    heights = [
        layer["base"]
        for layer in row.get("clouds") or []
        if layer["cover"] in ("BKN", "OVC", "OVX") and layer.get("base") is not None
    ]
    if row.get("vertVis") is not None:
        heights.append(row["vertVis"] * 100)
    return (metar.ceiling.value if metar.ceiling else None), (min(heights) if heights else None)


def altimeter(metar: Metar, row: dict[str, Any]) -> tuple[float | None, float | None]:
    return (metar.altimeter.hpa if metar.altimeter else None), row.get("altim")


def flight_category(metar: Metar, row: dict[str, Any]) -> tuple[float | None, float | None]:
    """The categories as severity ranks (VFR 0 to LIFR 3), so one comparison serves every field."""
    theirs = row.get("fltCat")
    return (
        None if metar.flight_category is None else metar.flight_category.rank,
        None if theirs is None else FlightCategory(theirs).rank,
    )


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
    "wdir": wind_direction,
    "wspd": wind_speed,
    "wgst": wind_gust,
    "visib": visibility,
    "ceiling": ceiling,
    "altim": altimeter,
    "fltCat": flight_category,
}

# Fields AWC lists but the saved reports never populate (no 15Z/21Z, 12Z or snow-reporting station was in the
# batches); the checks still run and pass vacuously, and the decoders are covered by tests/test_remarks.py.
SPARSE = {"pcp3hr", "pcp24hr", "snow"}


def tolerance_for(field: str) -> float:
    if field in ("precip", "pcp6hr", "pcp3hr", "pcp24hr"):
        return 0.0051
    return {"wspd": KNOT_TOLERANCE, "wgst": KNOT_TOLERANCE, "altim": KNOT_TOLERANCE, "visib": MILE_TOLERANCE}.get(
        field, TOLERANCE
    )


def mismatches(field: str) -> list[str]:
    compare = FIELDS[field]
    found: list[str] = []
    for row in awc_rows():
        if (field, row["rawOb"]) in EXCEPTIONS:
            continue
        ours, theirs = compare(decode(row), row)
        if not near(ours, theirs, tolerance_for(field)):
            found.append(f"{field}: ours={ours} awc={theirs} :: {row['rawOb']}")
    return found


@pytest.mark.parametrize("field", sorted(FIELDS))
def test_decoded_field_matches_awc(field: str) -> None:
    assert not mismatches(field)


@pytest.mark.parametrize("field", sorted(set(FIELDS) - SPARSE))
def test_enough_reports_carry_the_field(field: str) -> None:
    """The check is only worth something if AWC supplied the field on a good number of saved reports."""
    key = {"ceiling": "clouds"}.get(field, field)
    populated = sum(1 for row in awc_rows() if row.get(key) is not None)
    assert populated >= (10 if field == "wgst" else 20), field


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
        assert not near(ours, theirs, tolerance_for(field)), (field, raw)


def test_the_synoptic_groups_fall_on_synoptic_reports() -> None:
    """6- and 3-hour precipitation periods come from the report time; AWC only reports them on those hours."""
    for row in awc_rows():
        metar = decode(row)
        for item in metar.remarks_of(PeriodPrecipitation):
            assert item.hours in (3, 6), row["rawOb"]
