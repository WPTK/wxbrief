"""The forecast for the period under the timeline cursor, decoded."""

from __future__ import annotations

from datetime import datetime

from rich.text import Text
from textual.widgets import Static

from wxbrief.decode.model import ChangeType, Taf, TafPeriod, Timeline
from wxbrief.decode.timeline import category_of, merge
from wxbrief.i18n.keys import K
from wxbrief.render import phrases
from wxbrief.render.plain import DecodeRow, element_rows
from wxbrief.ui.context import ViewContext
from wxbrief.ui.strip import StripCell
from wxbrief.ui.wrap import wrap

ROW_INDENT = 1  # the decoded table's cell padding: every label in the detail pane starts at this column
ROW_LABEL_PAD = 3  # a label's colon and the two columns of cell padding before the value


def rows_text(rows: list[DecodeRow], ctx: ViewContext, width: int, indent: int = ROW_INDENT, labels: int = 0) -> Text:
    """Rows as ``Label:  value`` lines with wrapped values hanging under the value column.

    ``labels`` is the longest label anywhere in the pane, so every value starts in the same column as the decoded
    table's (its cell padding is one column each side: the value column starts ``labels + 3`` after the label's start).
    """
    palette = ctx.palette
    label_width = max(labels, max((len(row.label) for row in rows), default=0)) + ROW_LABEL_PAD
    width -= 1  # a line that is one column too long wraps badly
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
            badge = palette.badge(row.category)
            line.append_text(badge)
            rest = row.value.removeprefix(row.category.value).strip()
            if rest:  # the words hang under themselves, not under the badge
                pad = len(badge.plain) + 1
                line.append(" " + ("\n" + " " * (hang + pad)).join(wrap(rest, max(16, room - pad))))
        else:
            line.append(("\n" + " " * hang).join(wrap(row.value, max(16, room))), style=palette.style(row.style))
        lines.append(line)
    return Text("\n").join(lines)


def heading(text: str, width: int) -> Text:
    """A bold line of text; when it wraps the next lines hang two columns in."""
    return Text("\n  ".join(wrap(text, width - 1, hang=2)), style="bold")


class RowBlocks(Static):
    """Blocks of ``Label: value`` rows, each with an optional bold title, wrapped to this widget's own width."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._blocks: list[tuple[str | None, list[DecodeRow]]] = []
        self._ctx: ViewContext | None = None
        self._labels = 0

    def set_blocks(
        self, blocks: list[tuple[str | None, list[DecodeRow]]], ctx: ViewContext, *, labels: int = 0
    ) -> None:
        self._blocks, self._ctx, self._labels = blocks, ctx, labels
        self._draw()

    def on_resize(self) -> None:
        self._draw()  # the width is only known after layout, and changes with the terminal

    def _draw(self) -> None:
        if self._ctx is None:
            return
        width = self.size.width or 70
        parts: list[Text] = []
        for title, rows in self._blocks:
            if title:
                parts.append(heading(title, width))
            parts.append(rows_text(rows, self._ctx, width, labels=self._labels))
        self.update(Text("\n").join(parts))


class PeriodDetail(Static):
    """The forecast for the cell under the cursor: prevailing conditions, a change under way, temporary groups."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._args: tuple[Taf, Timeline, StripCell | None, ViewContext, str] | None = None
        self.labels = 0  # the longest label in the pane, set by the pane (see rows_text)

    def show_cell(self, taf: Taf, timeline: Timeline, cell: StripCell | None, ctx: ViewContext, icao: str) -> None:
        self._args = (taf, timeline, cell, ctx, icao)
        self._draw()

    def on_resize(self) -> None:
        if self._args is not None:
            self._draw()

    def _rows(self, rows: list[DecodeRow], ctx: ViewContext, width: int) -> Text:
        return rows_text(rows, ctx, width, labels=self.labels)

    def _stamp(self, ctx: ViewContext, icao: str, moment: datetime) -> str:
        return f"{ctx.localize(moment, icao):%Y-%m-%d} {ctx.clock(moment, icao)}"

    def _span(self, ctx: ViewContext, icao: str, period: TafPeriod) -> str:
        """The group's own time span in the time mode, so a header never mixes local and UTC times."""
        t = ctx.translator
        end = period.becoming_end if period.change is ChangeType.BECMG else period.end
        if period.start is None:
            return t.t(K.TAF_SPAN_NONE)
        first = self._stamp(ctx, icao, period.start)
        if end is None:
            return t.t(K.TAF_SPAN_START_ONLY, start=first)
        same_day = ctx.localize(end, icao).date() == ctx.localize(period.start, icao).date()
        return t.t(K.TAF_SPAN_BOTH, start=first, end=ctx.clock(end, icao) if same_day else self._stamp(ctx, icao, end))

    def _header(self, ctx: ViewContext, icao: str, period: TafPeriod) -> str:
        return phrases.describe_change_header(ctx.translator, period, self._span(ctx, icao, period))

    def _draw(self) -> None:
        assert self._args is not None
        taf, timeline, cell, ctx, icao = self._args
        t = ctx.translator
        if cell is None:
            self.update("")
            return
        width = self.size.width or 60
        title = Text()
        title.append(
            t.t(K.TIMELINE_SPAN, start=self._stamp(ctx, icao, cell.start), end=ctx.clock(cell.end, icao)),
            style="bold",
        )
        title.append("  ")
        title.append_text(ctx.palette.badge(cell.category))
        parts: list[Text] = [title]
        if cell.worst_category is not None and cell.worst_category != cell.category:
            worst = Text(t.t(K.TIMELINE_WORST) + " ", style=ctx.palette.muted)
            worst.append_text(ctx.palette.badge(cell.worst_category))
            parts.append(worst)

        # Prevailing forecast: one block per group that prevails somewhere in the cell.
        seen: set[int] = set()
        for index in cell.slices:
            item = timeline.slices[index]
            if item.period is None or item.period in seen:
                continue
            header = self._header(ctx, icao, taf.periods[item.period])
            text = (
                t.t(K.TIMELINE_THEN, time=ctx.clock(item.start, icao), header=header)
                if seen
                else t.t(K.TIMELINE_PREVAILING, header=header)
            )
            seen.add(item.period)
            parts.append(heading(text, width))
            parts.append(self._rows(element_rows(item.prevailing, item.category, t, ctx.units), ctx, width))

        # A change under way (BECMG), then temporary groups, each once.
        becoming: set[int] = set()
        overlays: set[int] = set()
        for index in cell.slices:
            item = timeline.slices[index]
            if item.becoming_index is not None and item.becoming_index not in becoming:
                becoming.add(item.becoming_index)
                group = taf.periods[item.becoming_index]
                category = category_of(merge(item.prevailing, group.elements))
                parts.append(heading(self._header(ctx, icao, group), width))
                parts.append(self._rows(element_rows(group.elements, category, t, ctx.units), ctx, width))
            for overlay in item.overlays:
                if overlay.index in overlays:
                    continue
                overlays.add(overlay.index)
                group = taf.periods[overlay.index]
                parts.append(heading(self._header(ctx, icao, group), width))
                rows = element_rows(overlay.elements, overlay.category, t, ctx.units)
                parts.append(self._rows(rows, ctx, width))
        self.update(Text("\n").join(parts))
