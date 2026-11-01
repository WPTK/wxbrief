"""Shared pytest configuration."""

from __future__ import annotations

import faulthandler
import os
import sys
import threading
import time
import warnings
from collections.abc import Generator

import psutil
import pytest

# A runaway test must fail, not exhaust the machine. resource.setrlimit does not exist on Windows, so a watcher thread
# reads the process's own resident memory. Every xdist worker is its own pytest session and runs this too.
RSS_LIMIT_MB = int(os.environ.get("WXBRIEF_TEST_RSS_MB", "2048"))
RSS_POLL_SECONDS = 0.25

# Backstops for what the time limit (pytest-timeout's thread) and the watcher cannot stop. Both are Python threads, so
# neither runs while a test holds the GIL inside C code: a regex that backtracks for ever, one allocation of many GiB.
# faulthandler's timer runs on a thread of its own that needs no GIL. On Windows a job object makes the kernel refuse
# memory past the limit, so the test gets a MemoryError. 0 turns either off. Collection (importing the test modules)
# runs before any test, so it has a hard timeout of its own.
HARD_TIMEOUT_SECONDS = float(os.environ.get("WXBRIEF_TEST_HARD_TIMEOUT", "300"))
COLLECT_TIMEOUT_SECONDS = float(os.environ.get("WXBRIEF_TEST_COLLECT_TIMEOUT", "300"))
COMMIT_LIMIT_MB = int(os.environ.get("WXBRIEF_TEST_COMMIT_MB", "4096"))

_stderr_fd = pytest.StashKey[int]()


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


def _limit_commit(limit_bytes: int, *, warn: bool) -> None:
    """Make Windows refuse this process, and any it starts, memory past ``limit_bytes``.

    Windows has no overcommit: a process that commits all it can makes every other program's allocations fail instead of
    being killed. Linux and macOS overcommit and end a process under memory pressure, so nothing is done there.
    """
    if sys.platform != "win32":
        return
    import ctypes
    from ctypes import wintypes

    class Basic(ctypes.Structure):  # JOBOBJECT_BASIC_LIMIT_INFORMATION
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class Extended(ctypes.Structure):  # JOBOBJECT_EXTENDED_LIMIT_INFORMATION
        _fields_ = [
            ("Basic", Basic),
            ("IoInfo", ctypes.c_ulonglong * 6),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]

    limits = Extended()
    limits.Basic.LimitFlags = 0x100  # JOB_OBJECT_LIMIT_PROCESS_MEMORY
    limits.ProcessMemoryLimit = limit_bytes
    job = kernel32.CreateJobObjectW(None, None)  # never closed: the limit lasts as long as this process
    applied = (
        job
        and kernel32.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits))  # 9: extended limits
        and kernel32.AssignProcessToJobObject(job, kernel32.GetCurrentProcess())
    )
    if not applied and warn:
        warnings.warn(f"the commit limit was not applied (job object error {ctypes.get_last_error()})", stacklevel=2)


def pytest_configure(config: pytest.Config) -> None:
    # faulthandler writes to a descriptor of its own: pytest's capture swaps fd 2 while a test runs.
    assert sys.__stderr__ is not None
    fd = os.dup(sys.__stderr__.fileno())
    config.add_cleanup(lambda: os.close(fd))
    config.stash[_stderr_fd] = fd
    if COMMIT_LIMIT_MB > 0:
        # Every xdist worker applies the limit; only the controller says when it could not, not once per worker.
        _limit_commit(COMMIT_LIMIT_MB * 2**20, warn=not hasattr(config, "workerinput"))
    # Started here, not in a fixture, so that collection is inside the memory limit too.
    threading.Thread(target=_watch_rss, args=(config, RSS_LIMIT_MB * 2**20), daemon=True, name="rss-watch").start()


@pytest.hookimpl(wrapper=True)
def pytest_collection(session: pytest.Session) -> Generator[None, object, object]:
    if COLLECT_TIMEOUT_SECONDS <= 0:
        return (yield)
    faulthandler.dump_traceback_later(COLLECT_TIMEOUT_SECONDS, exit=True, file=session.config.stash[_stderr_fd])
    try:
        return (yield)
    finally:
        faulthandler.cancel_dump_traceback_later()  # the per-test timer is armed after this, by pytest_runtest_protocol


@pytest.hookimpl(wrapper=True, trylast=True)  # pytest's faulthandler_timeout arms the same timer; the later call wins
def pytest_runtest_protocol(item: pytest.Item) -> Generator[None, object, object]:
    if HARD_TIMEOUT_SECONDS <= 0:
        return (yield)
    faulthandler.dump_traceback_later(HARD_TIMEOUT_SECONDS, exit=True, file=item.config.stash[_stderr_fd])
    try:
        return (yield)
    finally:
        faulthandler.cancel_dump_traceback_later()


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
