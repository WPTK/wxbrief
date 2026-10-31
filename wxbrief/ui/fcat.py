"""Flight-category cell fills for the forecast widgets, taken from the active palette.

The fills come from the same ``Palette`` that styles the badges (``ctx.palette``), so a cell, a badge and the CLI agree.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.style import Style

from wxbrief.decode.model import FlightCategory
from wxbrief.render.palette import readable_on
from wxbrief.ui.style import ViewPalette


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


_CACHE: dict[int, tuple[ViewPalette, CategoryColors]] = {}


def category_colors(view: ViewPalette) -> CategoryColors:
    """The cell colours for ``view``, built once per palette object."""
    found = _CACHE.get(id(view))
    if found is not None and found[0] is view:
        return found[1]
    palette = view.palette
    fill: dict[FlightCategory, str] = {}
    text: dict[FlightCategory, str] = {}
    for category in FlightCategory:
        color = palette.color(f"fcat-{category.value.lower()}")
        fill[category] = color.hex6
        text[category] = readable_on(color).hex6
    unknown = palette.color("surface").blend(palette.color("foreground"), 0.35)
    colors = CategoryColors(fill, text, unknown.hex6, readable_on(unknown).hex6)
    if len(_CACHE) > 16:
        _CACHE.clear()
    _CACHE[id(view)] = (view, colors)
    return colors
