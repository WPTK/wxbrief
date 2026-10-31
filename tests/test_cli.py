"""The ``wxbrief decode`` command, in process and as a subprocess."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys

import pytest

from wxbrief.__main__ import main

COBOL = "METAR KDEN 131453Z 06007KT 3/4SM R35L/P6000FT BR OVC003 09/08 A3001 RMK AO2 SFC"
EGLL = "METAR EGLL 311050Z AUTO 24010KT 200V280 CAVOK 12/08 Q1013 NOSIG"
DEG = "°"


def run_module(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "wxbrief", *args],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        timeout=60,
        check=False,
    )


def test_decode_argument_prints_a_lifr_decode() -> None:
    result = run_module("decode", "--date", "2026-10-13", COBOL)
    assert result.returncode == 0
    assert result.stderr == ""
    lines = result.stdout.splitlines()
    assert "Station:             KDEN" in lines
    assert "Flight category:     LIFR (low instrument flight rules)" in lines
    assert "Observed:            2026-10-13 14:53 UTC" in lines
    assert f"Wind:                From 060{DEG} (ENE) at 7 kt (13 km/h)" in lines
    assert "Visibility:          3/4 SM (1.2 km)" in lines
    assert "Runway visual range: Runway 35L: more than 6,000 ft (1,829 m)" in lines
    assert "Ceiling:             300 ft (91 m)" in lines
    assert "Flags:               Low ceiling, Low visibility" in lines
    assert "\x1b" not in result.stdout  # a pipe is not a terminal, so the output is plain


def test_decode_icao_report_in_metres_and_hpa() -> None:
    result = run_module("decode", "--date", "2026-10-31", EGLL)
    assert result.returncode == 0
    assert "Visibility:        CAVOK" in result.stdout
    assert "Pressure:          1013 hPa (29.91 inHg)" in result.stdout
    assert "VFR (visual flight rules)" in result.stdout


def test_decode_reads_stdin_one_report_per_line() -> None:
    result = run_module(
        "decode", "--date", "2026-10-13", stdin=f"{COBOL}\n\nMETAR KSEA 131453Z 18014KT 2SM +RA BR OVC007 12/11 A2972\n"
    )
    assert result.returncode == 0
    assert result.stdout.count("Station:") == 2
    assert "KDEN is reporting LIFR" in result.stdout
    assert "KSEA is reporting IFR" in result.stdout


def test_decode_reads_a_single_report_from_stdin() -> None:
    result = run_module("decode", "--date", "2026-10-13", "--plain", stdin=COBOL)
    assert result.returncode == 0
    assert "Flight category:     LIFR" in result.stdout


def test_decode_with_no_input_is_a_usage_error() -> None:
    result = run_module("decode", stdin="")
    assert result.returncode == 2
    assert "no report text" in result.stderr
    assert "Traceback" not in result.stderr


def test_garbage_input_prints_warnings_and_exits_zero() -> None:
    result = run_module("decode", "this is not a weather report ☃ ???")
    assert result.returncode == 0
    assert "Traceback" not in result.stdout + result.stderr
    assert "Unrecognized group: THIS" in result.stdout
    assert "warnings" in result.stdout


def test_nul_bytes_on_stdin_do_not_crash() -> None:
    result = run_module("decode", stdin="METAR KDEN\x00 131453Z \x00\n")
    assert result.returncode == 0
    assert "Traceback" not in result.stderr


def test_unquoted_words_are_one_report(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["decode", "--date", "2026-10-13", *COBOL.split()]) == 0
    out = capsys.readouterr().out
    assert out.count("Station:") == 1
    assert "KDEN is reporting LIFR" in out


def test_several_quoted_arguments_are_several_reports(capsys: pytest.CaptureFixture[str]) -> None:
    assert (
        main(["decode", "--date", "2026-10-13", COBOL, "METAR KSEA 131453Z 18014KT 2SM +RA BR OVC007 12/11 A2972"]) == 0
    )
    assert capsys.readouterr().out.count("Station:") == 2


def test_units_option(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["decode", "--date", "2026-10-13", "--units", "us", COBOL]) == 0
    out = capsys.readouterr().out
    assert "Visibility:          3/4 SM\n" in out
    assert main(["decode", "--date", "2026-10-13", "--units", "metric", COBOL]) == 0
    assert "Visibility:          1.2 km (3/4 SM)" in capsys.readouterr().out


def test_bad_units_and_dates_are_rejected_by_argparse(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["decode", "--units", "imperial", COBOL])
    assert excinfo.value.code == 2
    with pytest.raises(SystemExit) as excinfo:
        main(["decode", "--date", "13/10/2026", COBOL])
    assert excinfo.value.code == 2
    assert "expected YYYY-MM-DD" in capsys.readouterr().err


def test_date_resolves_the_day_of_month(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["decode", "--date", "2027-01-01", "METAR KDEN 312350Z 06007KT 10SM CLR 09/08 A3001"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert any(line.startswith("Observed:") and line.endswith("2026-12-31 23:50 UTC") for line in lines)


def test_without_a_date_the_current_month_is_used(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["decode", "METAR KDEN 011200Z 06007KT 10SM CLR 09/08 A3001"]) == 0
    assert "Observed:" in capsys.readouterr().out


class FakeTty(io.StringIO):
    """A stdout that claims to be a terminal."""

    def isatty(self) -> bool:
        return True


def test_rich_output_on_a_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeTty()
    monkeypatch.setattr(sys, "stdout", fake)
    assert main(["decode", "--date", "2026-10-13", COBOL]) == 0
    assert "KDEN" in fake.getvalue()
    assert "LIFR" in fake.getvalue()
    assert "Traceback" not in fake.getvalue()


def test_plain_flag_forces_plain_output_on_a_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeTty()
    monkeypatch.setattr(sys, "stdout", fake)
    assert main(["decode", "--plain", "--date", "2026-10-13", COBOL]) == 0
    assert "" not in fake.getvalue()
    assert "Flight category:" in fake.getvalue()


def test_a_leading_dash_group_needs_quotes_or_a_double_dash(capsys: pytest.CaptureFixture[str]) -> None:
    words = ["METAR", "KSEA", "131453Z", "18014KT", "2SM", "-RA", "BR", "OVC007", "12/11", "A2972"]
    with pytest.raises(SystemExit) as excinfo:
        main(["decode", *words])
    assert excinfo.value.code == 2
    capsys.readouterr()
    assert main(["decode", "--date", "2026-10-13", "--", *words]) == 0
    out = capsys.readouterr().out
    assert "Light rain and mist" in out
    assert main(["decode", "--date", "2026-10-13", " ".join(words)]) == 0
    assert "Light rain and mist" in capsys.readouterr().out


def test_version_still_works() -> None:
    result = run_module("--version")
    assert result.returncode == 0
    assert result.stdout.strip() == "wxbrief 0.2.0"


def test_help_lists_the_decode_command() -> None:
    result = run_module("--help")
    assert "decode" in result.stdout
    helped = run_module("decode", "--help")
    assert "--plain" in helped.stdout
    assert "--units" in helped.stdout
    assert "--date" in helped.stdout


# --- TAFs, --json and --discord -------------------------------------------------------------------------------------

TAF = "TAF KDEN 130500Z 1306/1412 18010KT P6SM SKC BECMG 1308/1310 4SM BR OVC008 TEMPO 1312/1314 1SM"


def test_decode_prints_a_taf_in_plain_text(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["decode", "--date", "2026-10-13", "--plain", TAF]) == 0
    out = capsys.readouterr().out
    assert "Station:" in out and "KDEN" in out
    assert "Traceback" not in out
    assert "BECMG" in out or "Becoming" in out


def test_a_blob_of_mixed_reports_on_stdin_is_split() -> None:
    blob = f"{COBOL}\n\n{TAF}\n  FM131800 20010KT P6SM SCT050\n\nMETAR KSEA 131453Z 18014KT 2SM +RA BR OVC007 12/11 A2972=\n"
    result = run_module("decode", "--date", "2026-10-13", "--json", stdin=blob)
    assert result.returncode == 0
    items = json.loads(result.stdout)
    assert [item["report_type"] for item in items] == ["METAR", "TAF", "METAR"]
    assert items[1]["station"] == "KDEN"
    assert len(items[1]["changes"]) == 3


def test_json_is_a_list_of_language_neutral_dicts() -> None:
    result = run_module("decode", "--date", "2026-10-13", "--json", COBOL, TAF)
    assert result.returncode == 0
    assert result.stderr == ""
    items = json.loads(result.stdout)
    assert len(items) == 2
    metar, taf = items
    assert metar["station"] == "KDEN" and metar["flight_category"] == "LIFR"
    assert metar["observed"] == "2026-10-13T14:53:00+00:00"
    assert taf["report_type"] == "TAF"
    assert taf["issue_time"] == "2026-10-13T05:00:00+00:00"
    assert taf["valid_from"] == "2026-10-13T06:00:00+00:00"
    assert taf["base"]["change"] == "BASE"
    assert [change["change"] for change in taf["changes"]] == ["BECMG", "TEMPO"]
    assert taf["worst_category"] == "IFR"
    assert "\x1b" not in result.stdout


def test_json_is_never_translated_or_unit_converted(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["decode", "--date", "2026-10-13", "--json", "--units", "metric", COBOL]) == 0
    metar = json.loads(capsys.readouterr().out)[0]
    assert metar["visibility"]["distance"] == {"value": 0.75, "unit": "SM"}


def test_discord_prints_one_fenced_block_per_report() -> None:
    result = run_module("decode", "--date", "2026-10-13", "--discord", COBOL, TAF)
    assert result.returncode == 0
    assert result.stderr == ""
    lines = result.stdout.strip().splitlines()
    assert lines.count("````") == 4  # an outer fence around each of the two blocks
    first_end = lines.index("````", 1)
    blocks = ["\n".join(lines[: first_end + 1]), "\n".join(lines[first_end + 2 :])]
    assert lines[first_end + 1] == ""
    for text in blocks:
        parts = text.splitlines()
        assert parts[0] == "````" and parts[-1] == "````"
        assert parts[1] == "```" and parts[-2] == "```"
    assert "Obs: 14:53 UTC (131453Z)" in blocks[0]
    assert "Visibility: 3/4 SM in mist" in blocks[0]
    assert "TAF issued 05:00 UTC (130500Z)" in blocks[1]
    assert "TEMPO 13/1200Z → 1400Z  [IFR]" in blocks[1]


def test_discord_defaults_to_us_units_and_follows_units(capsys: pytest.CaptureFixture[str]) -> None:
    egll = "METAR EGLL 311050Z 24010KT CAVOK 12/08 Q1013"
    assert main(["decode", "--date", "2026-10-31", "--discord", egll]) == 0
    assert "Temperature: 54°F (12°C)" in capsys.readouterr().out
    assert main(["decode", "--date", "2026-10-31", "--discord", "--units", "metric", egll]) == 0
    assert "Temperature: 12°C | " in capsys.readouterr().out


def test_discord_and_json_are_utf8_whatever_the_console(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["decode", "--date", "2026-10-13", "--discord", COBOL]) == 0
    assert "°" in capsys.readouterr().out


def test_the_output_formats_exclude_each_other(capsys: pytest.CaptureFixture[str]) -> None:
    for first, second in (("--json", "--discord"), ("--plain", "--json"), ("--plain", "--discord")):
        with pytest.raises(SystemExit) as excinfo:
            main(["decode", first, second, COBOL])
        assert excinfo.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err


def test_json_and_discord_with_no_input_are_still_a_usage_error() -> None:
    for flag in ("--json", "--discord"):
        result = run_module("decode", flag, stdin="")
        assert result.returncode == 2
        assert result.stdout == ""


def test_help_lists_the_new_output_options() -> None:
    helped = run_module("decode", "--help").stdout
    assert "--json" in helped and "--discord" in helped


def test_piped_plain_output_is_utf8_whatever_the_console_code_page() -> None:
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}
    env["PYTHONLEGACYWINDOWSSTDIO"] = "1"
    result = subprocess.run(
        [sys.executable, "-m", "wxbrief", "decode", "--date", "2026-10-13", COBOL],
        capture_output=True,
        env=env,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0
    assert b"\xc2\xb0" in result.stdout
    assert b"\xb0" not in result.stdout.replace(b"\xc2\xb0", b"")
