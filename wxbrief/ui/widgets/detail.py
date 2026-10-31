"""The detail pane: header, flag chips, raw report, decoded table, collapsible remarks and a plain TAF block."""

from __future__ import annotations

import textwrap
from datetime import datetime, timedelta
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.events import Resize
from textual.widgets import Collapsible, DataTable, Label, Static

from wxbrief.data.poll import Freshness
from wxbrief.decode.model import Metar, Taf
from wxbrief.i18n.keys import K
from wxbrief.render import phrases
from wxbrief.render.plain import DecodeRow, decode_rows, render_plain, warning_lines
from wxbrief.state import StationReports
from wxbrief.ui.context import ViewContext


def age_text(delta: timedelta) -> str:
    """``12 min``, ``3 h 05 min``, ``2 d 4 h``: how long ago, never negative."""
    minutes = max(0, int(delta.total_seconds() // 60))
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    if hours < 24:
        return f"{hours} h {rest:02d} min"
    days, hours = divmod(hours, 24)
    return f"{days} d {hours} h"


class StationHeader(Static):
    """Station code and name, flight category badge, observation time and how fresh it is."""

    def show(self, entry: StationReports, ctx: ViewContext, now: datetime, position: str) -> None:
        palette = ctx.palette
        station = ctx.station(entry.icao)
        name = station.name if station else (entry.awc_metar.name if entry.awc_metar else None)
        place = ", ".join(p for p in (station.state, station.country) if p) if station else ""
        metar = entry.metar
        title = Text.assemble((entry.icao, palette.style("wx.station") + palette.style("wx.label")))
        if name:
            title.append(f"  {name}")
        if place:
            title.append(f" ({place})", style="dim")
        title.append("  ")
        title.append_text(palette.badge(metar.flight_category if metar else None))
        title.append(f"   {position}", style="dim")
        lines = [title]
        if entry.awc_metar and entry.awc_metar.observed:
            observed = entry.awc_metar.observed
            state = entry.freshness(now)
            mark = ctx.glyphs.fresh if state is Freshness.FRESH else ctx.glyphs.stale
            style = "green" if state is Freshness.FRESH else "bold yellow"
            when = f"Observed {ctx.clock(observed, entry.icao)}, {age_text(now - observed)} ago  "
            line = Text.assemble(when, (f"{mark} {state.value}", style))
            if entry.from_cache and entry.updated is not None:
                line.append(f"  (cached {age_text(now - entry.updated)} ago)", style="dim")
            lines.append(line)
        else:
            lines.append(Text("No METAR in the last 2 hours", style="yellow"))
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
        self.update(Text("\n\n").join(parts) if parts else Text("No report yet", style="dim"))


class DecodedTable(DataTable[Text]):
    """Two columns, label and value; values wrap to the width of the pane."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(show_header=False, cursor_type="none", zebra_stripes=False, **kwargs)
        self._rows: list[DecodeRow] = []
        self._ctx: ViewContext | None = None
        self.add_columns("Field", "Value")

    def set_rows(self, rows: list[DecodeRow], ctx: ViewContext) -> None:
        self._rows = rows
        self._ctx = ctx
        self._fill()

    def _fill(self) -> None:
        ctx = self._ctx
        self.clear()
        if ctx is None or not self._rows:
            return
        palette = ctx.palette
        label_width = max(len(row.label) for row in self._rows) + 1
        width = max(16, self.size.width - label_width - 6)
        for row in self._rows:
            if row.category is not None:
                code = row.category.value
                badge = palette.badge(row.category)
                indent = len(badge.plain) + 1
                lines = textwrap.wrap(row.value.removeprefix(code).strip(), max(8, width - indent)) or [""]
                value = Text.assemble(badge, " ", ("\n" + " " * indent).join(lines))
            else:
                wrapped = "\n".join(textwrap.wrap(row.value, width) or [""])
                value = Text(wrapped, style=palette.style(row.style))
            self.add_row(Text(row.label, style=palette.style("wx.label")), value, height=None)

    def on_resize(self, event: Resize) -> None:
        if self._rows:
            self._fill()


class DetailPane(VerticalScroll):
    """Everything known about the selected station."""

    can_focus = True

    def compose(self) -> ComposeResult:
        yield Static("No stations yet. Press [b]a[/b] to add one.", id="placeholder")
        yield StationHeader(id="header")
        yield FlagsRow(id="flags")
        yield Label("Raw", classes="section", id="raw-title")
        yield RawReport(id="raw")
        yield Label("Decoded", classes="section", id="decoded-title")
        yield DecodedTable(id="decoded")
        with Collapsible(title="Remarks", id="remarks-box", collapsed=True):
            yield Static(id="remarks")
        yield Label("Forecast (TAF)", classes="section", id="taf-title")
        yield Static(id="taf")
        yield Static(id="warnings")

    def on_mount(self) -> None:
        self._set_visible(False)

    def _set_visible(self, shown: bool) -> None:
        self.query_one("#placeholder").display = not shown
        for child in self.children:
            if child.id != "placeholder":
                child.display = shown

    def show(self, entry: StationReports | None, ctx: ViewContext, now: datetime, position: str = "") -> None:
        if entry is None:
            self._set_visible(False)
            return
        self._set_visible(True)
        t = ctx.translator
        metar, taf = entry.metar, entry.taf
        self.query_one(StationHeader).show(entry, ctx, now, position)
        self.query_one(FlagsRow).show(metar, ctx)
        self.query_one(RawReport).show(entry, ctx)

        remark_labels = {t.t(K.LABEL_REMARK), t.t(K.LABEL_REMARKS)}
        skipped = remark_labels | {t.t(K.LABEL_FLAGS)}
        rows = decode_rows(metar, t, ctx.units) if metar else []
        self.query_one(DecodedTable).set_rows([r for r in rows if r.label not in skipped], ctx)
        self.query_one("#decoded-title").display = metar is not None
        self.query_one(DecodedTable).display = metar is not None
        remarks = [r for r in rows if r.label in remark_labels]
        box = self.query_one("#remarks-box", Collapsible)
        box.display = bool(remarks)
        box.title = f"Remarks ({len(remarks)})"
        palette = ctx.palette
        self.query_one("#remarks", Static).update(
            Text("\n").join(Text(r.value, style=palette.style(r.style)) for r in remarks)
        )

        has_taf = taf is not None
        self.query_one("#taf-title").display = has_taf
        self.query_one("#taf", Static).display = has_taf
        self.query_one("#taf", Static).update(Text(render_plain(taf, t, ctx.units)) if isinstance(taf, Taf) else "")

        warnings = warning_lines(metar, t) if metar else []
        warn_box = self.query_one("#warnings", Static)
        warn_box.display = bool(warnings)
        warn_box.update(Text("\n".join(warnings), style=palette.style("wx.warning")))

    def jump(self, section: str) -> None:
        """Scroll to ``raw``, ``decoded`` or ``taf``."""
        target = {"raw": "#raw-title", "decoded": "#decoded-title", "taf": "#taf-title"}[section]
        widget = self.query_one(target)
        if widget.display:
            self.scroll_to_widget(widget, top=True, animate=False)
