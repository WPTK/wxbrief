"""One station's full detail on its own screen: what Enter opens from the grid layout."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from textual.app import ComposeResult

from wxbrief.i18n.keys import K
from wxbrief.state import StationReports
from wxbrief.ui.bindings import bind, localize
from wxbrief.ui.copying import CopyActions
from wxbrief.ui.widgets.detail import DetailPane
from wxbrief.ui.widgets.key_bar import KeyBar

if TYPE_CHECKING:
    from wxbrief.app import WxBriefApp

REDRAW_SECONDS = 30.0  # the age and the fresh/stale mark move with the clock, so the screen draws itself again


class StationDetailScreen(CopyActions):
    # 1 2 3 and c live on DetailPane (its bindings reach this screen's copy actions through "screen.").
    BINDINGS = [
        bind("escape", "close", K.UI_BINDING_BACK),
        bind("C", "copy_both", K.UI_BINDING_COPY_BOTH, show=False),
        bind("y", "copy_raw", K.UI_BINDING_COPY_RAW, show=False),
    ]

    def __init__(self, icao: str) -> None:
        super().__init__()
        self._icao = icao

    @property
    def wx(self) -> WxBriefApp:
        return cast("WxBriefApp", self.app)

    def compose(self) -> ComposeResult:
        yield DetailPane(id="detail")
        yield KeyBar()

    def on_mount(self) -> None:
        localize(self)
        self.set_interval(REDRAW_SECONDS, self.redraw)
        self.redraw()
        pane = self.query_one(DetailPane)
        pane.focus(scroll_visible=False)
        pane.scroll_home(animate=False)  # open on the station header, whatever the first layout pass did

    def redraw(self) -> None:
        """Draw the station from the current state and clock: on a timer, after a poll, a theme or a setting change."""
        self.query_one(DetailPane).show(self.current(), self.wx.ctx, self.wx.now())

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """A station's own screen cannot add a station: DetailPane's ``a`` is hidden here."""
        del parameters
        return action != "add_station"

    def current(self) -> StationReports:
        return next((r for r in self.wx.state.reports() if r.icao == self._icao), StationReports(self._icao))

    def action_close(self) -> None:
        self.dismiss(None)
