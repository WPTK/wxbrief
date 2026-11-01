"""State matrix: five states, four terminal sizes, seven screens, with a rule list that no screen contradicts itself.

One session per (state, size) walks every screen with the real keys; after each screen the rules run on the rendered
text. 5 states x 4 sizes x 7 screens = 140 cells. A rule failure names the state, size, screen and the screen text.
Not driven here: a loading state (transient, so a screenshot of it is a race) and a quiet or busy day (the demo data
is fixed); they stay with the pilot UAT.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from uat_kit import Screen, Terminal

Start = Callable[..., Terminal]
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "awc"
SIZES = [(100, 30), (120, 30), (200, 50), (280, 70)]
SCREENS = ["list", "grid", "detail", "help", "add", "settings", "paste"]
BAR = "▌"


def seed_cache(directory: Path) -> None:
    """A cache with Denver and Heathrow reports, so the next start shows saved data before the network fails."""
    cache = directory / "cache"
    cache.mkdir()
    now = datetime.now(UTC).isoformat()
    for key, name in (("metars", "metar_kden_egll.json"), ("tafs", "taf_kden_egll.json")):
        rows = [
            r for r in json.loads((FIXTURES / name).read_text(encoding="utf-8")) if r.get("icaoId") in ("KDEN", "EGLL")
        ]
        (cache / f"{key}.json").write_text(json.dumps({"saved_at": now, "payload": rows}), encoding="utf-8")


def bad_config(directory: Path) -> None:
    (directory / "config.toml").write_text("this is [not valid toml\n", encoding="utf-8")


# state -> (station args, demo, prepare hook, text to wait for before walking)
STATES: dict[str, tuple[list[str], bool, Callable[[Path], None] | None, str]] = {
    "demo": ([], True, None, "Stations (10)"),
    "offline-no-cache": (["KDEN", "EGLL"], False, None, "No report yet"),
    "offline-with-saved-data": (["KDEN", "EGLL"], False, seed_cache, "stale"),
    "first-run-empty": ([], False, None, ""),
    "bad-config": (["KDEN"], False, bad_config, ""),
}


def status_row(screen: Screen) -> str:
    for line in screen.lines[-3:]:
        if re.match(r"\s*\d+/\d+\s", line) or "polling" in line or "offline" in line:
            return line.partition(BAR)[0]
    return ""


def contradictions(screen: Screen) -> list[str]:
    """The rules. Each returns a sentence when the rendered text contradicts itself."""
    found: list[str] = []
    text = screen.text
    bar = status_row(screen)
    low = bar.lower()
    if "offline" in low and "fresh" in low:
        found.append(f"status bar says both offline and fresh: {bar.strip()!r}")
    if "offline" in low and re.search(r"\blive\b", low):
        found.append(f"status bar says both offline and live: {bar.strip()!r}")
    if "polling off" in low and re.search(r"next poll", low):
        found.append(f"status bar says polling is off and shows a next poll: {bar.strip()!r}")
    title = re.search(r"Stations \((\d+)\)", text)
    counter = re.match(r"\s*(\d+)/(\d+)\s", bar)
    if title and counter and title[1] != counter[2]:
        found.append(f"title counts {title[1]} stations, status bar {counter[2]}")
    if title and "╭" not in text and "┏" not in text:
        rows = [
            ln
            for ln in screen.lines
            if re.search(r"^\W*\s*[A-Z0-9]{4}\s{2}(LIFR|IFR|MVFR|VFR|--)\s", ln.partition("▎")[0] + "  ")
        ]
        shown = len(rows)
        if shown and shown != int(title[1]) and int(title[1]) <= len(screen.lines) - 5:
            found.append(f"title counts {title[1]} stations, the list shows {shown}")
    for bad in ("Traceback", "Exception", "NoneType", "object at 0x"):
        if bad in text:
            found.append(f"internal error text on screen: {bad!r}")
    if text.count("Polling is off") > 1:
        found.append("the same toast is stacked more than once")
    return found


def walk(term: Terminal) -> dict[str, Screen]:
    """Visit the seven screens with the real keys, returning each one's rendered text."""
    seen = {"list": term.settle(0.5)}
    steps = [
        ("grid", ["v"], ["v"]),
        ("detail", ["enter"], ["escape"]),
        ("help", ["?"], ["escape"]),
        ("add", ["a"], ["escape"]),
        ("settings", ["S"], ["escape"]),
        ("paste", ["p"], ["escape"]),
    ]
    for name, into, out in steps:
        term.send_keys(*into)
        seen[name] = term.settle(0.5)
        term.send_keys(*out)
        term.settle(0.3)
    return seen


@pytest.mark.parametrize("size", SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
@pytest.mark.parametrize("state", list(STATES))
def test_no_screen_contradicts_itself(start: Start, state: str, size: tuple[int, int]) -> None:
    args, demo, prepare, wait = STATES[state]
    term = start(*size, args, demo=demo, prepare=prepare, ready=wait or "Stations")
    term.settle(1.0)
    if state.startswith("offline"):
        term.send_keys("r")  # the second failed fetch is what makes the status bar say offline
        term.wait_for(lambda s: "offline" in status_row(s).lower(), 60, "the offline status")
    problems = []
    for name, screen in walk(term).items():
        problems += [f"[{state} {size[0]}x{size[1]} {name}] {p}\n{screen.text}" for p in contradictions(screen)]
    assert not problems, "\n\n".join(problems)
