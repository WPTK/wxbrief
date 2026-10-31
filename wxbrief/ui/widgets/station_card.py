"""A station as a card: code, category, wind and visibility, and a 12-cell strip of the next twelve forecast hours."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from rich.style import Style
from rich.text import Text
from textual.events import Click
from textual.message import Message
from textual.widgets import Static

from wxbrief.data.poll import Freshness
from wxbrief.decode.model import Taf
from wxbrief.i18n.keys import K
from wxbrief.state import StationReports
from wxbrief.ui.context import ViewContext
from wxbrief.ui.fcat import CategoryColors, category_colors
from wxbrief.ui.strip import MINI_STRIP_HOURS, StripCell, mini_cells, strip_for
from wxbrief.ui.widgets.period_detail import badge
from wxbrief.ui.widgets.station_list import short_conditions
from wxbrief.ui.widgets.taf_timeline import HATCH, LETTERS, OVERLAY_MARK

CELL_WIDTH = 2
STRIP_WIDTH = MINI_STRIP_HOURS * CELL_WIDTH


def strip_lines(cells: Sequence[StripCell], colors: CategoryColors) -> tuple[Text, Text]:
    """The cells row and the thin temporary-group row under it, each padded to ``STRIP_WIDTH`` columns."""
    body, overlay = Text(no_wrap=True), Text(no_wrap=True)
    previous = None
    for index, cell in enumerate(cells):
        if cell.becoming:
            worst = cell.worst_category
            foreground = colors.fill_of(worst) if worst is not None and worst != cell.category else None
            body.append(HATCH * CELL_WIDTH, style=colors.style(cell.category, foreground))
        else:
            letter = LETTERS.get(cell.category, "?") if cell.category is not None else "?"
            mark = letter if index == 0 or cell.category != previous else " "
            body.append(mark.ljust(CELL_WIDTH), style=colors.style(cell.category))
        previous = cell.category
        if cell.overlay:
            overlay.append(OVERLAY_MARK * CELL_WIDTH, style=Style(color=colors.fill_of(cell.overlay_category)))
        else:
            overlay.append(" " * CELL_WIDTH)
    return body, overlay


class StationCard(Static):
    """One station in the grid layout. Clicking it selects it; clicking the selected card opens its detail."""

    class Clicked(Message):
        def __init__(self, icao: str) -> None:
            super().__init__()
            self.icao = icao

    def __init__(self, icao: str) -> None:
        super().__init__(id=f"card-{icao}")
        self.icao = icao

    def on_click(self, event: Click) -> None:
        self.post_message(self.Clicked(self.icao))

    def show(self, entry: StationReports, ctx: ViewContext, now: datetime, *, selected: bool) -> None:
        self.set_class(selected, "-selected")
        colors = category_colors(self.app.current_theme)
        glyphs = ctx.glyphs
        metar = entry.metar
        if metar is None:
            mark, mark_style = glyphs.missing, "dim"
        elif entry.freshness(now) is Freshness.FRESH:
            mark, mark_style = glyphs.fresh, "green"
        else:
            mark, mark_style = glyphs.stale, "yellow"
        station = ctx.station(entry.icao)
        name = station.name if station else (entry.awc_metar.name if entry.awc_metar else None)
        head = Text.assemble((mark, mark_style), " ", (entry.icao, "bold"), " ")
        head.append_text(badge(metar.flight_category if metar else None, colors))
        if name:
            head.append(f" {name}", style="dim")
        head.no_wrap = True
        head.overflow = "ellipsis"
        conditions = short_conditions(metar) or ("no report" if metar is None else "")
        lines = [head, Text(conditions, style="dim", no_wrap=True, overflow="ellipsis")]
        taf = entry.taf if isinstance(entry.taf, Taf) else None
        cells = mini_cells(strip_for(taf)[1], now) if taf is not None else ()
        if cells:
            lines.extend(strip_lines(cells, colors))
        else:
            lines.append(Text(ctx.translator.t(K.TIMELINE_NO_TAF), style="dim"))
        self.update(Text("\n").join(lines))
