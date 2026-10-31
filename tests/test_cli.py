"""The ``wxbrief decode`` command, in process and as a subprocess."""

from __future__ import annotations

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
    assert "Visibility:                   CAVOK" in result.stdout
    assert "Pressure:                     1013 hPa (29.91 inHg)" in result.stdout
    assert "VFR (visual flight rules)" in result.stdout


def test_decode_reads_stdin_one_report_per_line() -> None:
    result = run_module(
        "decode", "--date", "2026-10-13", stdin=f"{COBOL}\n\nMETAR KSEA 131453Z 18014KT 2SM +RA BR OVC007 12/11 A2972\n"
    )
    assert result.returncode == 0
    assert result.stdout.count("Station:") == 2
    assert "KDEN is reporting LIFR" in result.stdout
    assert "KSEA is reporting IFR" in result.stdout


def test_decode_reads_stdin_with_a_dash_free_pipe() -> None:
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


def test_rich_output_on_a_terminal(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    import io

    class FakeTty(io.StringIO):
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(sys, "stdout", FakeTty())
    assert main(["decode", "--date", "2026-10-13", COBOL]) == 0
    out = sys.stdout.getvalue()  # type: ignore[attr-defined]
    assert "KDEN" in out
    assert "LIFR" in out
    assert "Traceback" not in out


def test_plain_flag_forces_plain_output_on_a_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    import io

    class FakeTty(io.StringIO):
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(sys, "stdout", FakeTty())
    assert main(["decode", "--plain", "--date", "2026-10-13", COBOL]) == 0
    assert "\x1b" not in sys.stdout.getvalue()  # type: ignore[attr-defined]


def test_version_still_works() -> None:
    result = run_module("--version")
    assert result.returncode == 0
    assert result.stdout.strip() == "wxbrief 0.1.0"


def test_help_lists_the_decode_command() -> None:
    result = run_module("--help")
    assert "decode" in result.stdout
    helped = run_module("decode", "--help")
    assert "--plain" in helped.stdout
    assert "--units" in helped.stdout
    assert "--date" in helped.stdout
