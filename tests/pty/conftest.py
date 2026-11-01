"""Fixtures of the real-terminal suite. Every test gets a fresh program in a fresh pseudo-terminal, killed by PID."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from uat_kit import Screen, Terminal, unavailable_reason  # tests/ is on sys.path (rootdir import mode)

REASON = unavailable_reason()


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    here = __file__.rsplit("conftest.py", 1)[0]
    for item in items:
        if str(item.path).startswith(here):
            item.add_marker(pytest.mark.pty)
            item.add_marker(pytest.mark.timeout(90))
            if REASON:
                item.add_marker(pytest.mark.skip(reason=f"real-terminal layer unavailable: {REASON}"))


SRC_ENV = "WXBRIEF_PTY_SRC"  # a source tree to run instead of the installed one (checking another branch)
EXE_ENV = "WXBRIEF_PTY_EXE"  # the built program, for the post-build run; unset means python -m wxbrief


def launch(
    cols: int,
    rows: int,
    args: list[str] | None = None,
    *,
    demo: bool = True,
    env: dict[str, str] | None = None,
    prepare: Callable[[Path], None] | None = None,
) -> Terminal:
    exe = os.environ.get(EXE_ENV)
    argv = [exe] if exe else [sys.executable, "-m", "wxbrief"]
    if demo:
        argv += ["--demo"]
    argv += ["--config", "{dir}/config.toml", *(args or [])]
    extra = {"WXBRIEF_CACHE_DIR": "{dir}/cache", **(env or {})}
    if os.environ.get(SRC_ENV):
        extra["PYTHONPATH"] = os.environ[SRC_ENV]
    return Terminal(argv, cols, rows, env=extra, env_remove=("WXBRIEF_CONFIG",), prepare=prepare)


@pytest.fixture
def start() -> Iterator[Callable[..., Terminal]]:
    """``start(cols, rows, args)`` runs the program and waits until the station list is drawn."""
    made: list[Terminal] = []

    def factory(
        cols: int = 120,
        rows: int = 30,
        args: list[str] | None = None,
        *,
        demo: bool = True,
        env: dict[str, str] | None = None,
        prepare: Callable[[Path], None] | None = None,
        ready: str = "Stations",
    ) -> Terminal:
        term = launch(cols, rows, args, demo=demo, env=env, prepare=prepare)
        made.append(term)
        term.wait_for(lambda s: ready in s, 45, f"{ready!r} on screen")
        term.settle()
        return term

    yield factory
    for term in made:
        term.close()


__all__ = ["Screen"]
