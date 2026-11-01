"""Paste any METAR or TAF text and read the decode as you type. Entirely offline."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import Input, Label, Static, TextArea

from wxbrief.clipboard import copy_text
from wxbrief.decode.model import Metar, Taf
from wxbrief.decode.split import parse_any
from wxbrief.decode.times import end_of_day
from wxbrief.decode.units import UnitsMode
from wxbrief.i18n.keys import K
from wxbrief.render.discord import discord_block
from wxbrief.render.plain import decode_rows, render_plain, warning_lines
from wxbrief.ui.bindings import bind, localize
from wxbrief.ui.context import ViewContext
from wxbrief.ui.copying import parts_note
from wxbrief.ui.widgets.key_bar import KeyBar

DEBOUNCE_SECONDS = 0.2
MAX_PASTE_CHARS = 60_000  # a TAF or METAR is a few hundred characters; this is generous and keeps a stray paste cheap


def parse_reference(text: str, now: datetime) -> tuple[datetime, bool]:
    """The date the day-of-month in a report resolves against: ``YYYY-MM-DD`` as the end of that day UTC, else ``now``.

    The flag says whether the text was usable (an empty field counts as usable: it means "now").
    """
    value = text.strip()
    if not value:
        return now, True
    try:
        return end_of_day(datetime.strptime(value, "%Y-%m-%d").date()), True
    except ValueError:
        return now, False


class PasteDecodeScreen(Screen[None]):
    BINDINGS = [
        bind("escape", "close", K.UI_BINDING_BACK, priority=True),
        bind("f2", "copy_discord", K.UI_BINDING_COPY_DISCORD, priority=True),
        bind("c", "copy_discord", K.UI_BINDING_COPY_DISCORD_KEY, show=False),
    ]

    def __init__(self, ctx: ViewContext, now: Callable[[], datetime]) -> None:
        super().__init__()
        self._ctx = ctx
        self._now = now
        self._timer: Timer | None = None
        self.decoded: list[Metar | Taf] = []
        self.discord_text = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="paste-layout"):
            with Horizontal(id="paste-reference"):
                yield Label(self._ctx.translator.t(K.UI_PASTE_REFERENCE))
                yield Input(value=self._now().strftime("%Y-%m-%d"), id="reference", compact=True)
            yield TextArea(id="paste-input", tab_behavior="focus", show_line_numbers=False)
            with VerticalScroll(id="paste-output"):
                yield Static(self._ctx.translator.t(K.UI_PASTE_PROMPT), id="paste-result")
        yield KeyBar()

    def on_mount(self) -> None:
        localize(self)
        self.query_one(TextArea).focus()

    # --- decoding --------------------------------------------------------------------------------------------------

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        self._schedule()

    def on_input_changed(self, event: Input.Changed) -> None:
        self._schedule()

    def _schedule(self) -> None:
        if self._timer is not None:
            self._timer.stop()
        self._timer = self.set_timer(DEBOUNCE_SECONDS, self.decode_now)

    def redraw(self) -> None:
        """Decode again with the units and colours now in use (the output is Rich text with both baked in)."""
        self.decode_now()

    def decode_now(self) -> None:
        """Decode what is in the box now (the timer calls this 200 ms after the last change)."""
        full = self.query_one(TextArea).text
        text = full[:MAX_PASTE_CHARS]
        reference, valid = parse_reference(self.query_one("#reference", Input).value, self._now())
        self.decoded = parse_any(text, reference) if text.strip() else []
        ctx = self._ctx
        units = UnitsMode.US if ctx.units is UnitsMode.MIXED else ctx.units
        self.discord_text = "\n\n".join(discord_block(r, ctx.translator, units) for r in self.decoded)
        parts: list[RenderableType] = []
        if not valid:
            parts.append(Text(ctx.translator.t(K.UI_PASTE_BAD_DATE), style=ctx.palette.style("wx.warning")))
        if len(full) > MAX_PASTE_CHARS:
            note = ctx.translator.t(K.UI_PASTE_TRUNCATED, limit=f"{MAX_PASTE_CHARS:,}")
            parts.append(Text(note, style=ctx.palette.style("wx.warning")))
        if not self.decoded:
            parts.append(Text(ctx.translator.t(K.UI_PASTE_PROMPT)))
        for index, report in enumerate(self.decoded):
            if index:
                parts.append(Text(""))
            parts.append(self._view(report))
        self.query_one("#paste-result", Static).update(Group(*parts))

    def _view(self, report: Metar | Taf) -> RenderableType:
        ctx = self._ctx
        palette = ctx.palette
        t = ctx.translator
        parts: list[RenderableType] = [palette.raw_text(report), Text("")]
        if isinstance(report, Taf):
            parts.append(Text(render_plain(report, t, ctx.units)))
        else:
            table = Table.grid(padding=(0, 2))
            table.add_column(no_wrap=True)
            table.add_column()
            for row in decode_rows(report, t, ctx.units):
                value = Text(row.value, style=palette.style(row.style))
                if row.category is not None:
                    value = Text.assemble(
                        palette.badge(row.category), " ", row.value.removeprefix(row.category.value).strip()
                    )
                table.add_row(Text(row.label, style=palette.style("wx.label")), value)
            parts.append(table)
            warnings = warning_lines(report, t)
            if warnings:
                parts.append(Text(""))
                parts.append(Text("\n".join(warnings), style=palette.style("wx.warning")))
        return Group(*parts)

    # --- actions ---------------------------------------------------------------------------------------------------

    def action_copy_discord(self) -> None:
        if not self.discord_text:
            self.notify(self._ctx.translator.t(K.UI_TOAST_NOTHING_DECODED), severity="warning")
            return
        t = self._ctx.translator
        what = parts_note(t, t.t(K.UI_CLIPBOARD_DISCORD), self.discord_text, len(self.decoded))
        copy_text(self.app, self.discord_text, what, t)

    def action_close(self) -> None:
        self.app.pop_screen()
