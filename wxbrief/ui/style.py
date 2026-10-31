"""Turn the decoder's style names into Rich styles taken from the active Textual theme.

``highlight.py`` names a style per token kind (``wx.wind``). The CLI resolves those through a Rich theme; here they
resolve to the theme's colour variables, so the raw report re-colours when the theme changes. Flight-category colours
are fixed for now; the colourway session replaces both tables with theme-aware ones.
"""

from __future__ import annotations

from collections.abc import Mapping

from rich.style import Style
from rich.text import Text
from textual.color import Color

from wxbrief.decode.model import FlightCategory, Metar, Taf
from wxbrief.render.highlight import highlight_spans, style_name

# Style name -> (theme variable, extra Rich attributes).
_SEMANTIC: dict[str, tuple[str, str]] = {
    "wx.station": ("primary-lighten-2", "bold"),
    "wx.time": ("foreground-darken-2", "dim"),
    "wx.wind": ("secondary-lighten-3", ""),
    "wx.vis": ("accent", ""),
    "wx.wx": ("warning", ""),
    "wx.cloud": ("foreground", ""),
    "wx.temp": ("success", ""),
    "wx.pressure": ("primary-lighten-2", ""),
    "wx.remark": ("foreground-darken-2", "dim"),
    "wx.trend": ("secondary-lighten-3", ""),
    "wx.color-state": ("accent", "bold"),
    "wx.unknown": ("error-lighten-2", "bold"),
    "wx.label": ("foreground", "bold"),
    "wx.warning": ("warning", ""),
}

_BADGES = {
    FlightCategory.VFR: Style.parse("bold black on green"),
    FlightCategory.MVFR: Style.parse("bold white on blue"),
    FlightCategory.IFR: Style.parse("bold white on red"),
    FlightCategory.LIFR: Style.parse("bold white on magenta"),
}


def _color(value: str | None) -> str | None:
    try:
        return Color.parse(value).hex6 if value else None
    except Exception:  # "auto 60%" and other values that are not plain colours
        return None


class Palette:
    """Rich styles for the semantic style names, built from a Textual variable map."""

    def __init__(self, variables: Mapping[str, str]) -> None:
        self._styles: dict[str, Style] = {}
        for name, (variable, attrs) in _SEMANTIC.items():
            base = Style.parse(attrs) if attrs else Style.null()
            color = _color(variables.get(variable))
            self._styles[name] = base + Style(color=color) if color else base

    def style(self, name: str | None) -> Style:
        return self._styles.get(name or "", Style.null())

    @staticmethod
    def badge(category: FlightCategory | None) -> Text:
        if category is None:
            return Text(" -- ", style="dim")
        return Text(f" {category.value:^4} ", style=_BADGES[category])

    def raw_text(self, report: Metar | Taf) -> Text:
        """The raw report with every token coloured by its kind."""
        text = Text(report.raw)
        for span in highlight_spans(report.tokens):
            text.stylize(self.style(style_name(span.kind)), span.start, span.end)
        return text
