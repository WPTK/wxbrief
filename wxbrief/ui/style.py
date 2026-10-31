"""Rich styles for the TUI, taken from the active theme's palette.

``highlight.py`` names a style per token kind (``wx.wind``). The CLI resolves those through the Rich theme of a
``wxbrief.render.palette.Palette``; the TUI uses the same Rich theme, so the raw report, the badges and the colour
states re-colour together when the theme changes and match ``wxbrief decode --theme`` exactly.
"""

from __future__ import annotations

from rich.style import Style
from rich.text import Text

from wxbrief.decode.model import FlightCategory, Metar, Taf
from wxbrief.render.highlight import highlight_spans, style_name
from wxbrief.render.palette import Palette


class ViewPalette:
    """The Rich styles of one theme: highlight kinds, flight-category badges and colour states."""

    def __init__(self, palette: Palette) -> None:
        self.palette = palette
        self._styles = palette.rich_theme.styles

    def style(self, name: str | None) -> Style:
        found = self._styles.get(name or "")
        return found if isinstance(found, Style) else Style.null()

    @property
    def muted(self) -> Style:
        """Secondary text: times, remarks, counters."""
        return self.style("wx.time")

    @property
    def fresh(self) -> Style:
        """Fresh data, in the VFR colour (green on every theme)."""
        return self.style("fcat.vfr")

    @property
    def stale(self) -> Style:
        return self.style("wx.warning") + Style(bold=True)

    @property
    def offline(self) -> Style:
        """A fault, in the IFR colour (red on every theme)."""
        return self.style("fcat.ifr")

    def badge(self, category: FlightCategory | None) -> Text:
        if category is None:
            return Text(" -- ", style=self.muted)
        return Text(f" {category.value:^4} ", style=self.style(f"fcat.{category.value.lower()}.badge"))

    def raw_text(self, report: Metar | Taf) -> Text:
        """The raw report with every token coloured by its kind."""
        text = Text(report.raw)
        for span in highlight_spans(report.tokens):
            text.stylize(self.style(style_name(span.kind)), span.start, span.end)
        return text
