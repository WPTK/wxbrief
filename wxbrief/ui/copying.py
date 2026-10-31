"""The copy actions (``c``, ``C``, ``y``): what the briefing screen and the station detail screen share."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from textual.screen import Screen

from wxbrief.clipboard import copy_text
from wxbrief.decode.model import Metar, Taf
from wxbrief.decode.units import UnitsMode
from wxbrief.getcmd import local_hour
from wxbrief.i18n.keys import K
from wxbrief.render.discord import render_discord
from wxbrief.state import StationReports

if TYPE_CHECKING:
    from wxbrief.app import WxBriefApp


class CopyActions(Screen[None]):
    """Mixin for a screen with a ``current()`` station: gives it the three copy actions."""

    def current(self) -> StationReports | None:
        raise NotImplementedError

    def _discord(self, report: Metar | Taf, entry: StationReports) -> str:
        ctx = cast("WxBriefApp", self.app).ctx
        station = ctx.station(entry.icao)
        name = station.name if station else None
        hour = None
        if isinstance(report, Metar) and entry.awc_metar is not None:
            hour = local_hour(station.tz if station else None, entry.awc_metar.observed)
        units = ctx.units if ctx.units is not UnitsMode.MIXED else UnitsMode.US
        return render_discord(report, ctx.translator, units, station_name=name, local_hour=hour)

    def action_copy_metar(self) -> None:
        t = cast("WxBriefApp", self.app).ctx.translator
        entry = self.current()
        if entry is None or entry.metar is None:
            self.notify(t.t(K.UI_TOAST_NO_METAR_TO_COPY), severity="warning")
            return
        copy_text(self.app, self._discord(entry.metar, entry), t.t(K.UI_CLIPBOARD_METAR, icao=entry.icao), t)

    def action_copy_both(self) -> None:
        t = cast("WxBriefApp", self.app).ctx.translator
        entry = self.current()
        if entry is None or (entry.metar is None and entry.taf is None):
            self.notify(t.t(K.UI_TOAST_NOTHING_TO_COPY), severity="warning")
            return
        blocks = [self._discord(report, entry) for report in (entry.metar, entry.taf) if report is not None]
        copy_text(self.app, "\n\n".join(blocks), t.t(K.UI_CLIPBOARD_BOTH, icao=entry.icao), t)

    def action_copy_raw(self) -> None:
        t = cast("WxBriefApp", self.app).ctx.translator
        entry = self.current()
        raws = [report.raw for report in (entry.metar, entry.taf) if report is not None] if entry else []
        if not entry or not raws:
            self.notify(t.t(K.UI_TOAST_NOTHING_TO_COPY), severity="warning")
            return
        copy_text(self.app, "\n".join(raws), t.t(K.UI_CLIPBOARD_RAW, icao=entry.icao), t)
