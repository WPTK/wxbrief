"""Glyph sets for the small status marks. Switching sets live (``g``) arrives with the polish session."""

from __future__ import annotations

from dataclasses import dataclass

GLYPH_SETS = ("ascii", "unicode", "emoji", "nerd")


@dataclass(frozen=True, slots=True)
class Glyphs:
    fresh: str
    stale: str
    missing: str
    error: str


_SETS = {
    "ascii": Glyphs(fresh="*", stale="!", missing="-", error="x"),
    "unicode": Glyphs(fresh="●", stale="◐", missing="○", error="✖"),
    "emoji": Glyphs(fresh="🟢", stale="🟠", missing="⚪", error="❌"),
    "nerd": Glyphs(fresh="", stale="", missing="", error=""),
}


def glyphs_for(name: str) -> Glyphs:
    """The set called ``name``; an unknown name gives the unicode set."""
    return _SETS.get(name, _SETS["unicode"])
