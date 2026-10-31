"""A Textual theme as a Rich ``Theme``, so ``wxbrief decode --theme NAME`` matches the TUI without an App.

``Palette.from_theme`` applies the merge ``App.get_css_variables`` applies, in the same order: the semantic defaults
(plus the fixed flight-category and colour-state colours), then the colours ``theme.to_color_system().generate()``
derives, then ``theme.variables``. It resolves ``$name`` references and ``auto N%`` colours itself, since no
stylesheet is there to do it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rich.style import Style
from rich.theme import Theme as RichTheme
from textual.color import Color
from textual.theme import BUILTIN_THEMES, Theme

from wxbrief.ui.themes import AVIATION_THEMES
from wxbrief.ui.themes.semantic import (
    FLIGHT_CATEGORY_COLORS,
    SEMANTIC_DEFAULTS,
    semantic_variables,
)

_REFERENCE = re.compile(r"^\$([A-Za-z0-9_-]+)\s*(.*)$")
_PERCENT = re.compile(r"^(\d+(?:\.\d+)?)%$")


def all_themes() -> dict[str, Theme]:
    """Every theme the CLI can name: the Textual built-ins and the aviation themes."""
    themes = dict(BUILTIN_THEMES)
    themes.update({theme.name: theme for theme in AVIATION_THEMES})
    return themes


def luminance(color: Color) -> float:
    """WCAG relative luminance of an opaque colour."""
    def channel(value: int) -> float:
        scaled = value / 255
        return scaled / 12.92 if scaled <= 0.03928 else ((scaled + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(color.r) + 0.7152 * channel(color.g) + 0.0722 * channel(color.b)


def contrast_ratio(a: Color, b: Color) -> float:
    """WCAG contrast ratio between two opaque colours, 1.0 to 21.0."""
    lighter, darker = sorted((luminance(a), luminance(b)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def readable_on(background: Color) -> Color:
    """Black or white, whichever reads better on ``background``."""
    black, white = Color(0, 0, 0), Color(255, 255, 255)
    return black if contrast_ratio(black, background) >= contrast_ratio(white, background) else white


@dataclass(frozen=True)
class Palette:
    """A theme's merged variables, with a Rich theme built from the semantic ones."""

    name: str
    dark: bool
    variables: dict[str, str]
    rich_theme: RichTheme

    @classmethod
    def from_theme(cls, theme: Theme) -> Palette:
        """Merge the three layers for ``theme`` and build the Rich styles on the dotted names the renderer uses."""
        variables = {
            **SEMANTIC_DEFAULTS,
            **semantic_variables(theme.dark),
            **theme.to_color_system().generate(),
            **theme.variables,
        }
        palette = cls(theme.name, theme.dark, variables, RichTheme())
        object.__setattr__(palette, "rich_theme", palette._build_rich_theme())
        return palette

    def color(self, name: str) -> Color:
        """The opaque colour of variable ``name`` (``wx-wind``, ``fcat-ifr``, ``background`` ...)."""
        return self._resolve(name, ())

    def hex(self, name: str) -> str:
        """``color(name)`` as ``#rrggbb``."""
        return self.color(name).hex.lower()

    def css_variables(self) -> dict[str, str]:
        """The semantic variables (``wx-*``, ``fcat-*``, ``cs-*``) as resolved hex, for ``App.get_css_variables``.

        Textual does not expand ``$name`` references held in a variables dict (only in CSS text), so the app injects
        these resolved values rather than ``SEMANTIC_DEFAULTS`` itself.
        """
        keys = (*SEMANTIC_DEFAULTS, *semantic_variables(self.dark))
        return {key: self.hex(key) for key in keys}

    def _resolve(self, name: str, seen: tuple[str, ...]) -> Color:
        if name in seen:
            raise ValueError(f"circular colour reference: {' -> '.join((*seen, name))}")
        if name not in self.variables:
            raise KeyError(name)
        chain = (*seen, name)
        value = self.variables[name].strip()
        background = self._resolve("background", chain) if name != "background" else None

        reference = _REFERENCE.match(value)
        if reference:
            color = self._resolve(reference.group(1), chain)
            percent = _PERCENT.match(reference.group(2))
            if percent:
                color = color.with_alpha(float(percent.group(1)) / 100)
        elif value.startswith("auto"):
            assert background is not None
            percent = _PERCENT.match(value[4:].strip())
            alpha = float(percent.group(1)) / 100 if percent else 1.0
            color = readable_on(background).with_alpha(alpha)
        else:
            color = Color.parse(value)
        return color if background is None else (background + color).with_alpha(1.0)

    def _build_rich_theme(self) -> RichTheme:
        styles: dict[str, Style] = {}
        for key in SEMANTIC_DEFAULTS:
            style = Style(color=self.hex(key))
            styles[key.replace("-", ".", 1)] = Style(bold=True) + style if key == "wx-label" else style
        styles["wx.station"] = styles["wx.station"] + Style(bold=True)
        styles["wx.color-state"] = styles["wx.color-state"] + Style(bold=True)
        styles["wx.unknown"] = styles["wx.unknown"] + Style(bold=True)
        for category in FLIGHT_CATEGORY_COLORS:
            fill = self.color(f"fcat-{category}")
            styles[f"fcat.{category}"] = Style(color=fill.hex, bold=True)
            styles[f"fcat.{category}.badge"] = Style(color=readable_on(fill).hex, bgcolor=fill.hex, bold=True)
        return RichTheme(styles)
