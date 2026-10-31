"""The main screen: station list on the left, the selected station's detail on the right, status bar below."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, cast

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.events import Resize
from textual.widgets import OptionList

from wxbrief.i18n.keys import K
from wxbrief.state import StationReports
from wxbrief.ui.bindings import bind, localize
from wxbrief.ui.copying import CopyActions
from wxbrief.ui.screens.add_station import AddStationScreen
from wxbrief.ui.screens.help import HelpScreen
from wxbrief.ui.screens.paste import PasteDecodeScreen
from wxbrief.ui.screens.settings import SettingsScreen
from wxbrief.ui.screens.station_detail import StationDetailScreen
from wxbrief.ui.widgets.detail import DetailPane
from wxbrief.ui.widgets.key_bar import KeyBar
from wxbrief.ui.widgets.station_grid import StationGrid
from wxbrief.ui.widgets.station_list import StationList
from wxbrief.ui.widgets.status_bar import StatusBar

if TYPE_CHECKING:
    from wxbrief.app import WxBriefApp



class BriefingScreen(CopyActions):
    BINDINGS = [
        # a d v and c 1 2 3 work wherever the focus is; the footer shows them from the pane that owns them
        # (StationList, StationGrid, DetailPane), so these copies are hidden.
        bind("a", "add_station", K.UI_BINDING_ADD_STATION, show=False),
        bind("d", "remove_station", K.UI_BINDING_REMOVE_STATION, show=False),
        bind("p", "paste", K.UI_BINDING_PASTE),
        bind("r", "refresh_now", K.UI_BINDING_REFRESH_NOW),
        bind("v", "toggle_layout", K.UI_BINDING_TOGGLE_LAYOUT, show=False),
        bind("c", "copy_metar", K.UI_BINDING_COPY_METAR, show=False),
        bind("C", "copy_both", K.UI_BINDING_COPY_BOTH, show=False),
        bind("y", "copy_raw", K.UI_BINDING_COPY_RAW, show=False),
        bind("S", "settings", K.UI_BINDING_SETTINGS, show=False),
        # j and k show in the key bar only while the station list is hidden (see _hint_steps).
        bind("j", "next_station", K.UI_BINDING_NEXT_STATION, show=False, key_display="j/k"),
        bind("k", "previous_station", K.UI_BINDING_PREVIOUS_STATION, show=False),
        bind("1", "jump('raw')", K.UI_BINDING_JUMP_RAW, show=False),
        bind("2", "jump('decoded')", K.UI_BINDING_JUMP_DECODED, show=False),
        bind("3", "jump('taf')", K.UI_BINDING_JUMP_TAF, show=False),
        bind("question_mark", "help", K.UI_BINDING_HELP),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.selected: str | None = None
        self.layout_mode = "list"  # "list" (station list and detail) or "grid" (cards)
        self._ready = False

    @property
    def wx(self) -> WxBriefApp:
        return cast("WxBriefApp", self.app)

    def compose(self) -> ComposeResult:
        with Horizontal(id="main"):
            yield StationList(id="stations")
            yield DetailPane(id="detail")
            yield StationGrid(id="grid")
        yield StatusBar(id="status")
        yield KeyBar()

    def on_mount(self) -> None:
        localize(self)
        self._ready = True
        self._ticks = 0
        self.set_interval(1.0, self._tick)  # owned by the screen, so it stops with the screen
        self.layout_mode = "grid" if self.wx.options.view.layout == "grid" else "list"
        self._apply_layout()
        self.refresh_view()
        self._focus_main()

    def _tick(self) -> None:
        self._ticks += 1
        if self._ticks % 30 == 0:
            self.refresh_view()  # fresh reports turn stale as time passes
        else:
            self.refresh_status()

    # --- drawing ---------------------------------------------------------------------------------------------------

    def current(self) -> StationReports | None:
        return next((r for r in self.wx.state.reports() if r.icao == self.selected), None)

    def refresh_view(self) -> None:
        """Redraw the list, the detail pane and the status bar from the state."""
        if not self._ready:
            return
        wx = self.wx
        reports = wx.state.reports()
        ids = [r.icao for r in reports]
        title = wx.ctx.translator.t(K.UI_LIST_TITLE, n=len(ids))
        self.query_one(StationList).border_title = self.query_one(StationGrid).border_title = title
        if self.selected not in ids:
            self.selected = ids[0] if ids else None
        if self.layout_mode == "grid":
            self.query_one(StationGrid).set_stations(reports, wx.ctx, wx.now(), self.selected)
        else:
            with self.prevent(OptionList.OptionHighlighted):  # a redraw must not look like the user moving
                self.query_one(StationList).set_stations(reports, wx.ctx, wx.now(), self.selected)
        self.show_selected()

    def show_selected(self) -> None:
        wx = self.wx
        entry = self.current()
        if self.layout_mode == "list":
            self.query_one(DetailPane).show(entry, wx.ctx, wx.now())
        self.refresh_status()

    def refresh_status(self) -> None:
        if not self._ready:
            return
        wx = self.wx
        ids = wx.state.ids
        position = (ids.index(self.selected) + 1, len(ids)) if self.selected in ids else None
        self.query_one(StatusBar).show(wx.state, wx.scheduler, wx.ctx, wx.now(), self.current(), position)

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_id is None:
            return
        self.selected = event.option_id
        self.show_selected()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Enter on a station moves into its detail."""
        self.action_focus_detail()

    def on_resize(self, event: Resize) -> None:
        self._hint_steps()
        self.call_after_refresh(self._fix_focus)

    def _hint_steps(self) -> None:
        """Show ``j/k`` in the key bar while the list is hidden (narrow terminal): the only way to change station."""
        hidden = self.layout_mode == "list" and self.has_class("-narrow")
        for key, bindings in self._bindings.key_to_bindings.items():
            if key == "j":
                bindings[:] = [replace(item, show=hidden) for item in bindings]
        self.refresh_bindings()

    def _fix_focus(self) -> None:
        if self.layout_mode == "list" and not self.query_one(StationList).display:
            self.query_one(DetailPane).focus()

    # --- layout ----------------------------------------------------------------------------------------------------

    def _apply_layout(self) -> None:
        """Switch between list and grid with a class: the stylesheet shows and hides the three panes."""
        self.set_class(self.layout_mode == "grid", "-grid")
        self._hint_steps()

    def _focus_main(self) -> None:
        if self.layout_mode == "grid":
            self.query_one(StationGrid).focus()
        else:
            self.query_one(StationList).focus()
        self._fix_focus()

    def action_toggle_layout(self) -> None:
        self.layout_mode = "list" if self.layout_mode == "grid" else "grid"
        self._apply_layout()
        self.refresh_view()
        self._focus_main()
        self.notify(self.wx.ctx.translator.t(K.UI_LAYOUT_GRID if self.layout_mode == "grid" else K.UI_LAYOUT_LIST))

    def on_station_grid_selected(self, message: StationGrid.Selected) -> None:
        self.select(message.icao)

    def on_station_grid_opened(self, message: StationGrid.Opened) -> None:
        entry = self.current()
        if entry is not None:
            self.app.push_screen(StationDetailScreen(entry, self.wx.ctx, self.wx.now()))

    # --- selection -------------------------------------------------------------------------------------------------

    def select(self, icao: str) -> None:
        ids = self.wx.state.ids
        if icao in ids:
            self.selected = icao
            self.refresh_view()

    def _step(self, offset: int) -> None:
        ids = self.wx.state.ids
        if not ids:
            return
        index = ids.index(self.selected) if self.selected in ids else 0
        self.select(ids[(index + offset) % len(ids)])

    def action_next_station(self) -> None:
        self._step(1)

    def action_previous_station(self) -> None:
        self._step(-1)

    def action_focus_detail(self) -> None:
        if self.layout_mode == "list":  # the detail pane is hidden in the grid
            self.query_one(DetailPane).focus()

    def action_jump(self, section: str) -> None:
        if self.layout_mode == "list":  # the detail pane is hidden in the grid; Enter opens a station's detail instead
            self.query_one(DetailPane).jump(section)

    # --- actions ---------------------------------------------------------------------------------------------------

    def action_add_station(self) -> None:
        wx = self.wx

        def added(icao: str | None) -> None:
            if icao:
                wx.add_station(icao)

        self.app.push_screen(AddStationScreen(wx.ctx.stations, wx.state.ids), added)

    def action_remove_station(self) -> None:
        if self.selected is not None:
            self.wx.remove_station(self.selected)

    def action_paste(self) -> None:
        self.app.push_screen(PasteDecodeScreen(self.wx.ctx, self.wx.now))

    def action_refresh_now(self) -> None:
        self.wx.refresh_now()

    def action_settings(self) -> None:
        self.app.push_screen(SettingsScreen())

    def action_help(self) -> None:
        self.app.push_screen(HelpScreen())
