"""The Ctrl+P command palette: the app's own actions and a station switch by ICAO id or name."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import dataclass
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
SEPARATORS = re.compile(r"[\s,;>/→-]+")  # space, comma, ``>``, ``-``, ``/``, arrow: KDEN>KORD, KDEN-KORD
CODE_SHAPE = re.compile(r"[A-Z0-9]{3,4}")  # an ICAO, IATA or FAA id; anything longer is a name for the fuzzy search


@dataclass(frozen=True)
class Route:
    """A typed route: the stations it names in order, and the codes that name no station."""

    found: tuple[str, ...]
    rejected: tuple[str, ...]


def parse_route(text: str, resolve: Callable[[str], str | None]) -> Route | None:
    """``KDEN KORD KJFK``, ``KDEN>KJFK`` or ``kden-kjfk`` as a ``Route``; ``None`` when the text is not a route.

    ``resolve`` turns a typed code into an ICAO id (``None`` when it names no station). Text is a route only when
    every word is code-shaped and at least one resolves, so ``KD``, ``Denver`` and ``dark mode`` stay plain searches.
    Words that do not resolve (unknown, or an IATA/FAA code shared by two stations) come back in ``rejected`` so the
    palette can say why. Repeats collapse.
    """
    words = [w for w in SEPARATORS.split(text.strip().upper()) if w]
    if not words or not all(CODE_SHAPE.fullmatch(w) for w in words):
        return None
    found: list[str] = []
    rejected: list[str] = []
    for word in words:
        icao = resolve(word)
        if icao is None:
            if word not in rejected:
                rejected.append(word)
        elif icao not in found:
            found.append(icao)
    if not found:  # "dark mode" or "add stat" are searches; a route needs at least one real station
        return None
    return Route(tuple(found), tuple(rejected))


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

    def _route_hit(self, query: str) -> tuple[str, Callable[[], None]] | None:
        """The route typed as ``query``: its title and what choosing it does. Nothing on a modal screen."""
        app = cast("WxBriefApp", self.app)
        if not isinstance(self.screen, BriefingScreen):
            return None
        route = parse_route(query, lambda code: getattr(app.ctx.station(code), "icao", None))
        if route is None:
            return None
        t = app.ctx.translator
        if route.rejected:  # nothing is added from a route with a bad id: the reason is the hit
            codes = " ".join(route.rejected)
            return t.t(K.UI_PALETTE_ROUTE_REJECTED, codes=codes), lambda: app.notify(
                t.t(K.UI_TOAST_UNKNOWN_STATION, code=codes), severity="warning"
            )
        if all(icao in app.state.ids for icao in route.found) and len(route.found) < 2:
            return None  # one listed station: the plain "Go to" hit covers it
        return t.t(K.UI_PALETTE_ROUTE, route=" > ".join(route.found)), lambda: app.show_route(route.found)

    async def discover(self) -> Hits:
        t = cast("WxBriefApp", self.app).ctx.translator
        for icao, label in self._stations():
            yield DiscoveryHit(t.t(K.UI_PALETTE_GO_TO, station=label), lambda i=icao: self._goto(i))

    async def search(self, query: str) -> AsyncIterator[Hit]:
        t = cast("WxBriefApp", self.app).ctx.translator
        matcher = self.matcher(query)
        route = self._route_hit(query)
        if route is not None:
            yield Hit(1.0, route[0], route[1])  # above every fuzzy score: the whole query is the route
        for icao, label in self._stations():
            title = t.t(K.UI_PALETTE_GO_TO, station=label)
            score = matcher.match(title)
            if score > 0:
                yield Hit(score, matcher.highlight(title), lambda i=icao: self._goto(i))
