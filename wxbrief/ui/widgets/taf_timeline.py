"""The TAF timeline: a strip of hourly cells over the valid period.

Rows, top to bottom: tick labels (hours in the chosen time mode), the cells (background = prevailing flight category,
hatched while a ``BECMG`` is under way), a thin row for temporary groups (coloured by their worst case), the cursor and
a legend. The mouse (hover or click) and ``Left``/``Right`` move the cursor; ``TafTimeline.Moved`` tells the detail
pane which period to describe. In a narrow terminal, or when hourly cells would not fit, a cell spans three hours.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from rich.style import Style
from rich.text import Text
from textual.events import Click, MouseMove, Resize
from textual.message import Message
from textual.widget import Widget

from wxbrief.decode.model import FlightCategory, Taf, Timeline, TimelineHour
from wxbrief.i18n import Translator
from wxbrief.i18n.keys import K
from wxbrief.ui.bindings import bind, localize
from wxbrief.ui.context import ViewContext
from wxbrief.ui.fcat import category_colors
from wxbrief.ui.strip import StripCell, group_cells, hour_step, strip_for

HATCH = "▒"
OVERLAY_MARK = "▀"
CURSOR_MARK = "▲"
LETTER_KEYS = {
    FlightCategory.VFR: K.TIMELINE_LETTER_VFR,
    FlightCategory.MVFR: K.TIMELINE_LETTER_MVFR,
    FlightCategory.IFR: K.TIMELINE_LETTER_IFR,
    FlightCategory.LIFR: K.TIMELINE_LETTER_LIFR,
}


def category_letter(t: Translator, category: FlightCategory | None) -> str:
    """The one-letter mark of a flight category in a strip cell, ``?`` when there is none."""
    return t.t(LETTER_KEYS[category]) if category is not None else "?"


def cell_width(step: int) -> int:
    """Columns per cell: two for an hour, four for three hours."""
    return 2 if step == 1 else 4


def tick_labels(cells: Sequence[StripCell], width: int, ctx: ViewContext, icao: str, *, every_cell: bool) -> Text:
    """The hour labels above a strip of ``width``-column cells, then the zone name(s) in the order they occur.

    A label sits over a cell that starts on a multiple of three hours (every cell when ``every_cell``, for strips
    of merged hours); several zones appear when a daylight-saving change falls inside the strip.
    """
    ticks = Text(no_wrap=True)
    label_end = 0
    zones: list[str] = []
    for index, cell in enumerate(cells):
        local = ctx.localize(cell.start, icao)
        name = ctx.translator.t(K.TIME_ZONE_UTC) if ctx.is_zulu(icao) else (local.tzname() or "")
        if name and name not in zones:
            zones.append(name)
        position = index * width
        hour = f"{local:%H}" if local.minute == 0 else f"{local:%H:%M}"  # half-hour zones such as +5:30
        if (every_cell or local.hour % 3 == 0) and position >= label_end:
            ticks.append(" " * (position - len(ticks.plain)))
            ticks.append(hour, style=ctx.palette.muted)
            label_end = position + len(hour) + 1
    ticks.append("  " + "/".join(zones), style=ctx.palette.muted)
    return ticks


class TafTimeline(Widget, can_focus=True):
    """Hourly flight-category cells for one TAF."""

    BINDINGS = [
        bind("left", "move(-1)", K.UI_BINDING_EARLIER, show=False),
        bind("right", "move(1)", K.UI_BINDING_LATER, show=False),
        bind("home", "to_start", K.UI_BINDING_FIRST, show=False),
        bind("end", "to_end", K.UI_BINDING_LAST, show=False),
    ]

    class Moved(Message):
        """The cursor is on another cell (or the TAF changed): ``cell`` is the one now selected."""

        def __init__(
            self, timeline: TafTimeline, cell: StripCell | None, taf: Taf | None, data: Timeline, icao: str
        ) -> None:
            super().__init__()
            self.timeline = timeline
            self.cell = cell
            # a snapshot: the timeline may already hold another station's forecast when this message is handled
            self.taf = taf
            self.data = data
            self.icao = icao

    def on_mount(self) -> None:
        localize(self)

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.taf: Taf | None = None
        self.timeline = Timeline(None, None, ())
        self.hours: tuple[TimelineHour, ...] = ()
        self.cells: tuple[StripCell, ...] = ()
        self.step = 1
        self.cursor = 0  # index into ``cells``
        self._cursor_hour = 0  # index into ``hours``: survives a change of step
        self._ctx: ViewContext | None = None
        self._icao = ""
        self._key: tuple[str, str] | None = None
        self._chosen_hour: int | None = None  # the hour the user chose (key or click); None: follow the clock

    # --- data ------------------------------------------------------------------------------------------------------

    def set_taf(self, taf: Taf | None, ctx: ViewContext, icao: str, now: datetime) -> bool:
        """Show ``taf``; returns whether there is anything to draw. For an unchanged TAF the cursor returns to the hour
        the user chose, and until they choose one, to the current hour."""
        self._ctx = ctx
        self._icao = icao
        key = (icao, taf.raw) if taf is not None else None
        fresh = key != self._key
        self._key = key
        self.taf = taf
        if taf is None:
            self.timeline, self.hours = Timeline(None, None, ()), ()
        else:
            self.timeline, self.hours = strip_for(taf)
        self._rebuild()
        if fresh:
            self._chosen_hour = None
        at = next((i for i, hour in enumerate(self.hours) if hour.start <= now < hour.end), 0)
        # a hover only previewed another cell: the cursor goes back to the chosen hour, or the current one
        self._cursor_hour = self._chosen_hour if self._chosen_hour is not None else at
        self._cursor_hour = min(self._cursor_hour, max(0, len(self.hours) - 1))
        self.cursor = self._cell_of_hour(self._cursor_hour)
        self._announce()
        self.refresh()
        return bool(self.cells)

    @property
    def selected(self) -> StripCell | None:
        return self.cells[self.cursor] if 0 <= self.cursor < len(self.cells) else None

    def _is_narrow(self) -> bool:
        try:
            return self.screen.has_class("-narrow")
        except Exception:
            return False

    def _rebuild(self) -> None:
        self.step = hour_step(len(self.hours), self.size.width, narrow=self._is_narrow())
        self.cells = group_cells(self.hours, self.step)
        self.cursor = min(self._cell_of_hour(self._cursor_hour), max(0, len(self.cells) - 1))

    def _cell_of_hour(self, hour: int) -> int:
        return hour // self.step

    def _announce(self) -> None:
        self.post_message(self.Moved(self, self.selected, self.taf, self.timeline, self._icao))

    # --- cursor ----------------------------------------------------------------------------------------------------

    def move_to(self, index: int, *, chosen: bool = True) -> None:
        """Put the cursor on a cell. A hover only previews it (chosen=False): the chosen hour, or the clock when
        none is chosen, comes back at the next refresh."""
        if not self.cells:
            return
        index = max(0, min(index, len(self.cells) - 1))
        if chosen:  # even when the pointer was already there: a click on the hovered cell is still a choice
            self._chosen_hour = self.cells[index].hours[0]
        if index == self.cursor:
            return
        self.cursor = index
        self._cursor_hour = self.cells[index].hours[0]
        self._announce()
        self.refresh()

    def action_move(self, offset: int) -> None:
        self.move_to(self.cursor + offset)

    def action_to_start(self) -> None:
        self.move_to(0)

    def action_to_end(self) -> None:
        self.move_to(len(self.cells) - 1)

    def _index_at(self, x: int) -> int | None:
        index = x // cell_width(self.step)
        return index if 0 <= index < len(self.cells) else None

    def on_mouse_move(self, event: MouseMove) -> None:
        index = self._index_at(event.x)
        if index is not None:
            self.move_to(index, chosen=False)

    def on_click(self, event: Click) -> None:
        index = self._index_at(event.x)
        if index is not None:
            self.move_to(index)

    def on_resize(self, event: Resize) -> None:
        if not self.hours:
            return
        before = (self.step, self.cursor)
        self._rebuild()
        if (self.step, self.cursor) != before:
            self._announce()
        self.refresh()

    # --- drawing ---------------------------------------------------------------------------------------------------

    def render(self) -> Text:
        ctx = self._ctx
        if ctx is None or not self.cells:
            return Text("")
        colors = category_colors(ctx.palette)
        muted = ctx.palette.muted
        width = cell_width(self.step)
        ticks = tick_labels(self.cells, width, ctx, self._icao, every_cell=self.step > 1)
        body, overlay, cursor = Text(no_wrap=True), Text(no_wrap=True), Text(no_wrap=True)
        previous: FlightCategory | None = None
        for index, cell in enumerate(self.cells):
            if cell.becoming:
                worst = cell.worst_category
                foreground = colors.fill_of(worst) if worst is not None and worst != cell.category else None
                body.append(HATCH * width, style=colors.style(cell.category, foreground))
            else:
                letter = category_letter(ctx.translator, cell.category)
                mark = letter if cell.category != previous or index == 0 else " "
                body.append(mark.ljust(width), style=colors.style(cell.category))
            previous = cell.category
            if cell.overlay:
                overlay.append(OVERLAY_MARK * width, style=Style(color=colors.fill_of(cell.overlay_category)))
            else:
                overlay.append(" " * width)
        cursor.append(" " * (self.cursor * width))
        cursor.append(CURSOR_MARK.ljust(width), style="bold")
        legend = Text(no_wrap=True)
        legend.append(HATCH, style=muted)
        legend.append(f" {ctx.translator.t(K.TIMELINE_LEGEND_BECOMING)}   ", style=muted)
        legend.append(OVERLAY_MARK, style=muted)
        legend.append(f" {ctx.translator.t(K.TIMELINE_LEGEND_TEMPORARY)}", style=muted)
        return Text("\n", no_wrap=True, overflow="crop").join([ticks, body, overlay, cursor, legend])
