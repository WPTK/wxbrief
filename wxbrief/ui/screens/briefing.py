"""The main screen: station list on the left, the selected station's detail on the right, status bar below."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.events import Resize
from textual.screen import Screen
from textual.widgets import Footer, OptionList

from wxbrief.clipboard import copy_text
from wxbrief.decode.model import Metar, Taf
from wxbrief.decode.units import UnitsMode
from wxbrief.getcmd import local_hour
from wxbrief.render.discord import render_discord
from wxbrief.state import StationReports
from wxbrief.ui.screens.add_station import AddStationScreen
from wxbrief.ui.screens.help import HelpScreen
from wxbrief.ui.screens.paste import PasteDecodeScreen
from wxbrief.ui.screens.settings import SettingsScreen
from wxbrief.ui.widgets.detail import DetailPane
from wxbrief.ui.widgets.station_list import StationList
from wxbrief.ui.widgets.status_bar import StatusBar

if TYPE_CHECKING:
    from wxbrief.app import WxBriefApp


class BriefingScreen(Screen[None]):
    BINDINGS = [
        Binding("a", "add_station", "Add"),
        Binding("d", "remove_station", "Remove"),
        Binding("p", "paste", "Paste"),
        Binding("r", "refresh_now", "Refresh"),
        Binding("c", "copy_metar", "Copy METAR", show=False),
        Binding("C", "copy_both", "Copy METAR+TAF", show=False),
        Binding("y", "copy_raw", "Copy raw", show=False),
        Binding("S", "settings", "Settings", show=False),
        Binding("j", "next_station", "Next", show=False),
        Binding("k", "previous_station", "Previous", show=False),
        Binding("right_square_bracket", "next_station", "Next", show=False),
        Binding("left_square_bracket", "previous_station", "Previous", show=False),
        Binding("enter", "focus_detail", "Detail", show=False),
        Binding("1", "jump('raw')", "Raw", show=False),
        Binding("2", "jump('decoded')", "Decoded", show=False),
        Binding("3", "jump('taf')", "TAF", show=False),
        Binding("question_mark", "help", "Help"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.selected: str | None = None
        self._syncing = False
        self._ready = False

    @property
    def wx(self) -> WxBriefApp:
        return cast("WxBriefApp", self.app)

    def compose(self) -> ComposeResult:
        with Horizontal(id="main"):
            yield StationList(id="stations")
            yield DetailPane(id="detail")
        yield StatusBar(id="status")
        yield Footer()

    def on_mount(self) -> None:
        self._ready = True
        self.refresh_view()
        self.query_one(StationList).focus()

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
        if self.selected not in ids:
            self.selected = ids[0] if ids else None
        self._syncing = True
        try:
            self.query_one(StationList).set_stations(reports, wx.ctx, wx.now(), self.selected)
        finally:
            self._syncing = False
        self.show_selected()

    def show_selected(self) -> None:
        wx = self.wx
        entry = self.current()
        ids = wx.state.ids
        position = f"{ids.index(entry.icao) + 1}/{len(ids)}" if entry else ""
        self.query_one(DetailPane).show(entry, wx.ctx, wx.now(), position)
        self.refresh_status()

    def refresh_status(self) -> None:
        if not self._ready:
            return
        wx = self.wx
        self.query_one(StatusBar).show(wx.state, wx.scheduler, wx.ctx, wx.now(), self.current(), wx.glyph_set)

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if self._syncing or event.option_id is None:
            return
        self.selected = event.option_id
        self.show_selected()

    def on_resize(self, event: Resize) -> None:
        self.call_after_refresh(self._fix_focus)

    def _fix_focus(self) -> None:
        if not self.query_one(StationList).display:
            self.query_one(DetailPane).focus()

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
        self.query_one(DetailPane).focus()

    def action_jump(self, section: str) -> None:
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
        self.app.push_screen(SettingsScreen(self.wx.settings_lines()))

    def action_help(self) -> None:
        self.app.push_screen(HelpScreen())

    # --- copying ---------------------------------------------------------------------------------------------------

    def _discord(self, report: Metar | Taf, entry: StationReports) -> str:
        ctx = self.wx.ctx
        station = ctx.station(entry.icao)
        name = station.name if station else None
        hour = None
        if isinstance(report, Metar) and entry.awc_metar is not None:
            hour = local_hour(station.tz if station else None, entry.awc_metar.observed)
        units = ctx.units if ctx.units is not UnitsMode.MIXED else UnitsMode.US
        return render_discord(report, ctx.translator, units, station_name=name, local_hour=hour)

    def action_copy_metar(self) -> None:
        entry = self.current()
        if entry is None or entry.metar is None:
            self.notify("No METAR to copy", severity="warning")
            return
        copy_text(self.app, self._discord(entry.metar, entry), f"{entry.icao} METAR")

    def action_copy_both(self) -> None:
        entry = self.current()
        if entry is None or (entry.metar is None and entry.taf is None):
            self.notify("Nothing to copy", severity="warning")
            return
        blocks = [self._discord(report, entry) for report in (entry.metar, entry.taf) if report is not None]
        copy_text(self.app, "\n\n".join(blocks), f"{entry.icao} METAR and TAF")

    def action_copy_raw(self) -> None:
        entry = self.current()
        raws = [report.raw for report in (entry.metar, entry.taf) if report is not None] if entry else []
        if not entry or not raws:
            self.notify("Nothing to copy", severity="warning")
            return
        copy_text(self.app, "\n".join(raws), f"{entry.icao} raw report")
