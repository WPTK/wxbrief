"""What every widget needs to draw a report: language, units, glyphs, time mode and the theme palette."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from wxbrief.data.stations import Station, StationDB
from wxbrief.decode.units import UnitsMode
from wxbrief.i18n import Translator
from wxbrief.i18n.keys import K
from wxbrief.render.palette import Palette
from wxbrief.ui.glyphs import Glyphs
from wxbrief.ui.style import ViewPalette

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
    _palette: ViewPalette | None = None
    _palette_theme: str | None = None

    @property
    def palette(self) -> ViewPalette:
        """The palette for the active theme, rebuilt when the theme changes."""
        name = self.app.theme
        if self._palette is None or self._palette_theme != name:
            self._palette = ViewPalette(Palette.from_theme(self.app.current_theme))
            self._palette_theme = name
        return self._palette

    def station(self, icao: str) -> Station | None:
        return self.stations.get(icao)

    def _zone(self, icao: str | None) -> ZoneInfo | None:
        """The station's own zone in ``station`` mode, when the database knows it."""
        if self.time_mode == "station" and icao:
            found = self.station(icao)
            if found and found.tz:
                try:
                    return ZoneInfo(found.tz)
                except (ZoneInfoNotFoundError, ValueError, OSError):
                    return None
        return None

    def is_zulu(self, icao: str | None = None) -> bool:
        """True when times are shown in UTC: ``zulu`` mode, or ``station`` mode for a station without a known zone."""
        return self.time_mode == "zulu" or (self.time_mode == "station" and self._zone(icao) is None)

    def localize(self, moment: datetime, icao: str | None = None) -> datetime:
        """``moment`` in the zone the time mode asks for."""
        if self.is_zulu(icao):
            return moment.astimezone(UTC)
        zone = self._zone(icao)
        return moment.astimezone(zone) if zone is not None else moment.astimezone()

    def clock(self, moment: datetime | None, icao: str | None = None) -> str:
        """``14:53Z``, or the same moment in station-local or computer-local time per the time mode."""
        if moment is None:
            return self.translator.t(K.TIME_NONE)
        if self.is_zulu(icao):
            return moment.strftime("%H:%MZ")
        shifted = self.localize(moment, icao)
        return f"{shifted:%H:%M} {shifted.tzname() or ''}".strip()
