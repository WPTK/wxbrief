"""Plural categories per language rule. ``one_other`` is the English rule; other rules arrive with their catalogs."""

from __future__ import annotations

from collections.abc import Callable

# Categories a catalog may spell out; "other" is mandatory in every plural entry.
CATEGORIES = ("zero", "one", "two", "few", "many", "other")


def _one_other(n: float) -> str:
    return "one" if n == 1 else "other"


RULES: dict[str, Callable[[float], str]] = {
    "one_other": _one_other,
}


def plural_category(rule: str, n: float) -> str:
    """Return the plural category of ``n`` under ``rule``; unknown rules fall back to ``one_other``."""
    return RULES.get(rule, _one_other)(n)
