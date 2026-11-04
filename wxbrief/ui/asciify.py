"""The ASCII glyph set, enforced where the screen leaves the program.

Borders, scrollbars, toast bars and Rich tables are drawn by Textual and Rich with block and box-drawing characters that
an ASCII-only console (code page 437 or 1252, a bare font) cannot show. Rather than restyle every widget, the text
written to the terminal is mapped one character to one character, so the layout does not move. Letters (with their
accents) and the degree sign exist in those code pages and stay.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable

DEGREE = 0xB0  # in code pages 437 and 1252, and every wind and temperature has one

_MAP: dict[int, str] = {}


def _put(points: Iterable[int], to: str) -> None:
    for point in points:
        _MAP[point] = to


def _span(first: int, last: int) -> range:
    return range(first, last + 1)


# Box drawing (U+2500 to U+257F): straight lines, then every corner, tee and cross.
_put([0x2500, 0x2501, 0x2504, 0x2505, 0x2508, 0x2509, 0x254C, 0x254D, 0x2550], "-")
_put([0x2502, 0x2503, 0x2506, 0x2507, 0x250A, 0x250B, 0x254E, 0x254F, 0x2551], "|")
_put([*_span(0x250C, 0x254B), *_span(0x2552, 0x256C), *_span(0x256D, 0x2570)], "+")
# Block elements (U+2580 to U+259F): the parts of a tall border and a scrollbar.
_put([0x2580, 0x2594], "-")  # upper blocks
_put([*_span(0x2581, 0x2587)], "_")  # lower blocks
_put([*_span(0x2589, 0x258F), 0x2590, 0x2595], "|")  # left and right blocks
_put([0x2588, *_span(0x2596, 0x259F)], "#")
_put([0x2591, 0x2592, 0x2593], ":")
# Arrows and shapes.
_put([0x25B2, 0x25B4, 0x2191], "^")
_put([0x25BC, 0x25BE, 0x2193], "v")
_put([0x25B6, 0x25B8, 0x25BA, 0x2192, 0x203A], ">")
_put([0x25C0, 0x25C2, 0x25C4, 0x2190, 0x2039], "<")
_put([0x25CF, 0x2022, 0x25AA, 0x25A0, 0x25C6, 0x2605], "*")
_put([0x25CB, 0x25A1, 0x25C7, 0x2606], "o")
_put([0x25D0, 0x25D1, 0x25D2, 0x25D3], "!")
_put([0x2260, 0x2716, 0x2715, 0x2717, 0x274C, 0xD7], "x")
_put([0x2713, 0x2714], "v")
# Punctuation.
_put([0x2026, 0xB7, 0x22C5], ".")
_put([0x2013, 0x2014, 0x2212, 0x2010, 0x2011], "-")
_put([0x2018, 0x2019, 0x2032], "'")
_put([0x201C, 0x201D, 0x2033], '"')
_put([0xA0, 0x2009, 0x202F], " ")


def to_ascii(text: str) -> str:
    """``text`` with every character the ASCII glyph set cannot draw replaced by a one-cell stand-in."""
    if text.isascii():
        return text
    return "".join(ch if ord(ch) < 128 else _one(ch) for ch in text)


def _one(ch: str) -> str:
    if ord(ch) == DEGREE or ch.isalpha():
        return ch
    mapped = _MAP.get(ord(ch))
    if mapped is not None:
        return mapped
    if unicodedata.combining(ch) or unicodedata.category(ch) == "Cf":
        return ch  # zero width: it belongs to the letter before it
    return "?"
