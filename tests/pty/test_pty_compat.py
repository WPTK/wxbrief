"""Terminal compatibility in a real pseudo-terminal: colour environment, glyph fallback, minimum size, clean exit.

Windows Terminal rendering specifics, sixel and real tmux/SSH sessions are not covered here (see docs/development.md).
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from uat_kit import Terminal

Start = Callable[..., Terminal]
README = Path(__file__).resolve().parents[2] / "README.md"


def all_cells(term: Terminal) -> list[object]:
    return term._run(term._t.cells(0, 0, term.cols, term.rows))


def is_grey(colour: str) -> bool:
    found = re.fullmatch(r"#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})", colour or "")
    return colour in ("", "default") or bool(found and found[1] == found[2] == found[3])


def test_no_color_draws_no_colour(start: Start) -> None:
    term = start(env={"NO_COLOR": "1"})
    coloured = {(c.fg, c.bg) for c in all_cells(term) if not (is_grey(c.fg) and is_grey(c.bg))}
    assert not coloured, f"NO_COLOR is set but the screen uses colours: {sorted(coloured)[:5]}"


@pytest.mark.parametrize(
    ("term_name", "colorterm"),
    [("xterm-256color", "truecolor"), ("xterm-256color", ""), ("xterm", ""), ("linux", ""), ("vt100", "")],
    ids=["truecolor", "256-colour", "xterm-16", "linux-16", "vt100"],
)
def test_colour_environments_start_and_quit(start: Start, term_name: str, colorterm: str) -> None:
    term = start(env={"TERM": term_name, "COLORTERM": colorterm})
    assert "KDEN" in term.screen()
    term.send_keys("3")
    term.wait_for_text("Forecast (TAF)", 10)
    term.send_keys("q")
    assert term.wait_exit(15) == 0


@pytest.mark.xfail(strict=True, reason="#234: --glyphs ascii still draws block characters")
def test_ascii_glyph_set_draws_only_ascii_symbols(start: Start) -> None:
    term = start(args=["--glyphs", "ascii"])
    odd = {ch for line in term.screen().lines for ch in line if ord(ch) > 127 and not ch.isalpha() and ch != "°"}
    assert not odd, f"--glyphs ascii draws non-ASCII symbols: {sorted(odd)}"


def test_too_small_terminal_says_so_and_recovers(start: Start) -> None:
    term = start()
    term.resize(40, 10)
    small = term.settle(0.6)
    assert "larger" in small.text.lower() or "too small" in small.text.lower(), small.text
    term.resize(120, 30)
    term.wait_for(lambda s: "Stations" in s, 10, "the app again after growing the window")


@pytest.mark.xfail(
    sys.platform == "win32", strict=True, reason="#235: exit leaves focus reporting on (seen on Windows only; clean on Linux and macOS)"
)
def test_exit_leaves_the_terminal_clean(start: Start) -> None:
    term = start()
    term.send_keys("q")
    assert term.wait_exit(15) == 0
    state = term.state()
    leftovers = {
        "mouse tracking": state.mouse_mode != "none",
        "alternate screen": state.modes.get("alternate_screen"),
        "hidden cursor": not state.modes.get("cursor_visible", True),
        "bracketed paste": state.modes.get("bracketed_paste"),
        "focus reporting": state.modes.get("focus_events"),
    }
    assert not any(leftovers.values()), f"left on after exit: {[k for k, v in leftovers.items() if v]}"


def test_help_lists_every_readme_key(start: Start) -> None:
    table = README.read_text(encoding="utf-8").split("| Key | Does |")[1].split("\n\n")[0]
    keys = {k for row in table.splitlines()[2:] for k in re.findall(r"`([^`]+)`", row.split("|")[1])}
    term = start(120, 50)
    term.send_keys("?")
    help_text = term.wait_for_text("wxbrief keys", 10).text
    missing = [k for k in sorted(keys) if not re.search(rf"(?<![\w]){re.escape(k)}(?![\w])", help_text)]
    assert not missing, f"README keys the help screen does not list: {missing}"
