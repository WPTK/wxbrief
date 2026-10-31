"""Rich rendering of a decode: the raw report highlighted by group, then a labelled table.

Styles are dotted names (``wx.wind``, ``fcat.ifr``) resolved through a Rich ``Theme``. ``DEFAULT_THEME`` is a plain
built-in palette; mapping the app's colourways onto the same names is later work.
"""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.padding import Padding
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from wxbrief.decode.model import Metar, Taf
from wxbrief.decode.units import UnitsMode
from wxbrief.i18n import Translator
from wxbrief.render.highlight import highlight_spans, style_name
from wxbrief.render.plain import (
    DecodeRow,
    decode_rows,
    taf_blocks,
    taf_header_rows,
    taf_summary_row,
    warning_lines,
)

DEFAULT_THEME = Theme(
    {
        "wx.station": "bold cyan",
        "wx.time": "dim",
        "wx.wind": "blue",
        "wx.vis": "magenta",
        "wx.wx": "yellow",
        "wx.cloud": "default",
        "wx.temp": "green",
        "wx.pressure": "cyan",
        "wx.remark": "dim",
        "wx.trend": "bright_blue",
        "wx.color-state": "bold magenta",
        "wx.unknown": "bold red",
        "wx.label": "bold",
        "wx.warning": "yellow",
        "fcat.vfr": "bold green",
        "fcat.mvfr": "bold blue",
        "fcat.ifr": "bold red",
        "fcat.lifr": "bold magenta",
        "fcat.vfr.badge": "bold black on green",
        "fcat.mvfr.badge": "bold white on blue",
        "fcat.ifr.badge": "bold white on red",
        "fcat.lifr.badge": "bold white on magenta",
    }
)


def highlighted_raw(report: Metar | Taf) -> Text:
    """The raw report with every token styled by its kind."""
    text = Text(report.raw)
    for span in highlight_spans(report.tokens):
        text.stylize(style_name(span.kind), span.start, span.end)
    return text


def _value(row: DecodeRow) -> Text:
    """A row's value: a flight-category badge for the category rows, otherwise the text in the row's style."""
    if row.category is not None:
        code = row.category.value
        return Text.assemble((f" {code} ", f"fcat.{code.lower()}.badge"), row.value.removeprefix(code))
    return Text(row.value, style=row.style or "")


def _table(rows: list[DecodeRow]) -> Table:
    table = Table.grid(padding=(0, 2))
    table.add_column(no_wrap=True)
    table.add_column()
    for row in rows:
        table.add_row(Text(row.label, style="wx.label"), _value(row))
    return table


def _taf_parts(taf: Taf, t: Translator, units: UnitsMode) -> list[RenderableType]:
    """The header table, then each forecast period under its title, then the summary."""
    parts: list[RenderableType] = [_table(taf_header_rows(taf, t, units))]
    for block in taf_blocks(taf, t, units):
        title = Text(block.title, style="wx.trend")
        if block.category is not None:
            title.append("  ")
            title.append(f" {block.category.value} ", style=f"fcat.{block.category.value.lower()}.badge")
        parts.append(Text(""))
        parts.append(title)
        parts.append(Padding(_table(block.rows), (0, 0, 0, 2)))
    parts.append(Text(""))
    parts.append(_table([taf_summary_row(taf, t, units)]))
    return parts


def build_renderable(report: Metar | Taf, t: Translator, units: UnitsMode = UnitsMode.MIXED) -> RenderableType:
    """A Rich renderable for ``report``; print it on a ``Console(theme=DEFAULT_THEME)``."""
    parts: list[RenderableType] = [highlighted_raw(report), Text("")]
    if isinstance(report, Taf):
        parts.extend(_taf_parts(report, t, units))
    else:
        parts.append(_table(decode_rows(report, t, units)))
    warnings = warning_lines(report, t)
    if warnings:
        parts.append(Text(""))
        parts.extend(Text(line, style="wx.warning") for line in warnings)
    return Group(*parts)
