"""The forecast for the period under the timeline cursor, decoded."""

from __future__ import annotations

import textwrap
from datetime import datetime

from rich.style import Style
from rich.text import Text
from textual.widgets import Static

from wxbrief.decode.model import FlightCategory, Taf, Timeline
from wxbrief.decode.timeline import category_of, merge
from wxbrief.i18n.keys import K
from wxbrief.render import phrases
from wxbrief.render.plain import DecodeRow, element_rows
from wxbrief.ui.context import ViewContext
from wxbrief.ui.fcat import CategoryColors, category_colors
from wxbrief.ui.strip import StripCell


def badge(category: FlightCategory | None, colors: CategoryColors) -> Text:
    """`` VFR `` on the category colour."""
    if category is None:
        return Text(" -- ", style="dim")
    return Text(f" {category.value:^4} ", style=colors.style(category) + Style(bold=True))


def rows_text(rows: list[DecodeRow], ctx: ViewContext, colors: CategoryColors, width: int, indent: int = 2) -> Text:
    """Rows as ``Label:  value`` lines with wrapped values hanging under the value column."""
    palette = ctx.palette
    label_width = max((len(row.label) for row in rows), default=0) + 2
    width -= 4  # the scrollbar and a little slack: a line that is one column too long wraps badly
    room = width - indent - label_width
    stacked = room < 28  # a narrow pane: the label gets its own line and the value is indented under it
    lines: list[Text] = []
    for row in rows:
        line = Text(" " * indent)
        if stacked:
            line.append(f"{row.label}:", style=palette.style("wx.label"))
            line.append("\n" + " " * (indent + 2))
            hang, room = indent + 2, max(16, width - indent - 2)
        else:
            line.append(f"{row.label + ':':<{label_width}}", style=palette.style("wx.label"))
            hang = indent + label_width
        if row.category is not None:
            line.append_text(badge(row.category, colors))
            rest = row.value.removeprefix(row.category.value).strip()
            if rest:
                line.append(" " + rest)
        else:
            wrapped = textwrap.wrap(row.value, max(16, room)) or [""]
            line.append(("\n" + " " * hang).join(wrapped), style=palette.style(row.style))
        lines.append(line)
    return Text("\n").join(lines)


class PeriodDetail(Static):
    """The forecast for the cell under the cursor: prevailing conditions, a change under way, temporary groups."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._args: tuple[Taf, Timeline, StripCell | None, ViewContext, str] | None = None

    def show_cell(self, taf: Taf, timeline: Timeline, cell: StripCell | None, ctx: ViewContext, icao: str) -> None:
        self._args = (taf, timeline, cell, ctx, icao)
        self._draw()

    def on_resize(self) -> None:
        if self._args is not None:
            self._draw()

    def _stamp(self, ctx: ViewContext, icao: str, moment: datetime) -> str:
        return f"{ctx.localize(moment, icao):%Y-%m-%d} {ctx.clock(moment, icao)}"

    def _draw(self) -> None:
        assert self._args is not None
        taf, timeline, cell, ctx, icao = self._args
        t = ctx.translator
        if cell is None:
            self.update("")
            return
        colors = category_colors(self.app.current_theme)
        width = self.size.width or 60
        title = Text()
        title.append(
            t.t(K.TIMELINE_SPAN, start=self._stamp(ctx, icao, cell.start), end=ctx.clock(cell.end, icao)),
            style="bold",
        )
        title.append("  ")
        title.append_text(badge(cell.category, colors))
        parts: list[Text] = [title]
        if cell.worst_category is not None and cell.worst_category != cell.category:
            worst = Text(t.t(K.TIMELINE_WORST) + " ", style="dim")
            worst.append_text(badge(cell.worst_category, colors))
            parts.append(worst)

        # Prevailing forecast: one block per group that prevails somewhere in the cell.
        seen: set[int] = set()
        for index in cell.slices:
            item = timeline.slices[index]
            if item.period is None or item.period in seen:
                continue
            header = phrases.describe_change_header(t, taf.periods[item.period])
            text = (
                t.t(K.TIMELINE_THEN, time=ctx.clock(item.start, icao), header=header)
                if seen
                else t.t(K.TIMELINE_PREVAILING, header=header)
            )
            seen.add(item.period)
            parts.append(Text(text, style="bold"))
            parts.append(rows_text(element_rows(item.prevailing, item.category, t, ctx.units), ctx, colors, width))

        # A change under way (BECMG), then temporary groups, each once.
        becoming: set[int] = set()
        overlays: set[int] = set()
        for index in cell.slices:
            item = timeline.slices[index]
            if item.becoming_index is not None and item.becoming_index not in becoming:
                becoming.add(item.becoming_index)
                group = taf.periods[item.becoming_index]
                category = category_of(merge(item.prevailing, group.elements))
                parts.append(Text(phrases.describe_change_header(t, group), style="bold"))
                parts.append(rows_text(element_rows(group.elements, category, t, ctx.units), ctx, colors, width))
            for overlay in item.overlays:
                if overlay.index in overlays:
                    continue
                overlays.add(overlay.index)
                group = taf.periods[overlay.index]
                parts.append(Text(phrases.describe_change_header(t, group), style="bold"))
                rows = element_rows(overlay.elements, overlay.category, t, ctx.units)
                parts.append(rows_text(rows, ctx, colors, width))
        self.update(Text("\n").join(parts))
