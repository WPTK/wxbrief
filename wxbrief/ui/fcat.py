"""Flight-category colours for the forecast widgets, taken from the active Textual theme.

The widgets draw with Rich styles built here from ``Palette.from_theme`` (the fixed ``fcat-*`` colours, light or dark to
suit the theme). If a theme cannot be resolved the plain defaults from ``semantic.py`` are used, so a strip is never
left without colours.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.style import Style
from textual.color import Color, ColorParseError
from textual.theme import Theme

from wxbrief.decode.model import FlightCategory
from wxbrief.render.palette import Palette, readable_on
from wxbrief.ui.themes.semantic import FLIGHT_CATEGORY_COLORS


@dataclass(frozen=True)
class CategoryColors:
    """Fill and readable text colour (``#rrggbb``) per category, and a neutral for an unknown category."""

    fill: dict[FlightCategory, str]
    text: dict[FlightCategory, str]
    unknown_fill: str
    unknown_text: str

    def fill_of(self, category: FlightCategory | None) -> str:
        return self.unknown_fill if category is None else self.fill[category]

    def text_on(self, category: FlightCategory | None) -> str:
        return self.unknown_text if category is None else self.text[category]

    def style(self, category: FlightCategory | None, foreground: str | None = None) -> Style:
        """Fill ``category`` as the background; the foreground defaults to the readable text colour."""
        return Style(color=foreground or self.text_on(category), bgcolor=self.fill_of(category))


def _build(theme: Theme) -> CategoryColors:
    fill: dict[FlightCategory, str] = {}
    text: dict[FlightCategory, str] = {}
    try:
        palette = Palette.from_theme(theme)
        for category in FlightCategory:
            color = palette.color(f"fcat-{category.value.lower()}")
            fill[category] = color.hex6
            text[category] = readable_on(color).hex6
        unknown = palette.color("surface").blend(palette.color("foreground"), 0.35)
    except (ColorParseError, KeyError, ValueError):
        index = 0 if theme.dark else 1
        for category in FlightCategory:
            color = Color.parse(FLIGHT_CATEGORY_COLORS[category.value.lower()][index])
            fill[category] = color.hex6
            text[category] = readable_on(color).hex6
        unknown = Color.parse("#555555" if theme.dark else "#bbbbbb")
    return CategoryColors(fill, text, unknown.hex6, readable_on(unknown).hex6)


_CACHE: dict[tuple[str, int], CategoryColors] = {}


def category_colors(theme: Theme) -> CategoryColors:
    """The colours for ``theme``, built once per theme object."""
    key = (theme.name, id(theme))
    found = _CACHE.get(key)
    if found is None:
        found = _CACHE[key] = _build(theme)
    return found
