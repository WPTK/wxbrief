"""Glyph sets for the small status marks; ``g`` cycles through them."""

from __future__ import annotations

from dataclasses import dataclass

GLYPH_SETS = ("ascii", "unicode", "emoji", "nerd")


@dataclass(frozen=True, slots=True)
class Glyphs:
    fresh: str
    stale: str
    missing: str
    error: str
    differs: str  # AWC's flight category is not ours


_SETS = {
    "ascii": Glyphs(fresh="*", stale="!", missing="-", error="x", differs="!="),
    "unicode": Glyphs(fresh="●", stale="◐", missing="○", error="✖", differs="≠"),
    "emoji": Glyphs(fresh="🟢", stale="🟠", missing="⚪", error="❌", differs="≠"),
    "nerd": Glyphs(fresh="", stale="", missing="", error="", differs="≠"),
}


def glyphs_for(name: str) -> Glyphs:
    """The set called ``name``; an unknown name gives the unicode set."""
    return _SETS.get(name, _SETS["unicode"])
