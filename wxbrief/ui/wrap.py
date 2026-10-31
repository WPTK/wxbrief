"""Wrapping for the text the panes draw themselves: values, headings and the help list.

``textwrap`` breaks inside a long word and at hyphens, which cuts ``config.toml`` and ``--no-config`` in half, and it
puts the zone of ``18:00 UTC`` alone on a line. This wraps at spaces and after path separators, keeps a date, a time and
its zone together, and never breaks inside an option such as ``--no-config``.
"""

from __future__ import annotations

import re

# A date and time, or a time, and the zone after it: one unit (``2026-11-01 18:00 UTC``, ``11:00 MDT``).
STAMP = re.compile(r"(?:\d{4}-\d\d-\d\d )?\d\d:\d\d(?: [A-Z]{3,4})?")
GLUE = "\x00"  # stands for a space that must not break


def wrap(text: str, width: int, hang: int = 0) -> list[str]:
    """``text`` in lines of at most ``width`` columns; every line after the first has ``width - hang`` columns.

    The caller indents the later lines by ``hang``. A word longer than a line is broken after its path separators, and
    in the middle only when it has none.
    """
    width = max(width, 8)
    words = STAMP.sub(lambda m: m.group().replace(" ", GLUE), text).split()
    lines: list[str] = []
    line = ""

    def room() -> int:
        return width if not lines else max(width - hang, 8)

    for word in words:
        if line and len(line) + 1 + len(word) <= room():
            line += " " + word
            continue
        if not line and len(word) <= room():
            line = word
            continue
        if line:
            lines.append(line)
            line = ""
        if len(word) <= room():
            line = word
            continue
        for piece in re.split(r"(?<=[/\\])", word):  # a path breaks after its separators
            while piece:
                if line and len(line) + len(piece) <= room():
                    line += piece
                    piece = ""
                elif not line and len(piece) <= room():
                    line, piece = piece, ""
                else:
                    if line:
                        lines.append(line)
                        line = ""
                    if len(piece) > room():  # no separator to break at
                        cut = room()
                        lines.append(piece[:cut])
                        piece = piece[cut:]
    if line or not lines:
        lines.append(line)
    return [item.replace(GLUE, " ") for item in lines]
