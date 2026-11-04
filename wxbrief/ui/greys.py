"""16-colour terminals: leave the grey surfaces and text to the terminal's own default colours.

The themes' greys round to whichever of the sixteen palette colours is nearest, which is often black on a light
terminal. The terminal's default foreground and background always read, since the user chose them. A colour that is
not a plain grey (a flight category, a theme's tint) is left as it is for Rich to round.
"""

from __future__ import annotations

from functools import lru_cache

from rich.color import Color as RichColor
from rich.color import ColorType
from rich.segment import Segment
from rich.style import Style
from textual.color import Color
from textual.filter import LineFilter

_DEFAULT = RichColor.default()


def _grey(color: RichColor | None) -> bool:
    if color is None or color.type is not ColorType.TRUECOLOR or color.triplet is None:
        return False
    red, green, blue = color.triplet
    return red == green == blue


@lru_cache(1024)
def terminal_greys(style: Style) -> Style:
    """``style`` with a grey foreground or background replaced by the terminal's default."""
    foreground = _DEFAULT if _grey(style.color) else None
    background = _DEFAULT if _grey(style.bgcolor) else None
    if foreground is None and background is None:
        return style
    return style + Style.from_color(foreground, background)


class TerminalGreys(LineFilter):
    def apply(self, segments: list[Segment], background: Color) -> list[Segment]:
        return [
            Segment(text, None if style is None else terminal_greys(style), control)
            for text, style, control in segments
        ]
