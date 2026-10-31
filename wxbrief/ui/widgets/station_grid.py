"""The grid layout: a wrapping grid of station cards. Arrow keys move, Enter opens the station."""

from __future__ import annotations

from datetime import datetime

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.events import Resize
from textual.message import Message

from wxbrief.state import StationReports
from wxbrief.ui.context import ViewContext
from wxbrief.ui.widgets.station_card import StationCard

CARD_WIDTH = 38  # the least width a card gets; a wider pane fits more columns


class StationGrid(VerticalScroll, can_focus=True):
    BINDINGS = [
        Binding("left", "move(-1, 0)", "Left", show=False),
        Binding("right", "move(1, 0)", "Right", show=False),
        Binding("up", "move(0, -1)", "Up", show=False),
        Binding("down", "move(0, 1)", "Down", show=False),
        Binding("enter", "open", "Open", show=False),
    ]

    class Selected(Message):
        def __init__(self, icao: str) -> None:
            super().__init__()
            self.icao = icao

    class Opened(Message):
        def __init__(self, icao: str) -> None:
            super().__init__()
            self.icao = icao

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.ids: list[str] = []
        self.selected: str | None = None

    def compose(self) -> ComposeResult:
        yield Container(id="cards")

    @property
    def columns(self) -> int:
        return max(1, self.size.width // CARD_WIDTH)

    def on_resize(self, event: Resize) -> None:
        self.query_one("#cards", Container).styles.grid_size_columns = self.columns

    def set_stations(
        self, reports: list[StationReports], ctx: ViewContext, now: datetime, selected: str | None
    ) -> None:
        """Draw one card per station; cards are reused (and keep their place) while the list is unchanged."""
        cards = self.query_one("#cards", Container)
        ids = [entry.icao for entry in reports]
        if ids != self.ids:
            self.ids = ids
            cards.remove_children()
            cards.mount(*(StationCard(icao) for icao in ids))
        self.selected = selected if selected in ids else (ids[0] if ids else None)
        cards.styles.grid_size_columns = self.columns
        for entry in reports:
            card = self._card(entry.icao)
            if card is not None:
                card.show(entry, ctx, now, selected=entry.icao == self.selected)
        card = self._card(self.selected) if self.selected else None
        if card is not None:
            self.call_after_refresh(card.scroll_visible, animate=False)

    def _card(self, icao: str) -> StationCard | None:
        found = self.query(f"#card-{icao}")
        return found.first(StationCard) if found else None

    def action_move(self, dx: int, dy: int) -> None:
        if not self.ids:
            return
        index = self.ids.index(self.selected) if self.selected in self.ids else 0
        target = index + dx + dy * self.columns
        if 0 <= target < len(self.ids):
            self.post_message(self.Selected(self.ids[target]))

    def action_open(self) -> None:
        if self.selected:
            self.post_message(self.Opened(self.selected))

    def on_station_card_clicked(self, message: StationCard.Clicked) -> None:
        message.stop()
        self.focus()
        if message.icao == self.selected:
            self.post_message(self.Opened(message.icao))
        else:
            self.post_message(self.Selected(message.icao))
