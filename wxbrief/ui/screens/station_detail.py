"""One station's full detail on its own screen: what Enter opens from the grid layout."""

from __future__ import annotations

from datetime import datetime

from textual.app import ComposeResult
from textual.widgets import Footer

from wxbrief.i18n.keys import K
from wxbrief.state import StationReports
from wxbrief.ui.bindings import bind, localize
from wxbrief.ui.context import ViewContext
from wxbrief.ui.copying import CopyActions
from wxbrief.ui.widgets.detail import DetailPane


class StationDetailScreen(CopyActions):
    # 1 2 3 and c live on DetailPane (its bindings reach this screen's copy actions through "screen.").
    BINDINGS = [
        bind("escape", "close", K.UI_BINDING_BACK),
        bind("C", "copy_both", K.UI_BINDING_COPY_BOTH, show=False),
        bind("y", "copy_raw", K.UI_BINDING_COPY_RAW, show=False),
    ]

    def __init__(self, entry: StationReports, ctx: ViewContext, now: datetime) -> None:
        super().__init__()
        self._entry = entry
        self._ctx = ctx
        self._now = now

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
        self.query_one(DetailPane).show(self._entry, self._ctx, self._now)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """A station's own screen cannot add a station: DetailPane's ``a`` is hidden here."""
        del parameters
        return action != "add_station"

    def current(self) -> StationReports:
        return self._entry

    def action_close(self) -> None:
        self.dismiss(None)
