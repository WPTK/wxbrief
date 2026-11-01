"""A small rule engine over the status bar of a live session: every fact the bar states must agree with the others.

The bar is the row that carries ``req N/M``. Rules (each returns a message when broken):
  R1 never ``offline`` and ``fresh`` at once (Bill's red `offline` beside green `fresh`, #223)
  R2 never ``fresh`` and ``stale`` at once
  R3 ``offline`` is always followed by what is shown instead ("showing saved data")
"""

from __future__ import annotations

import re

from uat_kit import Screen


def status_bar(screen: Screen) -> str | None:
    """The status-bar row, or None while a toast or a dialog covers it."""
    for line in reversed(screen.lines):
        if re.search(r"\breq \d+/\d+", line):
            return line.strip()
    return None


def broken_rules(bar: str) -> list[str]:
    low = bar.lower()
    words = set(re.findall(r"[a-z]+", low))
    broken = []
    if "offline" in words and "fresh" in words:
        broken.append("R1: 'offline' beside 'fresh'")
    if "fresh" in words and "stale" in words:
        broken.append("R2: 'fresh' beside 'stale'")
    if "offline" in words and "saved" not in words:
        broken.append("R3: 'offline' without saying what is shown")
    return broken
