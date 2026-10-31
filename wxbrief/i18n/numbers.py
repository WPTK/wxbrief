"""Locale number formatting: decimal and thousands separators taken from a catalog's ``[meta]`` table.

Unit symbols (kt, SM, hPa ...) stay as they are in every language; only the punctuation of the digits changes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NumberFormat:
    """How one language writes numbers.

    ``min_grouping`` is the fewest integer digits that get a thousands separator (Spanish writes ``3000`` but
    ``10.000``, so it asks for 5).
    """

    decimal: str = "."
    group: str = ","
    min_grouping: int = 4

    @classmethod
    def from_meta(cls, meta: Mapping[str, object]) -> NumberFormat:
        """Read ``decimal``, ``group`` and ``min_grouping`` from a catalog's ``[meta]``; bad values stay English."""
        base = cls()
        decimal, group, minimum = meta.get("decimal"), meta.get("group"), meta.get("min_grouping")
        return cls(
            decimal=decimal if isinstance(decimal, str) and decimal else base.decimal,
            group=group if isinstance(group, str) and group else base.group,
            min_grouping=minimum if isinstance(minimum, int) and not isinstance(minimum, bool) else base.min_grouping,
        )

    def integer(self, value: float) -> str:
        """A whole number with the thousands separator (``3,000`` in English, ``3 000`` in French)."""
        number = round(value)
        digits = str(abs(number))
        if len(digits) >= self.min_grouping:
            head = len(digits) % 3 or 3
            parts = [digits[:head], *(digits[i : i + 3] for i in range(head, len(digits), 3))]
            digits = self.group.join(parts)
        return f"-{digits}" if number < 0 else digits

    def fixed(self, value: float, places: int) -> str:
        """``value`` with exactly ``places`` decimals and no thousands separator (``29.92``, ``1013,2``)."""
        return f"{value:.{places}f}".replace(".", self.decimal)

    def trimmed(self, value: float, places: int = 1) -> str:
        """``value`` with up to ``places`` decimals, trailing zeros dropped (``1.2``, ``10``)."""
        text = f"{value:.{places}f}"
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return (text or "0").replace(".", self.decimal)


ENGLISH = NumberFormat()
