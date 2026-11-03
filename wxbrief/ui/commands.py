"""The Ctrl+P command palette: the app's own actions and a station switch by ICAO id or name."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from typing import TYPE_CHECKING, cast

from textual.app import SystemCommand
from textual.command import DiscoveryHit, Hit, Hits, Provider
from textual.screen import Screen

from wxbrief.i18n import Translator
from wxbrief.i18n.keys import K
from wxbrief.ui.screens.base import StationScreen
from wxbrief.ui.screens.briefing import BriefingScreen

if TYPE_CHECKING:
    from wxbrief.app import WxBriefApp

HIDDEN = frozenset({"Keys", "Screenshot"})  # Textual's own help panel (the app has ``?``) and a file written to the cwd


def app_commands(app: WxBriefApp, screen: Screen[object], t: Translator) -> Iterable[SystemCommand]:
    """What the keys do, by name, for the screen the palette was opened from."""
    if isinstance(screen, BriefingScreen):
        yield SystemCommand(t.t(K.UI_PALETTE_ADD_STATION), "a", screen.action_add_station)
        yield SystemCommand(t.t(K.UI_BINDING_REMOVE_STATION), "d", screen.action_remove_station)
        yield SystemCommand(t.t(K.UI_BINDING_PASTE), "p", screen.action_paste)
        yield SystemCommand(t.t(K.UI_BINDING_TOGGLE_LAYOUT), "v", screen.action_toggle_layout)
        yield SystemCommand(t.t(K.UI_BINDING_SETTINGS), "S", screen.action_settings)
    if isinstance(screen, StationScreen):
        yield SystemCommand(t.t(K.UI_BINDING_REFRESH_NOW), "r", screen.action_refresh_now)
        yield SystemCommand(t.t(K.UI_BINDING_HELP), "?", screen.action_help)
    yield SystemCommand(t.t(K.UI_BINDING_CYCLE_UNITS), "u", app.action_cycle_units)
    yield SystemCommand(t.t(K.UI_BINDING_CYCLE_TIME), "z", app.action_cycle_time)
    yield SystemCommand(t.t(K.UI_BINDING_CYCLE_GLYPHS), "g", app.action_cycle_glyphs)


class StationProvider(Provider):
    """``KDEN`` or ``Denver`` in the palette selects that station of the watchlist."""

    def _stations(self) -> list[tuple[str, str]]:
        """The watchlist, or nothing when the palette was opened over Help, Settings or a detail: the selection would
        change out of sight."""
        app = cast("WxBriefApp", self.app)
        found: list[tuple[str, str]] = []
        if not isinstance(self.screen, BriefingScreen):
            return found
        for icao in app.state.ids:
            station = app.ctx.station(icao)
            found.append((icao, f"{icao} {station.name}" if station else icao))
        return found

    def _goto(self, icao: str) -> None:
        cast("WxBriefApp", self.app).briefing.select(icao)

    async def discover(self) -> Hits:
        t = cast("WxBriefApp", self.app).ctx.translator
        for icao, label in self._stations():
            yield DiscoveryHit(t.t(K.UI_PALETTE_GO_TO, station=label), lambda i=icao: self._goto(i))

    async def search(self, query: str) -> AsyncIterator[Hit]:
        t = cast("WxBriefApp", self.app).ctx.translator
        matcher = self.matcher(query)
        for icao, label in self._stations():
            title = t.t(K.UI_PALETTE_GO_TO, station=label)
            score = matcher.match(title)
            if score > 0:
                yield Hit(score, matcher.highlight(title), lambda i=icao: self._goto(i))
