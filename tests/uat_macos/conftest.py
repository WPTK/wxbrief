"""One terminal window per pytest session: iTerm2 is launched once per job, then each module runs its program in it."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from uat_macos import MacTerminal, unavailable_reason

APP = os.environ.get("WXBRIEF_UAT_MACOS", "")


def stop_program(term: MacTerminal) -> None:
    """Make sure the module's program has ended before the next module starts its own."""
    if term.alive():
        term.send_keys("q")
        try:
            term.wait_exit(5)
        except AssertionError:
            term.send_keys("ctrl+c")
            term.wait_exit(10)


@pytest.fixture(scope="session")
def session() -> Iterator[MacTerminal]:
    if not APP or unavailable_reason() is not None:
        pytest.skip("set WXBRIEF_UAT_MACOS=Terminal or iTerm2 on a Mac with cliclick and pyobjc")
    out = Path(os.environ.get("WXBRIEF_UAT_MACOS_OUT") or tempfile.mkdtemp(prefix="uat-macos-out-"))
    with MacTerminal(110, 36, app=APP, out_dir=out / APP) as t:
        yield t
