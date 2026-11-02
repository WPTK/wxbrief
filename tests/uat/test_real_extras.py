"""L2 (CLI half), L6 (screen sizes) and L7 (the first ten inputs) as real-input checks, offline."""

from __future__ import annotations

import re
import subprocess

import pytest
from journey_kit import (
    Session,
    calm,
    needs_pty,
    program,
    program_env,
    quit_cleanly,
    stations_listed,
)
from uat_kit.styled import changed_rows, styled_rows

pytestmark = needs_pty

LEAKS = re.compile(r"Error|Exception|Traceback|https?://", re.IGNORECASE)
EMPTY = "No stations yet. Press a to add one."


def leaks(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if LEAKS.search(line)]


# -- L2: the words a person is shown for a failure, from the CLI -----------------------------------------------------


@pytest.mark.timeout(90)
@pytest.mark.xfail(strict=True, reason="#254: wxbrief get prints raw ConnectError text when the network is down")
def test_L2_get_with_the_network_blocked_shows_no_internals(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import os

    env = {
        **os.environ,
        **program_env(),
        "WXBRIEF_CACHE_DIR": str(tmp_path / "cache"),
        "HTTPS_PROXY": "http://127.0.0.1:9",
        "HTTP_PROXY": "http://127.0.0.1:9",
        "PYTHONUTF8": "1",
    }
    done = subprocess.run(
        [*program(), "--no-config", "get", "KLGA"], capture_output=True, text=True, timeout=60, env=env, stdin=subprocess.DEVNULL
    )
    shown = done.stdout + done.stderr
    assert done.returncode != 0 and shown.strip(), "a blocked network must be a plain failure with a message"
    assert not leaks(shown), f"internals in the message: {leaks(shown)}"
    assert "Traceback" not in shown


# -- L6: sizes -------------------------------------------------------------------------------------------------------

SIZES = [(80, 24), (100, 30), (120, 40), (300, 60)]
NUMERIC_CUT = re.compile(r"\d…|…\d")


def judge(name: str, screen, cols: int, rows: int) -> list[str]:  # type: ignore[no-untyped-def]
    """What is wrong with ``screen`` as drawn at cols x rows: clipped numbers, a lost title, a mostly empty body."""
    problems: list[str] = []
    body = screen.lines[:-3]
    for line in body:
        if NUMERIC_CUT.search(line):
            problems.append(f"a number is cut with an ellipsis: {line.strip()[:80]!r}")
            break
    blank = sum(1 for line in body if not line.strip(" ▊▎▏│┃"))
    if cols >= 100 and name == "grid" and body and blank / len(body) > 0.5:
        problems.append(f"{blank} of {len(body)} body rows are empty")
    right = [line[cols // 2 :] for line in body]
    if cols >= 100 and name in ("list", "detail", "grid") and sum(1 for line in right if not line.strip(" ▊▎▏│┃")) / len(body) > 0.5:
        problems.append("more than half of the right half is empty")
    if "Traceback" in screen.text:
        problems.append("a traceback")
    return problems


@pytest.mark.parametrize(
    "cols,rows",
    [*SIZES[:3], pytest.param(*SIZES[3], marks=pytest.mark.xfail(strict=True, reason="#261: a very wide terminal leaves most of the list, detail and grid screens empty"))],
)
def test_L6_every_screen_at_every_size_holds_together(session: Session, cols: int, rows: int) -> None:
    term = session.start(cols, rows, ["--demo"], ready=None)
    term.wait_for(lambda s: "demo data" in s, 45, "the demo screen")
    term.settle()
    found: dict[str, list[str]] = {}

    def look(name: str) -> None:
        screen = calm(term)
        bad = judge(name, screen, cols, rows)
        if bad:
            found[name] = bad

    look("list")
    term.send_keys("enter")
    look("detail")
    term.send_keys("escape")
    term.settle(0.3)
    term.send_keys("v")
    look("grid")
    term.send_keys("v")
    term.settle(0.3)
    for key, name in (("a", "add"), ("?", "help"), ("S", "settings"), ("T", "themes")):
        term.send_keys(key)
        look(name)
        term.send_keys("escape")
        term.settle(0.3)
    quit_cleanly(term)
    assert not found, chr(10).join(f"{k}: {v}" for k, v in found.items())


@pytest.mark.parametrize("cols,rows", SIZES)
def test_L6_the_empty_state_at_every_size(session: Session, tmp_path, cols: int, rows: int) -> None:  # type: ignore[no-untyped-def]
    term = session.start(cols, rows, root=tmp_path, ready=None)
    term.wait_for(lambda s: EMPTY in s, 45, "the empty state")
    screen = calm(term)
    assert not leaks(screen.text), leaks(screen.text)
    if cols >= 100:
        assert stations_listed(screen) == 0, screen.text
    quit_cleanly(term)


# -- L7: first run feel ----------------------------------------------------------------------------------------------


def test_L7_the_first_inputs_on_a_fresh_profile_each_change_the_screen(session: Session, tmp_path) -> None:  # type: ignore[no-untyped-def]
    term = session.start(120, 30, root=tmp_path)
    assert EMPTY in term.screen()
    inputs = [
        ("Enter", lambda: term.send_keys("enter")),
        ("Tab", lambda: term.send_keys("tab")),
        ("Down", lambda: term.send_keys("down")),
        ("click on the list", lambda: term.click(5, 3)),
        ("?", lambda: term.send_keys("?")),
        ("Esc", lambda: term.send_keys("escape")),
        ("a", lambda: term.send_keys("a")),
        ("Esc", lambda: term.send_keys("escape")),
        ("t", lambda: term.send_keys("t")),
        ("v", lambda: term.send_keys("v")),
    ]
    silent: list[str] = []
    for label, act in inputs:
        before = styled_rows(term)
        text_before = term.screen().text
        act()
        calm(term)
        if not changed_rows(before, styled_rows(term)) and term.screen().text == text_before:
            silent.append(label)
    assert term.alive()
    quit_cleanly(term)
    assert not silent, f"inputs that changed nothing on screen, not even a message: {silent}"
