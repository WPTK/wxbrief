"""CLI polish: translated subcommand help, one JSON escaping, UTF-8 help when piped, FORCE_COLOR."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

COBOL = "METAR KDEN 131453Z 06007KT 3/4SM R35L/P6000FT BR OVC003 09/08 A3001 RMK AO2 SFC"
ACCENTED = "METAR KDEN 131453Z 06007KT 10SM FEW030 09/08 A3001 RMK ÉTÉ"
NOT_INHERITED = {"PYTHONIOENCODING", "PYTHONUTF8", "FORCE_COLOR", "NO_COLOR"}


def run_raw(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[bytes]:
    """The command with the interpreter's own default encodings (no PYTHONIOENCODING), output as bytes."""
    base = {k: v for k, v in os.environ.items() if k not in NOT_INHERITED}
    return subprocess.run(
        [sys.executable, "-m", "wxbrief", *args], capture_output=True, env={**base, **(env or {})}, timeout=60, check=False
    )


@pytest.mark.parametrize("command", ["decode", "get"])
def test_subcommand_help_follows_lang(command: str) -> None:
    english = run_raw(command, "--help").stdout.decode("utf-8")
    german = run_raw("--lang", "de", command, "--help").stdout.decode("utf-8")
    assert german != english
    assert "plain text" in english and "plain text" not in german
    assert "Klartext" in german


def test_json_keeps_non_ascii_characters_as_get_does() -> None:
    out = run_raw("decode", "--json", ACCENTED).stdout.decode("utf-8")
    assert "\\u00c9" not in out and "ÉTÉ" in out


def test_piped_help_is_utf8() -> None:
    out = run_raw("--lang", "de", "--help").stdout
    text = out.decode("utf-8")  # raises on the lone cp1252 bytes this used to write
    assert "ü" in text or "ä" in text or "ö" in text


def test_force_color_colours_piped_output() -> None:
    esc = b"\x1b["
    assert esc not in run_raw("decode", COBOL).stdout
    assert esc in run_raw("decode", COBOL, env={"FORCE_COLOR": "1"}).stdout
    assert esc not in run_raw("decode", "--plain", COBOL, env={"FORCE_COLOR": "1"}).stdout
