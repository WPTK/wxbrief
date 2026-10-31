"""One station's full detail on its own screen: what Enter opens from the grid layout."""

from __future__ import annotations

from datetime import datetime

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Footer

from wxbrief.i18n.keys import K
from wxbrief.state import StationReports
from wxbrief.ui.bindings import bind, localize
from wxbrief.ui.context import ViewContext
from wxbrief.ui.widgets.detail import DetailPane


class StationDetailScreen(Screen[None]):
    BINDINGS = [
        bind("escape", "close", K.UI_BINDING_BACK),
        bind("1", "jump('raw')", K.UI_BINDING_JUMP_RAW, show=False),
        bind("2", "jump('decoded')", K.UI_BINDING_JUMP_DECODED, show=False),
        bind("3", "jump('taf')", K.UI_BINDING_JUMP_TAF, show=False),
    ]

    def __init__(self, entry: StationReports, ctx: ViewContext, now: datetime, position: str = "") -> None:
        super().__init__()
        self._entry = entry
        self._ctx = ctx
        self._now = now
        self._position = position

    def compose(self) -> ComposeResult:
        yield DetailPane(id="detail")
        yield Footer()

    def on_mount(self) -> None:
        localize(self)
        self.redraw()
        pane = self.query_one(DetailPane)
        pane.focus(scroll_visible=False)
        pane.scroll_home(animate=False)  # open on the station header, whatever the first layout pass did

    def redraw(self) -> None:
        """Draw the snapshot again, e.g. after a theme change (the colours are baked into the Rich text)."""
        self.query_one(DetailPane).show(self._entry, self._ctx, self._now, self._position)

    def action_jump(self, section: str) -> None:
        self.query_one(DetailPane).jump(section)

    def action_close(self) -> None:
        self.dismiss(None)
