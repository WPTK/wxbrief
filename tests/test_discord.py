"""The Discord renderer: the layout of the reference notes for a METAR and for a TAF.

The reference notes (``metar-taf-decode``, ``SKILL.md``) were not available when these tests were written, so they
check the layout this renderer documents in ``render/discord.py``: a title line with the condition emoji, the
observation time, one line per element, a blank line, the clouds, a divider and the pressure/trend tail for a METAR;
a header, the divider and one block per period with its flight category for a TAF.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest

from wxbrief.decode.model import Condition, Metar, Taf
from wxbrief.decode.split import parse_any
from wxbrief.decode.units import UnitsMode
from wxbrief.i18n import Translator
from wxbrief.render.discord import (
    CONDITION_EMOJI,
    DIVIDER,
    NO_CONDITION_EMOJI,
    TAF_EMOJI,
    condition_emoji,
    discord_block,
    render_discord,
)
from wxbrief.render.phrases import describe_change_header

REF = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
T = Translator.load("en")
FENCE = "```"


def report(raw: str) -> Metar | Taf:
    (item,) = parse_any(raw, REF)
    return item


def block(raw: str, units: UnitsMode = UnitsMode.US, **kwargs: object) -> str:
    return discord_block(report(raw), T, units, **kwargs)  # type: ignore[arg-type]


def wrapped(*lines: str) -> str:
    return "\n".join([FENCE, *lines, FENCE])


# --- METAR ---------------------------------------------------------------------------------------------------------------


def test_a_metar_with_remarks_reproduces_the_template() -> None:
    raw = "METAR KJAX 312256Z AUTO 17005KT 10SM FEW030 24/20 A3003 RMK AO2 SLP170 T02390200 58008"
    assert block(raw) == wrapped(
        "🌤️ KJAX",
        "Obs: 22:56 UTC (312256Z)  — AUTO",
        "",
        "Wind: 170° @ 5 kt (S)",
        "Visibility: 10 SM",
        "Temperature: 75.0°F (23.9°C) | Dewpoint: 68.0°F (20.0°C)",
        "Altimeter: 30.03 inHg",
        "",
        "Clouds: Few clouds at 3,000 ft",
        DIVIDER,
        "Pressure: 1017.0 mb (falling -0.8 mb/3hr)",
    )


def test_an_icao_metar_in_the_three_unit_modes() -> None:
    raw = "METAR EGLL 311050Z AUTO 24010G20KT 200V280 CAVOK 12/08 Q1013 NOSIG"
    common_tail = [
        DIVIDER,
        "Trend: NOSIG (no significant change expected in the next 2 hours)",
    ]
    assert block(raw, UnitsMode.US) == wrapped(
        "☀️ EGLL",
        "Obs: 10:50 UTC (311050Z)  — AUTO",
        "",
        "Wind: 240° @ 10 kt, gusting 20 kt (WSW), varying 200°-280°",
        "Visibility: CAVOK",
        "Temperature: 54°F (12°C) | Dewpoint: 46°F (8°C)",
        "Altimeter: 29.91 inHg (1013 hPa)",
        *common_tail,
    )
    assert block(raw, UnitsMode.METRIC) == wrapped(
        "☀️ EGLL",
        "Obs: 10:50 UTC (311050Z)  — AUTO",
        "",
        "Wind: 240° @ 19 km/h (10 kt), gusting 37 km/h (20 kt) (WSW), varying 200°-280°",
        "Visibility: CAVOK",
        "Temperature: 12°C | Dewpoint: 8°C",
        "Altimeter: 1013 hPa",
        *common_tail,
    )
    mixed = block(raw, UnitsMode.MIXED)
    assert "Temperature: 12°C (54°F) | Dewpoint: 8°C (46°F)" in mixed
    assert "Altimeter: 1013 hPa (29.91 inHg)" in mixed


def test_weather_goes_into_the_visibility_line_and_the_peak_wind_into_the_tail() -> None:
    raw = "METAR KSEA 311453Z 18014G25KT 2SM +TSRA BR OVC007CB 12/11 A2972 RMK AO2 PK WND 20032/1440 TSB40"
    assert block(raw) == wrapped(
        "⛈️ KSEA",
        "Obs: 14:53 UTC (311453Z)",
        "",
        "Wind: 180° @ 14 kt, gusting 25 kt (S)",
        "Visibility: 2 SM in thunderstorm with heavy rain and mist",
        "Temperature: 54°F (12°C) | Dewpoint: 52°F (11°C)",
        "Altimeter: 29.72 inHg",
        "",
        "Clouds: Overcast at 700 ft, cumulonimbus",
        DIVIDER,
        "Peak wind: 200° @ 32 kt at 14:40",
    )


def test_a_metar_without_a_tail_has_no_divider() -> None:
    text = block("METAR KDEN 311453Z 00000KT 10SM CLR M05/M12 A3001")
    assert DIVIDER not in text
    assert "Wind: Calm" in text
    assert "Temperature: 23°F (-5°C) | Dewpoint: 10°F (-12°C)" in text
    assert text.endswith("Clouds: Clear below 12,000 ft\n" + FENCE)


def test_station_name_and_daylight_dress_the_title() -> None:
    raw = "METAR KDEN 311453Z 00000KT 10SM CLR M05/M12 A3001"
    assert block(raw, station_name="Denver Intl Airport").splitlines()[1] == "☀️ KDEN — DENVER INTL AIRPORT"
    assert block(raw, daylight=False).splitlines()[1].startswith("🌙 KDEN")
    assert block(raw, daylight=True).splitlines()[1].startswith("☀️ KDEN")


def test_only_lines_that_exist_in_the_report_appear() -> None:
    text = block("METAR KDEN 311453Z 18010KT")
    assert text == wrapped("🌡️ KDEN", "Obs: 14:53 UTC (311453Z)", "", "Wind: 180° @ 10 kt (S)")


# --- the emoji --------------------------------------------------------------------------------------------------------


def test_every_condition_has_an_emoji_and_a_clear_sky_turns_into_a_moon_at_night() -> None:
    assert set(CONDITION_EMOJI) == set(Condition)
    assert condition_emoji(None) == NO_CONDITION_EMOJI
    assert condition_emoji(Condition.CLEAR) == "☀️"
    assert condition_emoji(Condition.CLEAR, False) == "🌙"
    assert condition_emoji(Condition.CLEAR, True) == "☀️"
    assert condition_emoji(Condition.RAIN, False) == CONDITION_EMOJI[Condition.RAIN]


# --- TAF -----------------------------------------------------------------------------------------------------------------


TAF_RAW = (
    "TAF KDEN 310500Z 3106/3118 18010KT P6SM SKC WS020/30035KT BECMG 3108/3110 4SM BR OVC008 "
    "TEMPO 3112/3114 1SM FM311600 20010KT P6SM SCT050 TXM02/3118Z TNM08/0108Z RMK NXT FCST"
)


def test_a_taf_has_a_header_a_divider_and_one_block_per_period() -> None:
    assert block(TAF_RAW) == wrapped(
        f"{TAF_EMOJI} KDEN",
        "TAF issued 05:00 UTC (310500Z)",
        "Valid: 31/0600Z → 31/1800Z",
        "",
        DIVIDER,
        "BASE — from 31/0600Z  [VFR]",
        "Wind: 180° @ 10 kt (S)",
        "Visibility: more than 6 SM",
        "Clouds: Sky clear",
        "Wind shear: At 2,000 ft above ground the wind is from 300° (WNW) at 35 kt",
        "",
        "BECMG 31/0800Z → 1000Z  [IFR]",
        "Visibility: 4 SM in mist",
        "Clouds: Overcast at 800 ft",
        "",
        "TEMPO 31/1200Z → 1400Z  [IFR]",
        "Visibility: 1 SM",
        "",
        "FROM 31/1600Z  [VFR]",
        "Wind: 200° @ 10 kt (SSW)",
        "Visibility: more than 6 SM",
        "Clouds: Scattered clouds at 5,000 ft",
        "",
        "Temperature: max 28°F (-2°C) at 31/1800Z | min 18°F (-8°C) at 01/0800Z",
        "Remarks: NXT FCST",
    )


def test_probability_groups_are_headed_with_their_probability() -> None:
    text = block(
        "TAF COR EGGW 310900Z 3109/3118 09005KT 3000 BR BKN003 PROB30 TEMPO 3109/3112 0800 FG VV001 "
        "INTER 3114/3117 4000 SHRA SCT008 PROB40 3117/3118 -DZ",
        UnitsMode.METRIC,
        station_name="London Luton",
    )
    lines = text.splitlines()
    assert lines[1] == f"{TAF_EMOJI} EGGW — LONDON LUTON"
    assert lines[2] == f"TAF issued 09:00 UTC (310900Z)  — {'⚠️'} COR"
    assert "PROB30 TEMPO 31/0900Z → 1200Z  [LIFR]" in lines
    assert "INTER 31/1400Z → 1700Z  [IFR]" in lines
    assert "PROB40 31/1700Z → 1800Z  [LIFR]" in lines
    assert "Wind: 090° @ 9 km/h (5 kt) (E)" in lines
    assert "Clouds: Sky obscured, vertical visibility 30 m (100 ft)" in lines


def test_a_window_that_crosses_midnight_repeats_the_day() -> None:
    text = block("TAF KJFK 312200Z 3122/0106 06007KT P6SM SKC TEMPO 3123/0102 3SM BR")
    assert "TEMPO 31/2300Z → 01/0200Z  [MVFR]" in text.splitlines()
    assert "Valid: 31/2200Z → 01/0600Z" in text.splitlines()


def test_an_amendment_is_flagged_beside_the_issue_time() -> None:
    assert "TAF issued 07:00 UTC (310700Z)  — AMD" in block("TAF AMD WSSS 310700Z 3107/0112 10007KT 9999 FEW015")


def test_a_cancelled_forecast_says_so_and_has_no_period() -> None:
    assert block("TAF AMD LFPG 311000Z 3110/3118 CNL") == wrapped(
        f"{TAF_EMOJI} LFPG",
        "TAF issued 10:00 UTC (311000Z)  — AMD  — ⚠️ CANCELLED",
        "Valid: 31/1000Z → 31/1800Z",
        "",
        DIVIDER,
        "No forecast groups",
    )


def test_backticks_in_remarks_cannot_close_the_fence() -> None:
    out = block("TAF KJFK 312200Z 3122/0106 06007KT P6SM SKC RMK A```B `C`")
    body = out.split("\n", 1)[1].rsplit("\n", 1)[0]
    assert "`" not in body
    assert "A" + "'" * 3 + "B 'C'" in body
    assert out.startswith(FENCE) and out.endswith(FENCE)


def test_a_nil_forecast() -> None:
    assert block("TAF LFPB 311000Z NIL") == wrapped(
        f"{TAF_EMOJI} LFPB",
        "TAF issued 10:00 UTC (311000Z)  — NIL",
        "",
        DIVIDER,
        "No forecast groups",
    )


def test_military_extras_are_shown() -> None:
    text = block("TAF KHIF 310100Z 3101/0103 18006KT 9000 -SHRA OVC050 520009 QNH2992INS BECMG 3104/3105 610505")
    assert "Altimeter: 29.92 inHg" in text
    assert "Turbulence:" in text
    assert "Icing:" in text


# --- the wrapper -----------------------------------------------------------------------------------------------------------


def test_render_discord_wraps_the_block_in_an_outer_fence() -> None:
    item = report("METAR KDEN 311453Z 00000KT 10SM CLR M05/M12 A3001")
    inner = discord_block(item, T)
    outer = render_discord(item, T)
    assert outer == f"````\n{inner}\n````"
    assert render_discord(item, T, outer_fence=False) == inner
    assert inner.startswith(FENCE + "\n") and inner.endswith("\n" + FENCE)
    assert FENCE not in inner[len(FENCE) : -len(FENCE)]  # nothing inside can end the block early


@pytest.mark.parametrize("raw", ["garbage text", "TAF", "METAR", "TAF KDEN", "METAR KDEN 311453Z"])
def test_unreadable_input_still_renders_a_block(raw: str) -> None:
    text = block(raw)
    assert text.startswith(FENCE) and text.endswith(FENCE)


def test_a_probable_intermittent_group_keeps_its_probability() -> None:
    raw = "TAF YPAD 310800Z 3108/0114 18010KT 9999 SCT040 PROB30 INTER 3120/3122 4000 SHRA SCT008"
    assert "PROB30 INTER 31/2000Z → 2200Z  [IFR]" in block(raw, UnitsMode.METRIC).splitlines()
    taf = report(raw)
    assert isinstance(taf, Taf)
    header = describe_change_header(T, taf.changes[0])
    assert header.startswith("30% chance of intermittent conditions")


# --- the 2000-character message limit and the decoder's warnings -------------------------------------------------

LONG_TAF = (
    "TAF KRIV 310404Z 3104/0110 15006KT 9999 BKN035 BKN050 QNH2991INS BECMG 3105/3106 16006KT 9999 BKN025 BKN050 "
    "QNH2994INS BECMG 3108/3109 16006KT 8000 BR BKN015 BKN040 OVC250 QNH2992INS BECMG 3114/3115 16006KT 9999 NSW "
    "SCT030 BKN050 BKN200 QNH2988INS BECMG 3121/3122 28009KT 9999 BKN030 OVC080 QNH2987INS WND 230V330 TEMPO "
    "3122/0101 29010G15KT BECMG 0101/0102 29009KT 9999 VCSH SCT015 BKN020 OVC030 QNH2991INS TEMPO 0102/0106 9000 "
    "-SHRA BKN015 OVC030 BECMG 0105/0106 VRB04KT 9999 VCSH BKN015 OVC030 QNH2989INS TEMPO 0106/0110 8000 -SHRA BR "
    "BKN010 OVC025 BECMG 0109/0110 15006KT 8000 -SHRA BR BKN007 BKN020 510708 QNH2989INS TX20/3122Z TN11/3114Z"
)  # the KRIV forecast from tests/fixtures/awc: 2166 characters as one block in English, 2410 in Portuguese


@pytest.mark.parametrize("lang", ["en", "pt"])
def test_a_long_report_is_split_into_blocks_that_each_fit_in_one_message(lang: str) -> None:
    item = report(LONG_TAF)
    t = Translator.load(lang)
    fence_re = r"```\n.*?\n```"
    inner = re.findall(fence_re, render_discord(item, t, outer_fence=False), re.S)
    assert len(inner) >= 2
    assert all(len(block) <= 2000 for block in inner)
    outer = re.findall(r"````\n" + fence_re + r"\n````", render_discord(item, t), re.S)
    assert len(outer) == len(inner)  # every part is a complete block inside its own outer fence
    assert all(len(block) <= 2000 for block in outer)


def test_a_split_happens_between_lines_and_loses_nothing() -> None:
    item = report(LONG_TAF)
    whole = [ln for ln in render_discord(item, T, outer_fence=False).split("\n") if ln and ln != FENCE]
    parts = render_discord(item, T, outer_fence=False).split(FENCE + "\n\n" + FENCE)
    assert len(parts) >= 2
    assert whole == [ln for part in parts for ln in part.split("\n") if ln and ln != FENCE]
    assert sum(1 for ln in whole if ln.startswith("BECMG")) >= 2


def test_a_short_report_stays_one_block() -> None:
    text = render_discord(report("METAR KDEN 131453Z 06007KT 10SM FEW030 09/08 A3001"), T)
    assert text.count("````") == 2


def test_unread_groups_are_listed_in_the_discord_block() -> None:
    text = block("METAR KDEN 131453Z 06007KT 10SM FEW030 09/08 A3001 FOO")
    assert "1 warning" in text and "Unrecognized group: FOO" in text
    assert text.endswith(FENCE)


def test_length_counts_utf16_units_and_never_splits_an_emoji() -> None:
    from wxbrief.render.discord import _units, _wrap

    heart = "\u2764\ufe0f"  # one character plus a variation selector
    pair = "\U0001f468\u200d\U0001f469"  # man, ZWJ, woman: five UTF-16 units
    line = "x" * 9 + heart + pair * 4
    for limit in (10, 11, 12, 13, 14):
        pieces = _wrap(line, limit)
        assert "".join(pieces) == line
        assert all(_units(p) <= limit for p in pieces)
        assert not any(p.startswith(("\ufe0f", "\u200d")) or p.endswith("\u200d") for p in pieces)
    assert _units("\U0001f321") == 2


def test_a_copy_that_is_several_messages_says_so_in_the_toast() -> None:
    from wxbrief.render.discord import block_count
    from wxbrief.ui.copying import parts_note

    long_text = render_discord(report(LONG_TAF), T, outer_fence=False)
    count = block_count(long_text)
    assert count >= 2
    assert str(count) in parts_note(T, "KRIV", long_text) and "own message" in parts_note(T, "KRIV", long_text)
    short = block("METAR KDEN 131453Z 06007KT 10SM FEW030 09/08 A3001")
    assert parts_note(T, "KDEN", short) == "KDEN"
    assert parts_note(T, "KDEN", short + "\n\n" + short, reports=2) == "KDEN"
    for lang in ("de", "es", "fr", "pt"):
        assert "{" not in parts_note(Translator.load(lang), "X", long_text)
