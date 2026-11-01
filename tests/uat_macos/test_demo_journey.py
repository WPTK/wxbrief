"""wxbrief demo mode in a real Terminal.app or iTerm2 window: launch, wait for text, keys 1/2/3, click, resize, escape, quit.

Runs only when ``WXBRIEF_UAT_MACOS`` names the app (``Terminal`` or ``iTerm2``) on a Mac set up by
``scripts/grant_tcc.sh``; ``.github/workflows/uat-macos.yml`` does that. Screenshots and screen text go to
``WXBRIEF_UAT_MACOS_OUT`` (default: a temp directory). The steps share one window and run in file order.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator

import pytest

from uat_macos import MacTerminal, unavailable_reason
from uat_macos.conftest import stop_program

APP = os.environ.get("WXBRIEF_UAT_MACOS", "")
pytestmark = [
    pytest.mark.skipif(not APP, reason="set WXBRIEF_UAT_MACOS=Terminal or iTerm2 to drive a real terminal"),
    pytest.mark.skipif(bool(APP) and unavailable_reason() is not None, reason=str(unavailable_reason())),
]


@pytest.fixture(scope="module")
def term(session: MacTerminal) -> Iterator[MacTerminal]:
    session.run([sys.executable, "-m", "wxbrief", "--demo", "--no-config"], {"WXBRIEF_CACHE_DIR": "{dir}/cache"})
    yield session
    stop_program(session)


@pytest.fixture(autouse=True)
def _evidence(request: pytest.FixtureRequest, term: MacTerminal) -> Iterator[None]:
    yield
    if term.alive():  # a screenshot and the screen text after every step, pass or fail
        term.screenshot(request.node.name)


def detail_first_line(term: MacTerminal) -> str:
    """The first text row of the detail pane (right of the station list)."""
    lines = term.screen().lines
    return lines[1].split("▎", 1)[-1].strip() if "▎" in lines[1] else ""


def test_1_launch_and_wait_for_text(term: MacTerminal) -> None:
    screen = term.wait_for_text("Stations (10)", 60)
    assert "KDEN" in screen and "demo data, not live" in term.wait_for_text("demo data", 10)
    assert (term.cols, term.rows) == (110, 36)


def test_2_keys_1_2_3_move_between_sections(term: MacTerminal) -> None:
    term.send_keys("1")
    term.wait_for(lambda s: detail_first_line(term) == "Raw", 15, "section 1 (Raw) at the top of the detail pane")
    term.send_keys("2")
    term.wait_for(lambda s: detail_first_line(term) == "Decoded", 15, "section 2 (Decoded) at the top")
    term.send_keys("3")
    # key 3 moves focus into the forecast: the footer offers "esc Back" and the TAF detail is on screen
    term.wait_for(lambda s: "esc Back" in s.lines[-1] and "Prevailing" in s, 15, "focus in the forecast after key 3")


def test_3_click_a_station(term: MacTerminal) -> None:
    term.click_text("EGLL")
    term.wait_for_text("London/Heathrow", 15)
    assert "2/10" in term.settle().text


def test_4_resize(term: MacTerminal) -> None:
    term.resize(90, 30)
    screen = term.settle()
    assert (term.cols, term.rows) == (90, 30)
    assert "Stations" in screen and "EGLL" in screen
    term.resize(110, 36)
    assert "Stations" in term.settle()


def test_5_escape_goes_back(term: MacTerminal) -> None:
    term.send_keys("3")
    term.wait_for(lambda s: "esc Back" in s.lines[-1], 15, "focus in the forecast after key 3")
    term.send_keys("escape")
    term.wait_for(lambda s: "esc Back" not in s.lines[-1], 15, "the station list focused again after escape")


def test_6_quit(term: MacTerminal) -> None:
    term.send_keys("q")
    assert term.wait_exit(20) == 0
