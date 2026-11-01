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
from wxbrief.i18n import Translator
from wxbrief.i18n.keys import K
from wxbrief.state import StationReports
from wxbrief.ui.context import ViewContext
from wxbrief.ui.fcat import CategoryColors, category_colors
from wxbrief.ui.strip import MINI_STRIP_HOURS, StripCell, is_expired, mini_cells, strip_for
from wxbrief.ui.widgets.station_list import short_conditions
from wxbrief.ui.widgets.taf_timeline import HATCH, OVERLAY_MARK, category_letter, tick_labels

CELL_WIDTH = 2
STRIP_WIDTH = MINI_STRIP_HOURS * CELL_WIDTH


def strip_lines(cells: Sequence[StripCell], colors: CategoryColors, t: Translator) -> tuple[Text, Text]:
    """The cells row and the thin temporary-group row under it, each padded to ``STRIP_WIDTH`` columns."""
    body, overlay = Text(no_wrap=True), Text(no_wrap=True)
    previous = None
    for index, cell in enumerate(cells):
        if cell.becoming:
            worst = cell.worst_category
            foreground = colors.fill_of(worst) if worst is not None and worst != cell.category else None
            body.append(HATCH * CELL_WIDTH, style=colors.style(cell.category, foreground))
        else:
            letter = category_letter(t, cell.category)
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
        super().__init__()
        self.icao = icao

    def on_click(self, event: Click) -> None:
        self.post_message(self.Clicked(self.icao))

    def show(self, entry: StationReports, ctx: ViewContext, now: datetime, *, selected: bool) -> None:
        self.set_class(selected, "-selected")
        palette = ctx.palette
        colors = category_colors(palette)
        glyphs = ctx.glyphs
        metar = entry.metar
        if metar is None:
            mark, mark_style = glyphs.missing, palette.muted
        elif entry.freshness(now) is Freshness.FRESH:
            mark, mark_style = glyphs.fresh, palette.fresh
        else:
            mark, mark_style = glyphs.stale, palette.stale
        station = ctx.station(entry.icao)
        name = station.name if station else (entry.awc_metar.name if entry.awc_metar else None)
        head = Text.assemble((mark, mark_style), " ", (entry.icao, "bold"), " ")
        head.append_text(palette.badge(metar.flight_category if metar else None))
        theirs = ctx.awc_differs(entry)
        if theirs:
            head.append(f" {glyphs.differs}{theirs}", style=palette.stale)
        if name:
            head.append(f" {name}", style=palette.muted)
        conditions = short_conditions(metar) or (ctx.translator.t(K.UI_LIST_NO_REPORT) if metar is None else "")
        lines = [head, Text(conditions, style=palette.muted)]
        taf = entry.taf if isinstance(entry.taf, Taf) else None
        hours = strip_for(taf)[1] if taf is not None else ()
        cells = mini_cells(hours, now)
        if cells:
            lines.append(tick_labels(cells, CELL_WIDTH, ctx, entry.icao, every_cell=False))
            lines.extend(strip_lines(cells, colors, ctx.translator))
        else:
            if is_expired(hours, now):
                key = K.TIMELINE_EXPIRED
            else:  # no forecast at all, or one whose valid period cannot be read: not "no TAF" when there is a TAF
                key = K.TIMELINE_NO_TAF if taf is None else K.TIMELINE_NONE
            lines.append(Text(ctx.translator.t(key), style=palette.muted))
        self.update(Text("\n").join(lines))
