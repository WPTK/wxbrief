"""Add a station: type a code or part of a name, pick from the matches."""

from __future__ import annotations

import re
from collections.abc import Sequence

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.suggester import Suggester
from textual.widgets import Input, Label, OptionList
from textual.widgets.option_list import Option

from wxbrief.data.stations import Station, StationDB

_CODE = re.compile(r"^[A-Za-z0-9]{3,4}$")


class StationSuggester(Suggester):
    """Completes what is typed to a station code or name; only text that starts with the input can be suggested."""

    def __init__(self, db: StationDB) -> None:
        super().__init__(use_cache=False, case_sensitive=False)
        self._db = db

    async def get_suggestion(self, value: str) -> str | None:
        query = value.strip()
        if len(query) < 2:
            return None
        for station in self._db.search(query, limit=5):
            for candidate in (station.icao, station.name):
                if candidate.casefold().startswith(query.casefold()) and len(candidate) > len(query):
                    return query + candidate[len(query) :]
        return None


def station_label(station: Station) -> Text:
    codes = " ".join(c for c in (station.iata,) if c)
    place = ", ".join(p for p in (station.state, station.country) if p)
    line = Text.assemble((f"{station.icao:<5}", "bold"), station.name)
    if codes:
        line.append(f"  {codes}", style="dim")
    if place:
        line.append(f"  {place}", style="dim")
    return line


class AddStationScreen(ModalScreen[str | None]):
    """Dismisses with the chosen station id, or ``None``."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("down", "focus_results", "Results", show=False),
    ]

    def __init__(self, db: StationDB, existing: Sequence[str] = ()) -> None:
        super().__init__()
        self._db = db
        self._existing = set(existing)
        self.matches: list[Station] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="add-box", classes="dialog"):
            yield Label("Add station: ICAO or IATA code, or part of the name", classes="dialog-title")
            yield Input(placeholder="KDEN, DEN, heathrow ...", id="query", suggester=StationSuggester(self._db))
            yield OptionList(id="results")
            yield Label("Enter adds the first match   Down picks another   Esc cancels", classes="hint")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    @on(Input.Changed)
    def _search(self, event: Input.Changed) -> None:
        results = self.query_one(OptionList)
        results.clear_options()
        self.matches = self._db.search(event.value, limit=8) if event.value.strip() else []
        for station in self.matches:
            label = station_label(station)
            if station.icao in self._existing:
                label.append("  (listed)", style="dim")
            results.add_option(Option(label, id=station.icao))
        if self.matches:
            results.highlighted = 0

    @on(Input.Submitted)
    def _submit(self, event: Input.Submitted) -> None:
        if self.matches:
            self.dismiss(self.matches[0].icao)
            return
        code = event.value.strip().upper()
        station = self._db.get(code) if _CODE.match(code) else None  # an IATA or FAA code finds its station
        if station is not None:
            self.dismiss(station.icao)
        elif _CODE.match(code):
            self.notify(f"Unknown station {code}", severity="warning")
        else:
            self.notify("Type a station code or part of a name", severity="warning")

    @on(OptionList.OptionSelected)
    def _picked(self, event: OptionList.OptionSelected) -> None:
        if event.option_id:
            self.dismiss(event.option_id)

    def action_focus_results(self) -> None:
        if self.matches:
            self.query_one(OptionList).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)
