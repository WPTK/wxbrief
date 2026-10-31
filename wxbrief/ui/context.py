"""What every widget needs to draw a report: language, units, glyphs, time mode and the theme palette."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from wxbrief.data.stations import Station, StationDB
from wxbrief.decode.units import UnitsMode
from wxbrief.i18n import Translator
from wxbrief.ui.glyphs import Glyphs
from wxbrief.ui.style import Palette

if TYPE_CHECKING:
    from textual.app import App


@dataclass(slots=True)
class ViewContext:
    app: App[Any]
    translator: Translator
    units: UnitsMode
    glyphs: Glyphs
    time_mode: str
    stations: StationDB
    _palette: Palette | None = None
    _palette_theme: str | None = None

    @property
    def palette(self) -> Palette:
        """The palette for the active theme, rebuilt when the theme changes."""
        name = self.app.theme
        if self._palette is None or self._palette_theme != name:
            self._palette = Palette(self.app.get_css_variables())
            self._palette_theme = name
        return self._palette

    def station(self, icao: str) -> Station | None:
        return self.stations.get(icao)

    def clock(self, moment: datetime | None, icao: str | None = None) -> str:
        """``14:53Z``, or the same moment in station-local or computer-local time per the time mode."""
        if moment is None:
            return "--"
        zone: ZoneInfo | None = None
        if self.time_mode == "station" and icao:
            found = self.station(icao)
            if found and found.tz:
                try:
                    zone = ZoneInfo(found.tz)
                except (ZoneInfoNotFoundError, ValueError, OSError):
                    zone = None
        if self.time_mode == "zulu" or (self.time_mode == "station" and zone is None):
            return moment.strftime("%H:%MZ")
        shifted = moment.astimezone(zone) if zone is not None else moment.astimezone()
        return f"{shifted:%H:%M} {shifted.tzname() or ''}".strip()
