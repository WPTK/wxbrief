"""L4: the command-line flags the README names and the ones ``--help`` lists are the same set, and each one is accepted."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
from journey_kit import program, program_env

README = Path(__file__).resolve().parents[2] / "README.md"
FLAG = re.compile(r"(?<![\w-])(--[a-z][a-z0-9-]+)")


def run(*args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, **program_env(), "PYTHONUTF8": "1", "COLUMNS": "200"}
    return subprocess.run([*program(), *args], capture_output=True, text=True, timeout=60, env=env, stdin=subprocess.DEVNULL)


def help_flags() -> set[str]:
    """Flags of the program and of its sub-commands (the README names ``decode --plain`` and the like)."""
    found: set[str] = set()
    for args in (("--help",), ("decode", "--help"), ("get", "--help")):
        found |= set(FLAG.findall(run(*args).stdout))
    return found - {"--help"}


def readme_flags() -> set[str]:
    return set(FLAG.findall(README.read_text(encoding="utf-8"))) - {"--help"}


def test_L4_every_flag_in_the_readme_is_in_help() -> None:
    in_help, in_readme = help_flags(), readme_flags()
    assert in_help, "--help lists no flags"
    assert not (in_readme - in_help), f"README names flags --help does not: {sorted(in_readme - in_help)}"


@pytest.mark.xfail(strict=True, reason="#263: README does not name --config and --layout")
def test_L4_every_flag_in_help_is_in_the_readme() -> None:
    in_help, in_readme = help_flags(), readme_flags()
    assert not (in_help - in_readme), f"--help lists flags the README does not: {sorted(in_help - in_readme)}"


@pytest.mark.parametrize("flag", sorted(help_flags() & {"--version"}))
def test_L4_version_prints_a_version(flag: str) -> None:
    done = run(flag)
    assert done.returncode == 0 and re.search(r"\d+\.\d+\.\d+", done.stdout + done.stderr)


SUBCOMMAND_FLAGS = {"--version", "--plain", "--json", "--discord", "--date", "--no-color", "--output"}
VALUES = {
    "--theme": ["nord"],
    "--glyphs": ["ascii"],
    "--layout": ["grid"],
    "--units": ["metric"],
    "--time": ["zulu"],
    "--lang": ["en"],
    "--config": ["{tmp}/c.toml"],
    "--no-config": [],
    "--demo": [],
}
METAR = "METAR KDEN 131453Z 06007KT 3/4SM BR OVC003 09/08 A3001"


@pytest.mark.parametrize("flag", sorted((help_flags() - SUBCOMMAND_FLAGS) | set(VALUES)))
def test_L4_every_flag_listed_in_help_is_accepted_and_changes_nothing_it_should_not(flag: str, tmp_path: Path) -> None:
    assert flag in VALUES, f"{flag} is listed by --help but this test does not know a value for it: extend VALUES"
    args = [a.format(tmp=tmp_path) for a in VALUES[flag]]
    done = run(flag, *args, "decode", METAR)
    assert done.returncode == 0 and "KDEN" in done.stdout, (done.returncode, done.stderr[-300:])
    assert not list(tmp_path.iterdir()), "a per-run flag wrote a file"
