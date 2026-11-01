"""Journeys through the real program in a real pseudo-terminal, with the bytes a terminal sends.

What the pilot UAT cannot see: the SGR mouse reports (and the pointer motion before every click), the input parser,
the resize signal and the exit code of the real process. Assertions are on the rendered screen only.
"""

from __future__ import annotations

import re
from collections.abc import Callable

import pytest
from uat_kit import Screen, Terminal

Start = Callable[..., Terminal]
STATIONS = ["KDEN", "EGLL", "ETHB", "UUEE", "YSSY", "RJTT", "VIDP", "SBGR", "CYYZ", "NZSP"]


def position(screen: Screen) -> tuple[int, int] | None:
    """The 'N/M' selection counter of the status bar, or None."""
    for line in screen.lines[-3:]:
        found = re.match(r"\s*(\d+)/(\d+)\s", line)
        if found:
            return int(found[1]), int(found[2])
    return None


def footer(screen: Screen) -> str:
    return screen.lines[-1]


def heading_row(screen: Screen, title: str) -> int | None:
    """Row of a detail-pane section title (a line that is only the title), above the status bar."""
    for row, line in enumerate(layout(screen)[:-2]):
        pane = line.partition("▎")[2].strip() if "▎" in line else line.strip()
        if pane == title:
            return row
    return None


def detail_station(screen: Screen) -> str | None:
    """The station the detail pane is about: the id that starts the header line on the right of the list."""
    for line in screen.lines[:4]:
        pane = line.partition("▎")[2].strip() if "▎" in line else ""
        found = re.match(r"([A-Z0-9]{4})\s{2}\S", pane)
        if found:
            return found[1]
    return None


def row_of(screen: Screen, station: str, left_of: int = 40) -> tuple[int, int]:
    """Cell (col, row) of a station id in the list (or the card header in the grid)."""
    for row, line in enumerate(screen.lines[:-2]):
        col = line.find(station)
        if 0 <= col < left_of or (left_of > 100 and col >= 0):
            return col, row
    raise AssertionError(f"{station} not on screen:\n{screen.text}")


def layout(screen: Screen) -> list[str]:
    """The screen without toasts (bottom-right, they time out by design) and scrollbar blocks."""
    return [re.sub(r"[▁-█]", "", line.partition("▌")[0]).rstrip() for line in screen.lines]


def assert_stable(term: Terminal, seconds: float = 2.0, every: float = 0.5) -> Screen:
    """The screen does not change for ``seconds``: no layout jumping, no selection reverting."""
    first = term.screen()
    t = 0.0
    while t < seconds:
        term.hold(every)
        t += every
        now = term.screen()
        assert layout(now) == layout(first), f"screen changed after {t:g} s.\nBEFORE:\n{first.text}\nAFTER:\n{now.text}"
    return first


# -- startup, keys, round trips ---------------------------------------------------------------------------------------


def test_startup_shows_list_with_first_station_selected(start: Start) -> None:
    term = start()
    screen = term.screen()
    for station in STATIONS:
        assert station in screen
    assert position(screen) == (1, 10)
    assert detail_station(screen) == "KDEN"


def test_arrow_keys_move_the_selection(start: Start) -> None:
    term = start()
    term.send_keys("down", "down")
    screen = term.wait_for(lambda s: position(s) == (3, 10), 10, "3/10 after two Down keys")
    assert detail_station(screen) == "ETHB"
    term.send_keys("up")
    term.wait_for(lambda s: position(s) == (2, 10), 10, "2/10 after Up")


def test_click_on_third_row_selects_it_and_it_sticks(start: Start) -> None:
    term = start()
    col, row = row_of(term.screen(), "ETHB")
    term.click(col, row)
    term.wait_for(lambda s: position(s) == (3, 10) and detail_station(s) == "ETHB", 10, "ETHB selected by the click")
    term.hold(2.0)
    screen = term.screen()
    assert position(screen) == (3, 10), screen.text
    assert detail_station(screen) == "ETHB", screen.text
    assert_stable(term)


def test_click_layout_stays_stable_for_two_seconds(start: Start) -> None:
    term = start()
    term.click(*row_of(term.screen(), "UUEE"))
    term.wait_for(lambda s: position(s) == (4, 10), 10, "UUEE selected")
    snapshots = []
    for _ in range(5):
        term.hold(0.5)
        snapshots.append(term.screen())
    assert all(layout(s) == layout(snapshots[0]) for s in snapshots), "\n\n".join("\n".join(s) for s in snapshots[:2])
    assert position(term.screen()) == (4, 10)


def test_click_then_each_row_in_turn(start: Start) -> None:
    term = start()
    for index in (4, 1, 6):  # a click, then a click elsewhere: the second must not be swallowed
        term.click(*row_of(term.screen(), STATIONS[index]))
        term.wait_for(lambda s, i=index: position(s) == (i + 1, 10), 10, f"{STATIONS[index]} selected")
        term.hold(0.5)
        assert position(term.screen()) == (index + 1, 10), term.screen_text()


def test_grid_click_selects_a_card_and_it_sticks(start: Start) -> None:
    term = start()
    term.send_keys("v")
    term.wait_for(lambda s: "Grid layout" in s or (heading_row(s, "Raw") is None and "╭" in s.text), 10, "grid")
    term.settle()
    term.click(*row_of(term.screen(), "RJTT", left_of=200))
    term.wait_for(lambda s: position(s) == (6, 10), 10, "RJTT selected in the grid")
    term.hold(2.0)
    screen = term.screen()
    assert position(screen) == (6, 10), screen.text
    assert "┏" in screen.text  # the heavy border marks the selected card
    assert_stable(term)


@pytest.mark.parametrize("focus", ["list", "detail", "after_click"])
def test_keys_1_2_3_scroll_the_sections_into_view(start: Start, focus: str) -> None:
    term = start()
    if focus == "detail":
        term.send_keys("enter")
        term.wait_for(lambda s: "esc Back" in footer(s), 10, "focus in the detail pane")
    elif focus == "after_click":
        term.click(*row_of(term.screen(), "ETHB"))
        term.wait_for(lambda s: position(s) == (3, 10), 10, "ETHB selected")
    for key, title in (("3", "Forecast (TAF)"), ("2", "Decoded"), ("1", "Raw")):
        before = layout(term.screen())
        term.send_keys(key)
        term.wait_for(
            lambda s, t=title, b=before: heading_row(s, t) is not None and layout(s) != b,
            10,
            f"key {key} to change the screen and show {title!r}",
        )
        if key == "1":
            assert (heading_row(term.screen(), "Raw") or 99) <= 3, term.screen_text()
    assert position(term.screen()) is not None


def test_enter_and_escape_round_trip(start: Start) -> None:
    term = start()
    before = footer(term.screen())
    assert "d Remove" in before
    term.send_keys("enter")
    inside = term.wait_for(lambda s: "esc Back" in footer(s), 10, "the detail footer")
    assert "1 Raw" in footer(inside)
    term.send_keys("escape")
    after = term.wait_for(lambda s: "d Remove" in footer(s), 10, "the list footer again")
    assert position(after) == (1, 10)


def test_add_dialog_opens_and_closes(start: Start) -> None:
    term = start()
    term.send_keys("a")
    term.wait_for(lambda s: "Add station" in s, 10, "the add dialog")
    term.send_keys("escape")
    term.wait_for(lambda s: "Add station" not in s, 10, "the add dialog closed")
    assert position(term.screen()) == (1, 10)


def test_help_opens_and_closes(start: Start) -> None:
    term = start()
    term.send_keys("?")
    term.wait_for(lambda s: "wxbrief keys" in s, 10, "help")
    term.send_keys("escape")
    term.wait_for(lambda s: "wxbrief keys" not in s, 10, "help closed")


@pytest.mark.parametrize("layout", ["list", "grid"])
def test_resize_keeps_the_selection(start: Start, layout: str) -> None:
    term = start(120, 30)
    if layout == "grid":
        term.send_keys("v")
        term.wait_for(lambda s: "┏" in s.text or "╭" in s.text, 10, "grid")
    term.send_keys("right", "right") if layout == "grid" else term.send_keys("down", "down")
    term.wait_for(lambda s: position(s) == (3, 10), 10, "ETHB selected")
    for cols, rows in ((60, 16), (120, 30)):
        term.resize(cols, rows)
        term.wait_for(lambda s, r=rows: len(s.lines) == r and position(s) is not None, 10, f"{cols}x{rows} drawn")
        term.settle()
        assert position(term.screen()) == (3, 10), term.screen_text()
    assert_stable(term, 1.0)


def test_q_exits_cleanly(start: Start) -> None:
    term = start()
    term.send_keys("q")
    assert term.wait_exit(15) == 0, term.screen_text()


def test_a_dead_network_does_not_matter_in_demo(start: Start) -> None:
    term = start()
    term.send_keys("r")
    term.hold(1.0)
    assert "offline" not in term.screen().text.lower().replace("no network", "")


# -- regression tests for defects found in the 0.3.0 release (#221 #222 #225), fixed in #228 -------------------------------


def test_click_keeps_focus_on_the_list(start: Start) -> None:
    term = start()
    term.click(*row_of(term.screen(), "ETHB"))
    term.wait_for(lambda s: position(s) == (3, 10), 10, "ETHB selected")
    term.hold(0.5)
    assert "d Remove" in footer(term.screen()), footer(term.screen())
    assert "esc Back" not in footer(term.screen())


def test_repeated_refresh_in_demo_shows_one_toast(start: Start) -> None:
    term = start()
    for _ in range(3):
        term.send_keys("r")
    screen = term.settle(0.3)
    assert sum(line.count("Polling is off") for line in screen.lines) <= 1, screen.text


def test_demo_mode_is_visible_after_the_toast_has_gone(start: Start) -> None:
    term = start()
    term.hold(8.0)
    assert "demo" in term.screen().text.lower(), term.screen_text()
