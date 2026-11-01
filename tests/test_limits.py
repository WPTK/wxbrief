"""The guards in conftest.py and pyproject.toml stop a runaway test instead of letting it exhaust the machine."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

CONFTEST = Path(__file__).with_name("conftest.py")

# Catastrophic backtracking is C code that holds the GIL, so no Python thread can interrupt it.
STUCK_IN_C = "import re\n\ndef test_stuck():\n    re.match(r'(a+)+$', 'a' * 64 + 'b')\n"


def _run_inner(
    tmp_path: Path, test_source: str, *args: str, rss_mb: int = 2048, **extra_env: str
) -> subprocess.CompletedProcess[str]:
    (tmp_path / "conftest.py").write_text(CONFTEST.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "test_inner.py").write_text(test_source, encoding="utf-8")
    env = {**os.environ, "WXBRIEF_TEST_RSS_MB": str(rss_mb), **extra_env}
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


def test_a_test_stuck_in_c_code_is_ended_by_the_backstop(tmp_path: Path) -> None:
    # The time limit is set too, as pyproject.toml sets it (a thread), but it cannot run while the regex holds the GIL.
    result = _run_inner(
        tmp_path, STUCK_IN_C, "--timeout", "2", "-o", "timeout_method=thread", WXBRIEF_TEST_HARD_TIMEOUT="3"
    )
    assert result.returncode != 0
    assert "Timeout (0:00:03)" in result.stderr
    assert "in test_stuck" in result.stderr


def test_a_module_stuck_in_c_code_while_importing_is_ended_by_the_collection_limit(tmp_path: Path) -> None:
    # No test runs: the hang is at import, which only the collection limit covers.
    result = _run_inner(
        tmp_path, "import re\n\nre.match(r'(a+)+$', 'a' * 64 + 'b')\n", WXBRIEF_TEST_COLLECT_TIMEOUT="3"
    )
    assert result.returncode != 0
    assert "Timeout (0:00:03)" in result.stderr
    assert "test_inner.py" in result.stderr


def test_the_collection_limit_is_cancelled_when_collection_finishes(tmp_path: Path) -> None:
    source = "import time\n\ndef test_slower_than_the_collection_limit():\n    time.sleep(4)\n"
    result = _run_inner(tmp_path, source, WXBRIEF_TEST_COLLECT_TIMEOUT="2")
    assert result.returncode == 0, result.stdout + result.stderr


def test_pytests_faulthandler_timeout_does_not_disarm_the_backstop(tmp_path: Path) -> None:
    result = _run_inner(tmp_path, STUCK_IN_C, "-o", "faulthandler_timeout=600", WXBRIEF_TEST_HARD_TIMEOUT="3")
    assert result.returncode != 0
    assert "Timeout (0:00:03)" in result.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="the commit limit is Windows only")
def test_one_huge_allocation_is_refused_on_windows(tmp_path: Path) -> None:
    source = "import pytest\n\ndef test_big():\n    with pytest.raises(MemoryError):\n        bytearray(1 << 30)\n"
    result = _run_inner(tmp_path, source, WXBRIEF_TEST_COMMIT_MB="512")
    assert result.returncode == 0, result.stdout + result.stderr
