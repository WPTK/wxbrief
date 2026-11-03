"""The detail pane: header, flag chips, raw report, decoded table, collapsible remarks and a plain TAF block."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.events import Resize
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Collapsible, DataTable, Label, Static

from wxbrief.data.poll import Freshness
from wxbrief.decode.model import Metar, Taf
from wxbrief.i18n.keys import K
from wxbrief.render import phrases
from wxbrief.render.pairs import TokenPair, token_pairs
from wxbrief.render.plain import DecodeBlock, DecodeRow, decode_rows, taf_blocks, taf_header_rows, warning_lines
from wxbrief.state import StationReports
from wxbrief.ui.bindings import bind, localize
from wxbrief.ui.context import ViewContext
from wxbrief.ui.strip import is_expired
from wxbrief.ui.widgets.period_detail import PeriodDetail, RowBlocks
from wxbrief.ui.widgets.status_bar import STATE_KEYS, age_text
from wxbrief.ui.widgets.taf_timeline import TafTimeline
from wxbrief.ui.wrap import wrap


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
            t = ctx.translator
            missing = f"{t.t(K.UI_DETAIL_NO_REPORT)}. {t.t(K.UI_DETAIL_REFRESH_HINT)}"
            lines.append(Text(missing, style=ctx.palette.stale))
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

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._parts: list[Text] = []
        self._selected: tuple[int, int] | None = None

    def show(self, entry: StationReports, ctx: ViewContext) -> None:
        parts: list[Text] = []
        if entry.metar is not None:
            parts.append(ctx.palette.raw_text(entry.metar))
        if entry.taf is not None:
            parts.append(ctx.palette.raw_text(entry.taf))
        self._parts = parts
        self._selected = None
        self._draw()
        self.display = bool(parts)  # nothing held: the header says so, and there is no raw section to show

    def select(self, span: tuple[int, int] | None) -> None:
        """Mark ``raw[start:end]`` of the METAR (the first report) as the selected token; ``None`` clears it."""
        if span != self._selected:
            self._selected = span
            self._draw()

    def _draw(self) -> None:
        parts = self._parts
        if self._selected is not None and parts:
            first = parts[0].copy()
            first.stylize("reverse bold", *self._selected)
            parts = [first, *parts[1:]]
        self.update(Text("\n\n").join(parts))


class TokenTable(DataTable[Text]):
    """Every raw token of the METAR beside its meaning; the row cursor selects the token in the raw line.

    From ``SIDE_BY_SIDE`` terminal columns the token, its group and its meaning are columns; narrower, each token
    stands on a line of its own with its meaning indented below it.
    """

    SIDE_BY_SIDE = 100

    class Picked(Message):
        """The token under the cursor (``None`` when the table has lost the keyboard)."""

        def __init__(self, pair: TokenPair | None) -> None:
            super().__init__()
            self.pair = pair

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(show_header=False, cursor_type="row", zebra_stripes=False, **kwargs)
        self._pairs: list[TokenPair] = []
        self._ctx: ViewContext | None = None

    @property
    def selected(self) -> TokenPair | None:
        row = self.cursor_row
        return self._pairs[row] if 0 <= row < len(self._pairs) else None

    def set_pairs(self, pairs: list[TokenPair], ctx: ViewContext) -> None:
        self._pairs = pairs
        self._ctx = ctx
        self._fill()

    def _fill(self) -> None:
        ctx = self._ctx
        row = self.cursor_row
        self.clear(columns=True)
        if ctx is None or not self._pairs:
            return
        palette = ctx.palette
        side_by_side = self.app.size.width >= self.SIDE_BY_SIDE
        inner = max(20, self.size.width - 6)
        token_width = min(max(len(p.text) for p in self._pairs), 18)
        label_width = max(len(p.label) for p in self._pairs)
        meaning_width = max(12, inner - token_width - label_width - 2)
        if side_by_side:
            self.add_column("Token", width=token_width)
            self.add_column("Group", width=label_width)
            self.add_column("Meaning", width=meaning_width)
        else:
            self.add_column("Token", width=inner)
        for pair in self._pairs:
            style = palette.style("wx.warning") if pair.unknown else palette.style(pair.style)
            meaning = pair.meaning or "-"
            kept = style if pair.unknown else ""
            if side_by_side:
                self.add_row(
                    Text("\n".join(wrap(pair.text, token_width)), style=style),
                    Text(pair.label, style=palette.muted),
                    Text("\n".join(wrap(meaning, meaning_width)), style=kept),
                    height=None,
                )
            else:
                head = Text(pair.text, style=style)
                if pair.label:
                    head.append(f"  {pair.label}", style=palette.muted)
                body = Text("\n".join(f"  {line}" for line in wrap(meaning, inner - 2)), style=kept)
                self.add_row(Text("\n").join([head, body]), height=None)
        if self.row_count:
            self.move_cursor(row=min(max(row, 0), self.row_count - 1), animate=False)

    def on_resize(self, event: Resize) -> None:
        if self._pairs:
            self._fill()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        event.stop()
        if self.has_focus:
            self.post_message(self.Picked(self.selected))

    def on_focus(self, event: events.Focus) -> None:
        self.post_message(self.Picked(self.selected))

    def on_blur(self, event: events.Blur) -> None:
        self.post_message(self.Picked(None))


class DecodedTable(DataTable[Text]):
    """Two columns, label and value; values wrap to the width of the pane."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(show_header=False, cursor_type="none", zebra_stripes=False, **kwargs)
        self._rows: list[DecodeRow] = []
        self._ctx: ViewContext | None = None
        self._labels = 0  # the longest label in the pane (see rows_text)
        self._keys: list[str] = []  # row keys now in the table: the label and its Nth occurrence
        self._cells: dict[str, tuple[Text, Text]] = {}
        self._widths: tuple[int, int] | None = None  # the column widths now in the table

    def set_rows(self, rows: list[DecodeRow], ctx: ViewContext, labels: int = 0) -> None:
        self._rows = rows
        self._ctx = ctx
        self._labels = labels
        self._fill()

    def _fill(self) -> None:
        """Bring the table up to date in place; a refresh that changes no row leaves the cursor and scroll alone."""
        ctx = self._ctx
        if ctx is None or not self._rows:
            self._keys, self._cells, self._widths = [], {}, None
            self.clear(columns=True)
            return
        palette = ctx.palette
        label_width = max(self._labels, max(len(row.label) for row in self._rows)) + 1
        width = max(8, self.size.width - label_width - 6)  # each column has a cell padding of 1 on both sides
        wanted: list[tuple[str, Text, Text]] = []
        seen: dict[str, int] = {}
        for row in self._rows:
            n = seen[row.label] = seen.get(row.label, 0) + 1
            wanted.append((f"{row.label}#{n}", Text(row.label, style=palette.style("wx.label")), self._value(row, width, ctx)))
        keys = [key for key, _, _ in wanted]
        # Column widths come from the pane width, never left over from an earlier one: a new width starts again.
        # So does a row that is new anywhere but at the end, since the table only appends.
        kept = [key for key in self._keys if key in keys]
        if self._widths != (label_width, width) or keys[: len(kept)] != kept:
            self._rebuild(wanted, label_width, width)
            return
        for key in self._keys:
            if key not in keys:
                self.remove_row(key)
        for key, label, value in wanted:
            if key in self._cells:
                if any(a != b or a.style != b.style for a, b in zip(self._cells[key], (label, value))):  # == ignores the base style
                    self.update_cell(key, "Field", label, update_width=False)
                    self.update_cell(key, "Value", value, update_width=False)
            else:
                self.add_row(label, value, height=None, key=key)
        self._keys = keys
        self._cells = {key: (label, value) for key, label, value in wanted}

    def _rebuild(self, wanted: list[tuple[str, Text, Text]], label_width: int, width: int) -> None:
        cursor, scroll = self.cursor_coordinate, self.scroll_y
        self.clear(columns=True)
        self.add_column("Field", width=label_width, key="Field")
        self.add_column("Value", width=width, key="Value")
        for key, label, value in wanted:
            self.add_row(label, value, height=None, key=key)
        self._widths = (label_width, width)
        self._keys = [key for key, _, _ in wanted]
        self._cells = {key: (label, value) for key, label, value in wanted}
        if self.row_count:
            self.move_cursor(row=min(cursor.row, self.row_count - 1), column=cursor.column, animate=False)
            self.call_after_refresh(self.scroll_to, y=scroll, animate=False, immediate=True)

    @staticmethod
    def _value(row: DecodeRow, width: int, ctx: ViewContext) -> Text:
        palette = ctx.palette
        if row.category is not None:
            code = row.category.value
            badge = palette.badge(row.category)[1:]  # without its left padding, which would shift the value right
            indent = len(badge.plain) + 1
            text = row.value.removeprefix(code).strip()
            if width - indent < 12:  # too narrow for a hanging indent: the badge gets its own line
                return Text.assemble(badge, "\n", "\n".join(wrap(text, width)))
            lines = wrap(text, width - indent)
            return Text.assemble(badge, " ", ("\n" + " " * indent).join(lines))
        return Text("\n".join(wrap(row.value, width)), style=palette.style(row.style))

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
        bind("4", "jump('tokens')", K.UI_BINDING_JUMP_TOKENS, show=False),
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
        yield Label(classes="section", id="tokens-title")
        yield TokenTable(id="tokens")
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
        raw_title = self.query_one("#raw-title", Label)
        raw_title.update(t.t(K.UI_SECTION_RAW))
        raw_title.display = entry.metar is not None or entry.taf is not None  # RawReport hides itself on the same test
        self.query_one("#decoded-title", Label).update(t.t(K.UI_SECTION_DECODED))
        self.query_one("#taf-title", Label).update(t.t(K.UI_SECTION_FORECAST))
        self.query_one("#tokens-title", Label).update(t.t(K.UI_SECTION_TOKENS))
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
        tokens = self.query_one(TokenTable)
        if metar is None:
            self._release_focus(tokens)
        tokens.set_pairs(token_pairs(metar, t, ctx.units) if metar else [], ctx)
        self.query_one("#tokens-title").display = tokens.display = metar is not None
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

        taf = entry.taf if isinstance(entry.taf, Taf) else None
        taf_warnings = warning_lines(taf, t) if taf else []
        if taf_warnings:  # the forecast's heading says whose they are
            taf_warnings[0] = f"{t.t(K.UI_SECTION_FORECAST)}: {taf_warnings[0]}"
        warnings = [*(warning_lines(metar, t) if metar else []), *taf_warnings]
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
        skipped = {t.t(K.LABEL_STATION), t.t(K.LABEL_REPORT)}
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

    def on_token_table_picked(self, message: TokenTable.Picked) -> None:
        """Mark the selected token in the raw line."""
        message.stop()
        pair = message.pair
        self.query_one(RawReport).select((pair.start, pair.end) if pair is not None else None)

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
        target = {"raw": "#raw-title", "decoded": "#decoded-title", "tokens": "#tokens-title", "taf": "#taf-title"}[section]
        widget = self.query_one(target)
        entry, ctx = self._entry, self._ctx
        empty = entry is not None and entry.metar is None and entry.taf is None
        if entry is not None and ctx is not None and (empty or not widget.display):
            # nothing to go to: say so, a key that does nothing looks broken
            no_taf = section == "taf" and entry.taf is None and entry.metar is not None
            key = K.TIMELINE_NO_TAF if no_taf else K.UI_DETAIL_NO_REPORT
            self.app.notify(ctx.translator.t(key), severity="warning")
            return
        self.scroll_to_widget(widget, top=True, animate=False)
        if section == "tokens" and self.query_one(TokenTable).display:
            self.query_one(TokenTable).focus(scroll_visible=False)
        if section == "taf" and self.query_one(TafTimeline).display:
            self.query_one(TafTimeline).focus(scroll_visible=False)  # the jump has placed the section
