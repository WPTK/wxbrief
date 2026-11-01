"""The input inventory: every key binding and every clickable in the source has a real-terminal test, enforced.

``KEY_SCENARIOS`` and ``CLICKABLES`` are the registry. Each key scenario names the (scope, key) pairs it covers and
drives the real program with the bytes a terminal sends; the check is an observable change on the rendered screen (a
changed layout, a toast, a dialog). The meta-tests scan the source for ``bind("key", ...)`` and for clickable widgets
and fail when one has no scenario, and fail on a README key with no scenario. A binding that is advertised and does
nothing fails its scenario.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
from uat_kit import Screen, Terminal

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "wxbrief"
Start = Callable[..., Terminal]
Check = Callable[[Screen, Screen], bool]

NAMES = {"question_mark": "?"}
BAR = "▌"


def layout(screen: Screen) -> list[str]:
    return [re.sub(r"[▁-█]", "", line.partition(BAR)[0]).rstrip() for line in screen.lines]


def toasts(screen: Screen) -> str:
    return " ".join(line.partition(BAR)[2].strip() for line in screen.lines if BAR in line)


def changed(before: Screen, after: Screen) -> bool:
    return layout(before) != layout(after) or toasts(before) != toasts(after)


def toast_changed(before: Screen, after: Screen) -> bool:
    return toasts(after) != toasts(before)


def opened(text: str) -> Check:
    return lambda before, after: text in after and text not in before


def closed(text: str) -> Check:
    return lambda before, after: text in before and text not in after


def has(text: str) -> Check:
    return lambda before, after: text in after.text


def style_only(before: Screen, after: Screen) -> bool:  # replaced by a cell-style comparison in test_key
    return True


def list_footer(before: Screen, after: Screen) -> bool:
    return "d Remove" in after.lines[-1]


def shows(title: str) -> Check:
    return lambda before, after: changed(before, after) and title in after.text


@dataclass
class Key:
    id: str
    covers: list[tuple[str, str]]  # (source file stem, key)
    setup: list[str]
    key: str
    check: Check = changed
    note: str = ""


KEY_SCENARIOS: list[Key] = [
    Key("q-quit", [("app", "q"), ("too_small", "q")], [], "q", note="exit code asserted in test_q_exits_cleanly"),
    Key("T-theme-picker", [("app", "T")], [], "T", opened("cockpit-night")),
    Key("t-theme", [("app", "t")], [], "t", note="colour only; asserted by test_t_changes_colours"),
    Key("g-glyphs", [("app", "g")], [], "g"),
    Key("u-units", [("app", "u")], [], "u"),
    Key("z-time", [("app", "z")], [], "z"),
    Key("r-refresh", [("base", "r")], [], "r", toast_changed),
    Key("help-open", [("base", "question_mark")], [], "?", opened("wxbrief keys")),
    Key("a-add", [("briefing", "a"), ("station_list", "a")], [], "a", opened("Add station")),
    Key("d-remove", [("briefing", "d"), ("station_list", "d")], [], "d", has("Stations (9)")),
    Key("v-grid", [("briefing", "v"), ("station_list", "v")], [], "v", has("╭")),
    Key("p-paste", [("briefing", "p")], [], "p"),
    Key("c-copy", [("briefing", "c")], [], "c", toast_changed),
    Key("C-copy-both", [("briefing", "C")], [], "C", toast_changed),
    Key("y-copy-raw", [("briefing", "y")], [], "y", toast_changed),
    Key("S-settings", [("briefing", "S")], [], "S"),
    Key("j-next", [("briefing", "j")], [], "j", has("2/10")),
    Key("k-previous", [("briefing", "k")], [], "k", has("10/10")),
    Key("1-raw", [("briefing", "1"), ("detail", "1")], ["3"], "1", shows("Raw")),
    Key("2-decoded", [("briefing", "2"), ("detail", "2")], ["3"], "2", shows("Decoded")),
    Key("3-taf", [("briefing", "3"), ("detail", "3")], [], "3", shows("Forecast (TAF)")),
    Key("escape-back", [("briefing", "escape")], ["enter"], "escape", list_footer),
    Key("enter-open", [("station_grid", "enter")], ["v"], "enter", has("esc Back")),
    Key("detail-c", [("detail", "c")], ["enter"], "c", toast_changed),
    Key("detail-a", [("detail", "a")], ["enter"], "a", opened("Add station")),
    Key("timeline-left", [("detail", "left"), ("taf_timeline", "left")], ["enter", "3", "right"], "left"),
    Key("timeline-right", [("detail", "right"), ("taf_timeline", "right")], ["enter", "3"], "right"),
    Key("timeline-home", [("taf_timeline", "home")], ["enter", "3", "right", "right"], "home"),
    Key("timeline-end", [("taf_timeline", "end")], ["enter", "3"], "end"),
    Key("grid-right", [("station_grid", "right")], ["v"], "right", has("2/10")),
    Key("grid-left", [("station_grid", "left")], ["v", "right"], "left", has("1/10")),
    Key("grid-down", [("station_grid", "down")], ["v"], "down", has("4/10")),
    Key("grid-up", [("station_grid", "up")], ["v", "down"], "up", has("1/10")),
    Key("grid-a", [("station_grid", "a")], ["v"], "a", opened("Add station")),
    Key("grid-d", [("station_grid", "d")], ["v"], "d", has("Stations (9)")),
    Key("grid-v", [("station_grid", "v")], ["v"], "v", lambda b, a: "╭" not in a.text),
    Key("add-escape", [("add_station", "escape")], ["a"], "escape", closed("Add station")),
    Key("add-down", [("add_station", "down")], ["a", "Gatwick"], "down", style_only, note="highlight is colour only"),
    Key("help-escape", [("help", "escape")], ["?"], "escape", closed("wxbrief keys")),
    Key("help-qmark", [("help", "question_mark")], ["?"], "?", closed("wxbrief keys")),
    Key("settings-escape", [("settings", "escape")], ["S"], "escape", list_footer),
    Key("settings-S", [("settings", "S")], ["S"], "S", list_footer),
    Key("picker-escape", [("theme_picker", "escape")], ["T"], "escape", closed("cockpit-night")),
    Key("paste-escape", [("paste", "escape")], ["p"], "escape", list_footer),
    Key(
        "paste-f2",
        [("paste", "f2")],
        ["p", "METAR KDEN 131453Z 06007KT 3/4SM BR OVC003 09/08 A3001"],
        "f2",
        toast_changed,
    ),
    Key("paste-c", [("paste", "c")], ["p", "METAR KDEN 131453Z 06007KT 3/4SM BR OVC003 09/08 A3001", "escape"], "c"),
    Key("station-y", [("station_detail", "y")], ["v", "enter"], "y", toast_changed),
    Key("station-C", [("station_detail", "C")], ["v", "enter"], "C", toast_changed),
    Key("station-escape", [("station_detail", "escape")], ["v", "enter"], "escape", list_footer),
]


@pytest.mark.parametrize("scn", KEY_SCENARIOS, ids=lambda s: s.id)
def test_key(start: Start, scn: Key) -> None:
    if scn.id in ("q-quit", "t-theme"):
        pytest.skip(scn.note)
    term = start()
    for step in scn.setup:
        term.send_keys(step)
        term.settle(0.3)
    before = term.screen()
    cells_before = repr(term._run(term._t.cells(0, 0, term.cols, term.rows)))
    term.send_keys(scn.key)
    term.settle(0.5)
    after = term.screen()
    if scn.check is style_only:
        assert repr(term._run(term._t.cells(0, 0, term.cols, term.rows))) != cells_before, f"{scn.id}: no style change"
        return
    assert scn.check(before, after), (
        f"key {scn.key!r} ({scn.id}) did nothing observable.\nBEFORE:\n{before.text}\nAFTER:\n{after.text}"
    )


def test_t_changes_colours(start: Start) -> None:
    term = start()
    before = repr(term._run(term._t.cells(0, 5, 30, 1)))
    term.send_keys("t")
    term.settle(0.5)
    assert repr(term._run(term._t.cells(0, 5, 30, 1))) != before, "key t changed no cell style"


# -- clickables -------------------------------------------------------------------------------------------------------

# (source file stem, kind) -> the test that clicks it, or a reason it is display only.
CLICKABLES: dict[tuple[str, str], str] = {
    ("station_list", "OptionList"): "test_pty_journeys.py::test_click_on_third_row_selects_it_and_it_sticks",
    ("station_list", "on_click"): "test_pty_journeys.py::test_click_keeps_focus_on_the_list",
    ("station_card", "on_click"): "test_pty_journeys.py::test_grid_click_selects_a_card_and_it_sticks",
    ("taf_timeline", "on_click"): "test_pty_inventory.py::test_click_timeline_hour",
    ("add_station", "OptionList"): "test_pty_inventory.py::test_click_add_station_result",
    ("settings", "OptionList"): "test_pty_inventory.py::test_click_settings_option",
    ("theme_picker", "OptionList"): "test_pty_inventory.py::test_click_theme_option",
    ("detail", "Collapsible"): "test_pty_inventory.py::test_click_forecast_groups_expander",
    ("detail", "DataTable"): "display only: DecodedTable rows are read-only and have no action",
}


def test_click_timeline_hour(start: Start) -> None:
    term = start()
    term.send_keys("enter", "3")
    term.settle(0.4)
    before = term.screen()
    row = next(r for r, line in enumerate(before.lines) if re.search(r"\b06\s+09\s+12", line))
    term.click(before.lines[row].index("12") + 1, row + 1)
    after = term.settle(0.5)
    assert layout(after) != layout(before), f"click on the timeline did nothing:\n{after.text}"


def test_click_add_station_result(start: Start) -> None:
    term = start()
    term.send_keys("a", "Gatwick")
    term.wait_for(lambda s: "EGKK" in s.text, 10, "a Gatwick result")
    term.settle(0.5)
    term.click_text("EGKK")
    term.wait_for(lambda s: "Add station" not in s and "Stations (11)" in s, 10, "EGKK added by the click")


def test_click_settings_option(start: Start) -> None:
    term = start()
    term.send_keys("S")
    before = term.settle(0.6)
    row = next(r for r, line in enumerate(before.lines) if "Units" in line)
    term.click(before.lines[row].index("Units") + 2, row)
    after = term.settle(0.5)
    assert layout(after) != layout(before), f"click on a settings option did nothing:\n{after.text}"


def test_click_theme_option(start: Start) -> None:
    term = start()
    term.send_keys("T")
    term.wait_for_text("phosphor-green", 10)
    term.settle(0.4)
    term.click_text("phosphor-green")
    term.wait_for(lambda s: "phosphor-green" not in s.text, 10, "the picker closed by the click")


def test_click_forecast_groups_expander(start: Start) -> None:
    term = start()
    term.send_keys("enter", "3")
    term.wait_for_text("All forecast groups", 10)
    before = term.settle(0.4)
    term.click_text("All forecast groups")
    after = term.settle(0.5)
    assert layout(after) != layout(before), after.text


# -- the meta-tests ---------------------------------------------------------------------------------------------------


def source_bindings() -> set[tuple[str, str]]:
    found = set()
    for path in SRC.rglob("*.py"):
        for key in re.findall(r'\bbind\(\s*"([^"]+)"', path.read_text(encoding="utf-8")):
            found.add((path.stem, key))
    return found


def source_clickables() -> set[tuple[str, str]]:
    found = set()
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "def on_click" in text:
            found.add((path.stem, "on_click"))
        for kind in ("OptionList", "Collapsible", "DataTable", "Button"):
            if re.search(rf"(\byield {kind}\(|class \w+\({kind}[\[\)]|\bwith {kind}\()", text):
                found.add((path.stem, kind))
    return found


def test_every_binding_in_the_source_has_a_scenario() -> None:
    covered = {pair for scn in KEY_SCENARIOS for pair in scn.covers}
    assert not sorted(source_bindings() - covered), f"bindings with no test: {sorted(source_bindings() - covered)}"
    assert not sorted(covered - source_bindings()), (
        f"scenarios for missing bindings: {sorted(covered - source_bindings())}"
    )


def test_every_clickable_in_the_source_has_a_test() -> None:
    missing = sorted(source_clickables() - set(CLICKABLES))
    assert not missing, f"clickable widgets with no click test: {missing}"
    for test in CLICKABLES.values():
        if "::" in test:
            file, name = test.split("::")
            assert f"def {name}(" in (Path(__file__).parent / file).read_text(encoding="utf-8"), f"{test} is missing"


def test_every_readme_key_has_a_scenario() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    table = readme.split("| Key | Does |")[1].split("\n\n")[0]
    keys = {k for row in table.splitlines()[2:] for k in re.findall(r"`([^`]+)`", row.split("|")[1])}
    covered = {NAMES.get(key, key) for scn in KEY_SCENARIOS for _, key in scn.covers}
    assert keys, "no keys parsed from the README table"
    assert not (keys - covered), f"README keys with no scenario: {sorted(keys - covered)}"
