"""The guards in conftest.py and pyproject.toml stop a runaway test instead of letting it exhaust the machine."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

CONFTEST = Path(__file__).with_name("conftest.py")


def _run_inner(tmp_path: Path, test_source: str, *args: str, rss_mb: int = 2048) -> subprocess.CompletedProcess[str]:
    (tmp_path / "conftest.py").write_text(CONFTEST.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "test_inner.py").write_text(test_source, encoding="utf-8")
    env = {**os.environ, "WXBRIEF_TEST_RSS_MB": str(rss_mb)}
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:xdist", *args],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )


def test_a_hung_test_fails_on_the_time_limit(tmp_path: Path) -> None:
    result = _run_inner(tmp_path, "import time\n\ndef test_hang():\n    time.sleep(60)\n", "--timeout", "2")
    assert result.returncode != 0
    assert "Timeout" in result.stdout + result.stderr


def test_a_runaway_test_is_ended_on_the_memory_limit(tmp_path: Path) -> None:
    source = (
        "import time\n\n"
        "def test_grow():\n"
        "    held = []\n"
        "    for _ in range(100):\n"
        "        held.append(bytearray(b'x' * 10_000_000))\n"
        "        time.sleep(0.05)\n"
    )
    result = _run_inner(tmp_path, source, rss_mb=300)
    assert result.returncode == 70
    assert "FATAL" in result.stderr
