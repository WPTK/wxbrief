"""The detail pane: header, flag chips, raw report, decoded table, collapsible remarks and a plain TAF block."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.events import Resize
from textual.widget import Widget
from textual.widgets import Collapsible, DataTable, Label, Static

from wxbrief.data.poll import Freshness
from wxbrief.decode.model import Metar, Taf
from wxbrief.i18n import Translator
from wxbrief.i18n.keys import K
from wxbrief.render import phrases
from wxbrief.render.plain import DecodeBlock, DecodeRow, decode_rows, taf_blocks, taf_header_rows, warning_lines
from wxbrief.state import StationReports
from wxbrief.ui.bindings import bind, localize
from wxbrief.ui.context import ViewContext
from wxbrief.ui.strip import is_expired
from wxbrief.ui.widgets.period_detail import PeriodDetail, RowBlocks
from wxbrief.ui.widgets.status_bar import STATE_KEYS
from wxbrief.ui.widgets.taf_timeline import TafTimeline
from wxbrief.ui.wrap import wrap


def age_text(delta: timedelta, t: Translator) -> str:
    """``12 min``, ``3 h 05 min``, ``2 d 4 h``: how long ago, never negative."""
    minutes = max(0, int(delta.total_seconds() // 60))
    if minutes < 60:
        return t.t(K.UI_AGE_MINUTES, minutes=minutes)
    hours, rest = divmod(minutes, 60)
    if hours < 24:
        return t.t(K.UI_AGE_HOURS, hours=hours, minutes=rest)
    days, hours = divmod(hours, 24)
    return t.t(K.UI_AGE_DAYS, days=days, hours=hours)


class StationHeader(Static):
    """Station code and name, flight category badge, observation time and how fresh it is."""

    def show(self, entry: StationReports, ctx: ViewContext, now: datetime) -> None:
        palette = ctx.palette
        station = ctx.station(entry.icao)
        name = station.name if station else (entry.awc_metar.name if entry.awc_metar else None)
        place = ", ".join(p for p in (station.state, station.country) if p) if station else ""
        metar = entry.metar
        title = Text.assemble((entry.icao, palette.style("wx.station") + palette.style("wx.label")))
        if name:
            title.append(f"  {name}")
        if place:
            title.append(f" ({place})", style=palette.muted)
        title.append("  ")
        title.append_text(palette.badge(metar.flight_category if metar else None))
        theirs = ctx.awc_differs(entry)
        if theirs:  # AWC's own category for this report is not the one we computed
            title.append(f" {ctx.glyphs.differs}{theirs}", style=palette.stale)
        lines = [title]
        if entry.awc_metar and entry.awc_metar.observed:
            observed = entry.awc_metar.observed
            state = entry.freshness(now)
            mark = ctx.glyphs.fresh if state is Freshness.FRESH else ctx.glyphs.stale
            style = ctx.palette.fresh if state is Freshness.FRESH else ctx.palette.stale
            t = ctx.translator
            when = t.t(K.UI_DETAIL_OBSERVED_AGO, time=ctx.clock(observed, entry.icao), age=age_text(now - observed, t))
            line = Text.assemble(f"{when}  ", (f"{mark} {t.t(STATE_KEYS[state])}", style))
            if entry.from_cache and entry.updated is not None:
                cached = t.t(K.UI_DETAIL_CACHED_AGO, age=age_text(now - entry.updated, t))
                line.append(f"  {cached}", style=ctx.palette.muted)
            lines.append(line)
        elif metar is None:  # nothing held: not fetched yet, the fetch failed, or the station has none
            lines.append(Text(ctx.translator.t(K.UI_DETAIL_NO_METAR), style=ctx.palette.stale))
        self.update(Text("\n").join(lines))


class FlagsRow(Static):
    """The report's flags as chips (``CB``, ``Gusts``, ``Low ceiling`` ...)."""

    def show(self, metar: Metar | None, ctx: ViewContext) -> None:
        flags = metar.flags if metar else ()
        text = Text()
        for flag in flags:
            if text:
                text.append(" ")
            text.append(f" {phrases.describe_flag(ctx.translator, flag)} ", style="bold reverse")
        self.update(text)
        self.display = bool(flags)


class RawReport(Static):
    """The raw METAR and TAF text, each token coloured by its group."""

    def show(self, entry: StationReports, ctx: ViewContext) -> None:
        parts: list[Text] = []
        if entry.metar is not None:
            parts.append(ctx.palette.raw_text(entry.metar))
        if entry.taf is not None:
            parts.append(ctx.palette.raw_text(entry.taf))
        empty = Text(ctx.translator.t(K.UI_DETAIL_NO_REPORT), style=ctx.palette.muted)
        self.update(Text("\n\n").join(parts) if parts else empty)


class DecodedTable(DataTable[Text]):
    """Two columns, label and value; values wrap to the width of the pane."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(show_header=False, cursor_type="none", zebra_stripes=False, **kwargs)
        self._rows: list[DecodeRow] = []
        self._ctx: ViewContext | None = None
        self._labels = 0  # the longest label in the pane (see rows_text)

    def set_rows(self, rows: list[DecodeRow], ctx: ViewContext, labels: int = 0) -> None:
        self._rows = rows
        self._ctx = ctx
        self._labels = labels
        self._fill()

    def _fill(self) -> None:
        ctx = self._ctx
        self.clear(columns=True)  # column widths are set from the pane width below, never left over from an earlier one
        if ctx is None or not self._rows:
            return
        palette = ctx.palette
        label_width = max(self._labels, max(len(row.label) for row in self._rows)) + 1
        width = max(8, self.size.width - label_width - 6)  # each column has a cell padding of 1 on both sides
        self.add_column("Field", width=label_width)
        self.add_column("Value", width=width)
        for row in self._rows:
            if row.category is not None:
                code = row.category.value
                badge = palette.badge(row.category)
                indent = len(badge.plain) + 1
                text = row.value.removeprefix(code).strip()
                if width - indent < 12:  # too narrow for a hanging indent: the badge gets its own line
                    value = Text.assemble(badge, "\n", "\n".join(wrap(text, width)))
                else:
                    lines = wrap(text, width - indent)
                    value = Text.assemble(badge, " ", ("\n" + " " * indent).join(lines))
            else:
                wrapped = "\n".join(wrap(row.value, width))
                value = Text(wrapped, style=palette.style(row.style))
            self.add_row(Text(row.label, style=palette.style("wx.label")), value, height=None)

    def on_resize(self, event: Resize) -> None:
        if self._rows:
            self._fill()


class DetailPane(VerticalScroll):
    """Everything known about the selected station."""

    can_focus = True
    BINDINGS = [
        bind("1", "jump('raw')", K.UI_BINDING_JUMP_RAW),
        bind("2", "jump('decoded')", K.UI_BINDING_JUMP_DECODED),
        bind("3", "jump('taf')", K.UI_BINDING_JUMP_TAF),
        bind("left", "timeline(-1)", K.UI_BINDING_EARLIER, show=False),
        bind("right", "timeline(1)", K.UI_BINDING_LATER, show=False),
        bind("c", "screen.copy_metar", K.UI_BINDING_COPY_METAR),
        bind("a", "screen.add_station", K.UI_BINDING_ADD_STATION),  # the list is hidden on a narrow terminal
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._entry: StationReports | None = None
        self._ctx: ViewContext | None = None

    def compose(self) -> ComposeResult:
        yield Static(id="placeholder")  # the text is set in show(), in the language in use
        yield StationHeader(id="header")
        yield FlagsRow(id="flags")
        yield Label(classes="section", id="raw-title")
        yield RawReport(id="raw")
        yield Label(classes="section", id="decoded-title")
        yield DecodedTable(id="decoded")
        with Collapsible(id="remarks-box", collapsed=True):
            yield Static(id="remarks")
        yield Label(classes="section", id="taf-title")
        yield RowBlocks(id="taf-summary")
        yield Static(id="taf-note")
        yield TafTimeline(id="timeline")
        yield PeriodDetail(id="period")
        with Collapsible(id="taf-groups-box", collapsed=True):
            yield RowBlocks(id="taf-groups")
        yield Static(id="warnings")

    def on_mount(self) -> None:
        localize(self)
        self._set_visible(False)

    def _set_visible(self, shown: bool) -> None:
        self.query_one("#placeholder").display = not shown
        for child in self.children:
            if child.id != "placeholder":
                child.display = shown

    def show(self, entry: StationReports | None, ctx: ViewContext, now: datetime) -> None:
        previous = self._entry.icao if self._entry is not None else None
        self._entry, self._ctx = entry, ctx
        t = ctx.translator
        self.query_one("#placeholder", Static).update(t.t(K.UI_DETAIL_NO_STATIONS))
        if entry is None or entry.icao != previous:
            self.scroll_home(animate=False)  # another station starts at its own header, never mid-way down the last one
            self._release_focus(self)  # a widget now below the fold must not keep the keyboard
        if entry is None:
            self._set_visible(False)
            return
        self._set_visible(True)
        self.query_one("#raw-title", Label).update(t.t(K.UI_SECTION_RAW))
        self.query_one("#decoded-title", Label).update(t.t(K.UI_SECTION_DECODED))
        self.query_one("#taf-title", Label).update(t.t(K.UI_SECTION_FORECAST))
        metar = entry.metar
        self.query_one(StationHeader).show(entry, ctx, now)
        self.query_one(FlagsRow).show(metar, ctx)
        self.query_one(RawReport).show(entry, ctx)

        remark_labels = {t.t(K.LABEL_REMARK), t.t(K.LABEL_REMARKS)}
        skipped = remark_labels | {t.t(K.LABEL_FLAGS), t.t(K.LABEL_SUMMARY)}  # the summary restates the rows around it
        rows = decode_rows(metar, t, ctx.units) if metar else []
        decoded = [r for r in rows if r.label not in skipped]
        taf_rows, blocks = self._taf_rows(entry, ctx)
        labels = max((len(r.label) for r in (*decoded, *taf_rows, *(r for b in blocks for r in b.rows))), default=0)
        self.query_one(PeriodDetail).labels = labels
        self.query_one(DecodedTable).set_rows(decoded, ctx, labels)
        table = self.query_one(DecodedTable)
        if metar is None:
            self._release_focus(table)
        self.query_one("#decoded-title").display = metar is not None
        table.display = metar is not None
        remarks = [r for r in rows if r.label in remark_labels]
        box = self.query_one("#remarks-box", Collapsible)
        if not remarks:
            self._release_focus(box)
        box.display = bool(remarks)
        box.title = t.t(K.UI_SECTION_REMARKS, n=len(remarks))
        palette = ctx.palette
        self.query_one("#remarks", Static).update(
            Text("\n").join(Text(r.value, style=palette.style(r.style)) for r in remarks)
        )

        self._show_taf(entry, ctx, now, taf_rows, blocks, labels)

        warnings = warning_lines(metar, t) if metar else []
        warn_box = self.query_one("#warnings", Static)
        warn_box.display = bool(warnings)
        warn_box.update(Text("\n".join(warnings), style=palette.style("wx.warning")))

    @staticmethod
    def _taf_rows(entry: StationReports, ctx: ViewContext) -> tuple[list[DecodeRow], list[DecodeBlock]]:
        """The forecast header rows and the blocks of every group (none without a forecast)."""
        taf = entry.taf if isinstance(entry.taf, Taf) else None
        if taf is None:
            return [], []
        t = ctx.translator
        skipped = {t.t(K.LABEL_STATION), t.t(K.LABEL_REPORT), t.t(K.LABEL_FLAGS)}
        rows = [row for row in taf_header_rows(taf, t, ctx.units) if row.label not in skipped]
        return rows, taf_blocks(taf, t, ctx.units)

    def _show_taf(
        self,
        entry: StationReports,
        ctx: ViewContext,
        now: datetime,
        rows: list[DecodeRow],
        blocks: list[DecodeBlock],
        labels: int,
    ) -> None:
        """The forecast section: summary, timeline with the period under the cursor, and every group in plain words."""
        taf = entry.taf if isinstance(entry.taf, Taf) else None
        t = ctx.translator
        shown = taf is not None
        if not shown:
            self._release_focus(self.query_one("#taf-groups-box"))
        for selector in ("#taf-title", "#taf-summary", "#taf-groups-box"):
            self.query_one(selector).display = shown
        timeline = self.query_one(TafTimeline)
        period = self.query_one(PeriodDetail)
        note = self.query_one("#taf-note", Static)
        if taf is None:
            timeline.display = period.display = note.display = False
            timeline.set_taf(None, ctx, entry.icao, now)
            self._release_focus(timeline)
            return
        self.query_one("#taf-summary", RowBlocks).set_blocks([(None, rows)], ctx, labels=labels)
        self.query_one("#taf-groups-box", Collapsible).title = t.t(K.UI_SECTION_GROUPS, n=len(blocks))
        self.query_one("#taf-groups", RowBlocks).set_blocks([(b.title, b.rows) for b in blocks], ctx, labels=labels)
        drawn = timeline.set_taf(taf, ctx, entry.icao, now)
        expired = is_expired(timeline.hours, now)  # a lapsed forecast is not "Prevailing ...": say so instead
        drawn = drawn and not expired
        timeline.display = period.display = drawn
        note.display = not drawn
        key = K.TIMELINE_CANCELLED if taf.cancelled else K.TIMELINE_EXPIRED if expired else K.TIMELINE_NONE
        note.update(Text(t.t(key), style=ctx.palette.muted))
        if not drawn:
            period.update("")
            self._release_focus(timeline)

    def action_timeline(self, offset: int) -> None:
        """Left/Right on the pane move the forecast cursor, as help says."""
        timeline = self.query_one(TafTimeline)
        if timeline.display:
            timeline.scroll_visible(animate=False)  # the key must show what it moved, not pin an off-screen cursor
            timeline.action_move(offset)

    def _release_focus(self, hidden: Widget) -> None:
        """A widget about to be hidden must not keep the keyboard (Textual would drop it): hand it to the pane."""
        focused = self.screen.focused
        if focused is not None and focused is not self and (focused is hidden or hidden in focused.ancestors):
            self.focus()

    def on_taf_timeline_moved(self, message: TafTimeline.Moved) -> None:
        """Show the forecast for the cell the cursor is on."""
        message.stop()
        entry = self._entry
        ctx = self._ctx
        if message.taf is None or entry is None or ctx is None:
            return
        if message.icao != entry.icao or message.cell is not message.timeline.selected:
            return  # stale: the cursor or the station has moved on since this was posted
        self.query_one(PeriodDetail).show_cell(message.taf, message.data, message.cell, ctx, message.icao)

    def action_jump(self, section: str) -> None:
        self.jump(section)

    def jump(self, section: str) -> None:
        """Scroll to ``raw``, ``decoded`` or ``taf``; the forecast also takes the keyboard focus (cursor keys)."""
        target = {"raw": "#raw-title", "decoded": "#decoded-title", "taf": "#taf-title"}[section]
        widget = self.query_one(target)
        if widget.display:
            self.scroll_to_widget(widget, top=True, animate=False)
            if section == "taf" and self.query_one(TafTimeline).display:
                self.query_one(TafTimeline).focus(scroll_visible=False)  # the jump has placed the section
