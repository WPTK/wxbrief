"""``--selftest`` is the smoke test the release workflow runs on every built binary."""

from __future__ import annotations

import pytest

from wxbrief.__main__ import main
from wxbrief.selftest import CHECKS, run_selftest


def test_selftest_passes(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--selftest"]) == 0
    out = capsys.readouterr().out
    assert out.count("ok   ") == len(CHECKS)
    assert "FAIL" not in out
    assert "ok   app:" in out


def test_selftest_fails_when_a_check_fails(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def broken() -> str:
        raise RuntimeError("boom")

    monkeypatch.setattr("wxbrief.selftest.CHECKS", (("broken", broken), *CHECKS))
    assert run_selftest() == 1
    assert "FAIL broken" in capsys.readouterr().out
