"""Styled screen snapshots on top of ``Terminal`` (new file; the kit API is unchanged).

``Terminal.screen()`` is text only. "Did that key press change anything the user can see?" also has to count a moved
cursor or a highlighted title, which differ only in colour or attributes. ``styled_rows`` returns, per row, the text and
the style of every non-blank cell, with the two volatile status-bar facts (the poll countdown and the request count)
blanked, so two snapshots of an idle program are equal and a snapshot after a visible change is not.
"""

from __future__ import annotations

import re
from typing import Any

from .terminal import Terminal

_VOLATILE = re.compile(r"next poll \d+:\d\d|req \d+/\d+|\d+/\d+ ")


def _style(cell: Any) -> tuple[Any, ...]:
    return (str(cell.fg), str(cell.bg), cell.bold, cell.dim, cell.italic, cell.inverse, cell.underline)


def styled_rows(term: Terminal, *, plain_tail: int = 2) -> list[tuple[str, tuple[Any, ...]]]:
    """One ``(text, styles)`` per screen row. The last ``plain_tail`` rows (status bar, key bar) compare by text only,
    because their colours move with the countdown."""
    cells = term._run(term._t.cells(0, 0, term.cols, term.rows))
    rows: list[list[Any]] = [[] for _ in range(term.rows)]
    for cell in cells:
        rows[cell.y].append(cell)
    out: list[tuple[str, tuple[Any, ...]]] = []
    for index, row in enumerate(rows):
        text = "".join(c.char or "" for c in sorted(row, key=lambda c: c.x)).rstrip()
        text = _VOLATILE.sub("", text)
        if index >= term.rows - plain_tail:
            out.append((text, ()))
        else:
            out.append((text, tuple(_style(c) for c in sorted(row, key=lambda c: c.x) if c.char not in ("", " "))))
    return out


def changed_rows(before: list[tuple[str, tuple[Any, ...]]], after: list[tuple[str, tuple[Any, ...]]]) -> list[int]:
    """Indexes of the rows that differ in text or style."""
    return [i for i, (a, b) in enumerate(zip(before, after, strict=False)) if a != b]


def detail_overflows(term: Terminal) -> bool:
    """True when a vertical scrollbar thumb is drawn in the three right-most columns above the status bar: the content
    of the pane is taller than the pane, so there is something to scroll."""
    cells = term._run(term._t.cells(term.cols - 3, 0, 3, term.rows))
    return any(c.char in "▁▂▃▄▅▆▇█" for c in cells if c.y < term.rows - 2)
