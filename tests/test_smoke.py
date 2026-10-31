"""Smoke tests for the package entry point."""

from __future__ import annotations

import subprocess
import sys

import pytest

import wxbrief
from wxbrief.__main__ import main


def test_version_is_zerover() -> None:
    major, minor, patch = (int(part) for part in wxbrief.__version__.split("."))
    assert major == 0
    assert minor >= 1 and patch >= 0


def test_version_flag_in_process(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert capsys.readouterr().out.strip() == "wxbrief 0.2.0"


def test_no_arguments_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert capsys.readouterr().out.startswith("usage: wxbrief")


def test_version_flag_as_module() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "wxbrief", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == f"wxbrief {wxbrief.__version__}"
