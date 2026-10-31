"""Plural categories per language rule, named by each catalog's ``[meta] plural_rule``."""

from __future__ import annotations

from collections.abc import Callable

# Categories a catalog may spell out; "other" is mandatory in every plural entry.
CATEGORIES = ("zero", "one", "two", "few", "many", "other")


def _one_other(n: float) -> str:
    return "one" if n == 1 else "other"


def _one_below_two(n: float) -> str:
    """French and Portuguese: zero and one are singular."""
    return "one" if 0 <= n < 2 else "other"


RULES: dict[str, Callable[[float], str]] = {
    "one_other": _one_other,
    "one_below_two": _one_below_two,
}


# The categories each rule can return: a plural entry in that language must spell out all of them.
RULE_CATEGORIES: dict[str, tuple[str, ...]] = {
    "one_other": ("one", "other"),
    "one_below_two": ("one", "other"),
}


def plural_category(rule: str, n: float) -> str:
    """Return the plural category of ``n`` under ``rule``; unknown rules fall back to ``one_other``."""
    return RULES.get(rule, _one_other)(n)
