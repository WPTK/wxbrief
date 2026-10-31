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
        self._going: set[StationCard] = set()

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
            # Keep the cards that stay, remove the ones that went, mount the new ones, then put them in order. Cards
            # carry no ids, so a station removed and added again at once can never collide with its dying card.
            have = {card.icao: card for card in cards.query(StationCard) if card not in self._going}
            for icao, card in have.items():
                if icao not in ids:
                    self._going.add(card)
                    card.remove()
            have = {icao: card for icao, card in have.items() if icao in ids}
            fresh = [StationCard(icao) for icao in ids if icao not in have]
            if fresh:
                cards.mount(*fresh)
            have.update((card.icao, card) for card in fresh)
            previous: StationCard | None = None
            for icao in ids:
                card = have[icao]
                if previous is None:
                    if cards.children and cards.children[0] is not card:
                        cards.move_child(card, before=0)
                else:
                    cards.move_child(card, after=previous)
                previous = card
            self._going = {card for card in self._going if card.is_attached}
        self.selected = selected if selected in ids else (ids[0] if ids else None)
        cards.styles.grid_size_columns = self.columns
        for entry in reports:
            found = self._card(entry.icao)
            if found is not None:
                found.show(entry, ctx, now, selected=entry.icao == self.selected)
        chosen = self._card(self.selected) if self.selected else None
        if chosen is not None:
            self.call_after_refresh(chosen.scroll_visible, animate=False)

    def _card(self, icao: str) -> StationCard | None:
        return next((card for card in self.query(StationCard) if card.icao == icao and card not in self._going), None)

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
