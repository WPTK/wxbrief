"""Monkey test: random key, resize and refresh sequences against a loaded app (Pilot + hypothesis state machine).

Invariants after every step: the app has not raised, the station list highlights the selected station, and a redraw
with unchanged data (``refresh`` rule: the 30 s tick, a poll that returns the same rows, a theme or unit change) leaves
the list scroll, the detail pane scroll, the TAF cursor, the focus and the DecodedTable cursor where they were.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule
from ux_kit import load, make_app, rows, station_ids

from wxbrief.ui.screens.briefing import BriefingScreen
from wxbrief.ui.widgets.detail import DecodedTable, DetailPane
from wxbrief.ui.widgets.station_list import StationList
from wxbrief.ui.widgets.taf_timeline import TafTimeline

KEYS = [
    "up",
    "down",
    "pageup",
    "pagedown",
    "home",
    "end",
    "enter",
    "escape",
    "tab",
    "shift+tab",
    "j",
    "k",
    "1",
    "2",
    "3",
    "left",
    "right",
    "v",
    "r",
    "question_mark",
]
SIZES = [(80, 24), (100, 30), (120, 40), (200, 60)]


def snapshot_of(app: Any) -> dict[str, Any]:
    screen = app.screen
    assert isinstance(screen, BriefingScreen)
    table = screen.query_one(DecodedTable)
    return {
        "list_scroll": screen.query_one(StationList).scroll_y,
        "pane_scroll": screen.query_one(DetailPane).scroll_y,
        "timeline_cursor": screen.query_one(TafTimeline).cursor,
        "focused": app.focused,
        "table_cursor": table.cursor_coordinate,
        "table_scroll": table.scroll_y,
        "selected": screen.selected,
    }


class BriefingMonkey(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.runner = asyncio.Runner()
        ids = station_ids("taf_us_20261031", 30)
        self.app = make_app(Path(tempfile.mkdtemp()), ids)
        self.manager = self.app.run_test(size=(120, 40))
        self.pilot = self.runner.run(self.manager.__aenter__())
        load(self.app, rows("metar_us_20261031"), rows("taf_us_20261031"))
        self.run(self.pilot.pause())

    def run(self, coroutine: Any) -> Any:
        return self.runner.run(coroutine)

    def teardown(self) -> None:
        try:
            self.run(self.manager.__aexit__(None, None, None))
        finally:
            self.runner.close()

    @rule(key=st.sampled_from(KEYS))
    def press(self, key: str) -> None:
        self.run(self.pilot.press(key))
        self.run(self.pilot.pause())
        self.leave_dialogs()

    @rule(size=st.sampled_from(SIZES))
    def resize(self, size: tuple[int, int]) -> None:
        self.run(self.pilot.resize_terminal(*size))
        self.run(self.pilot.pause())

    @rule(amount=st.integers(1, 12), up=st.booleans())
    def wheel(self, amount: int, up: bool) -> None:
        pane = self.app.screen.query_one(DetailPane)
        pane.scroll_to(y=max(0, min(pane.max_scroll_y, pane.scroll_y + (-amount if up else amount))), animate=False)
        self.run(self.pilot.pause())

    @rule()
    def refresh(self) -> None:
        """A redraw from unchanged data must not move anything the user placed."""
        self.run(self.pilot.pause())
        before = snapshot_of(self.app)
        self.app.redraw_screens()
        self.run(self.pilot.pause())
        self.run(self.pilot.pause())
        after = snapshot_of(self.app)
        assert after == before, {k: (before[k], after[k]) for k in before if before[k] != after[k]}

    @rule()
    def new_poll_same_rows(self) -> None:
        before = snapshot_of(self.app)
        load(self.app, rows("metar_us_20261031"), rows("taf_us_20261031"))
        self.run(self.pilot.pause())
        self.run(self.pilot.pause())
        after = snapshot_of(self.app)
        assert after == before, {k: (before[k], after[k]) for k in before if before[k] != after[k]}

    def leave_dialogs(self) -> None:
        while not isinstance(self.app.screen, BriefingScreen):
            self.run(self.pilot.press("escape"))
            self.run(self.pilot.pause())

    @invariant()
    def healthy(self) -> None:
        assert self.app._exception is None
        screen = self.app.screen
        if isinstance(screen, BriefingScreen) and screen.layout_mode == "list":
            option_list = screen.query_one(StationList)
            if option_list.display and option_list.highlighted is not None:
                assert option_list.get_option_at_index(option_list.highlighted).id == screen.selected


BriefingMonkey.TestCase.settings = settings(
    max_examples=10,
    stateful_step_count=14,
    deadline=None,
    suppress_health_check=list(HealthCheck),
    database=None,
)
test_briefing_monkey = pytest.mark.slow(BriefingMonkey.TestCase)
