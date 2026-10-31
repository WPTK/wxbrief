"""Rich rendering of a decode: the raw report highlighted by group, then a labelled table.

Styles are dotted names (``wx.wind``, ``fcat.ifr``) resolved through a Rich ``Theme``. ``DEFAULT_THEME`` is a plain
built-in palette; mapping the app's colourways onto the same names is later work.
"""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from wxbrief.decode.model import Metar
from wxbrief.decode.units import UnitsMode
from wxbrief.i18n import Translator
from wxbrief.render.highlight import highlight_spans, style_name
from wxbrief.render.plain import decode_rows, warning_lines

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


def highlighted_raw(metar: Metar) -> Text:
    """The raw report with every token styled by its kind."""
    text = Text(metar.raw)
    for span in highlight_spans(metar.tokens):
        text.stylize(style_name(span.kind), span.start, span.end)
    return text


def build_renderable(metar: Metar, t: Translator, units: UnitsMode = UnitsMode.MIXED) -> RenderableType:
    """A Rich renderable for ``metar``; print it on a ``Console(theme=DEFAULT_THEME)``."""
    table = Table.grid(padding=(0, 2))
    table.add_column(no_wrap=True)
    table.add_column()
    for row in decode_rows(metar, t, units):
        label = Text(row.label, style="wx.label")
        if row.category is not None:
            code = row.category.value
            value = Text.assemble(
                (f" {code} ", f"fcat.{code.lower()}.badge"),
                row.value.removeprefix(code),
            )
        else:
            value = Text(row.value, style=row.style or "")
        table.add_row(label, value)

    parts: list[RenderableType] = [highlighted_raw(metar), Text(""), table]
    warnings = warning_lines(metar, t)
    if warnings:
        parts.append(Text(""))
        parts.extend(Text(line, style="wx.warning") for line in warnings)
    return Group(*parts)
