"""Shared pytest configuration."""

from __future__ import annotations

import os
import sys
import threading
import time

import psutil
import pytest

# A runaway test must fail, not exhaust the machine. resource.setrlimit does not exist on Windows, so a watcher thread
# reads the process's own resident memory. Every xdist worker is its own pytest session and runs this too.
RSS_LIMIT_MB = int(os.environ.get("WXBRIEF_TEST_RSS_MB", "2048"))
RSS_POLL_SECONDS = 0.25


def _say(config: pytest.Config, text: str) -> None:
    """Write past pytest's output capture, which would otherwise swallow the message of a process about to die."""
    capman = config.pluginmanager.getplugin("capturemanager")
    try:
        with capman.global_and_fixture_disabled():
            sys.stderr.write(text)
            sys.stderr.flush()
    except Exception:
        sys.stderr.write(text)


def _watch_rss(config: pytest.Config, limit_bytes: int) -> None:
    process = psutil.Process()
    while True:
        rss = process.memory_info().rss
        if rss > limit_bytes:
            _say(
                config,
                f"\nFATAL: test process {process.pid} is using {rss / 2**20:.0f} MB, over the "
                f"{limit_bytes // 2**20} MB limit (WXBRIEF_TEST_RSS_MB). Ending it.\n",
            )
            os._exit(70)  # a hard exit: the runaway code may be ignoring everything softer
        time.sleep(RSS_POLL_SECONDS)


@pytest.fixture(scope="session", autouse=True)
def _memory_limit(pytestconfig: pytest.Config) -> None:
    threading.Thread(
        target=_watch_rss,
        args=(
            pytestconfig,
            RSS_LIMIT_MB * 2**20,
        ),
        daemon=True,
        name="rss-watch",
    ).start()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--update-goldens",
        action="store_true",
        default=False,
        help="rewrite tests/fixtures/reports/**/*.golden.json from the current decoder output (review the diff!)",
    )


@pytest.fixture
def update_goldens(request: pytest.FixtureRequest) -> bool:
    return bool(request.config.getoption("--update-goldens"))
