"""What the terminal sends for real input, read as raw bytes (no app logic in between).

When the journey fails on a key or a click, these say whether the terminal ever sent it. Each click is recorded as
intended cell -> received cell in ``probe_clicks.txt`` under ``WXBRIEF_UAT_MACOS_OUT``. The terminals are known to land a
click one column off now and then (macos-26 Terminal.app, cause unexplained), so a one-column miss is recorded and
warned about, and only a bigger miss fails.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
import time
import warnings
from collections.abc import Iterator
from pathlib import Path

import pytest

from uat_macos import MacTerminal, unavailable_reason

APP = os.environ.get("WXBRIEF_UAT_MACOS", "")
PROBE = Path(__file__).resolve().parent / "scripts" / "rawprobe.py"
pytestmark = [
    pytest.mark.skipif(not APP, reason="set WXBRIEF_UAT_MACOS=Terminal or iTerm2 to drive a real terminal"),
    pytest.mark.skipif(bool(APP) and unavailable_reason() is not None, reason=str(unavailable_reason())),
]
CELLS = [(20, 8), (5, 11), (6, 11), (2, 2), (60, 20), (100, 30)]


@pytest.fixture(scope="module")
def probe() -> Iterator[MacTerminal]:
    out = Path(os.environ.get("WXBRIEF_UAT_MACOS_OUT") or tempfile.mkdtemp(prefix="uat-macos-out-"))
    with MacTerminal(
        [sys.executable, str(PROBE), "{dir}/raw.log"], 110, 36, app=APP, out_dir=out / f"{APP}-probe"
    ) as t:
        t.wait_for_text("probe ready", 60)
        yield t


def received(term: MacTerminal) -> bytes:
    log = term.dir / "raw.log"
    if not log.exists():
        return b""
    return b"".join(bytes.fromhex(line.split()[1]) for line in log.read_text().splitlines() if len(line.split()) == 2)


def test_escape_and_a_letter_arrive(probe: MacTerminal) -> None:
    probe.send_keys("escape")
    time.sleep(1)
    probe.send_keys("1")
    time.sleep(1)
    got = received(probe)
    assert b"\x1b" in got and b"1" in got, f"expected an ESC byte and a 1, the terminal sent {got!r}"


def test_clicks_land_on_the_intended_cell(probe: MacTerminal) -> None:
    lines, far = [], []
    for col, row in CELLS:
        before = len(received(probe))
        probe.click(col, row)
        time.sleep(0.8)
        new = received(probe)[before:]
        hits = re.findall(rb"\x1b\[<0;(\d+);(\d+)M", new)
        if not hits:
            lines.append(f"({col},{row}) -> nothing arrived: {new!r}")
            far.append(lines[-1])
            continue
        got = (int(hits[0][0]) - 1, int(hits[0][1]) - 1)
        lines.append(f"({col},{row}) -> {got}  dx={got[0] - col} dy={got[1] - row}")
        if got[1] != row or abs(got[0] - col) > 1:
            far.append(lines[-1])
        elif got != (col, row):
            warnings.warn(f"{APP}: click {lines[-1]} (off by one column)", stacklevel=1)
    (probe.out_dir / "probe_clicks.txt").write_text("\n".join(lines) + "\n")
    assert not far, "clicks missed by more than one column or any row:\n" + "\n".join(far)


def test_quit_probe(probe: MacTerminal) -> None:
    probe.send_keys("q")
    assert probe.wait_exit(20) == 0
