"""Check that an exported screenshot has real colour in it (used by the screenshot scripts and a test)."""

from __future__ import annotations

import re

HEX = re.compile(r"(?:fill|stroke)\s*[:=]\s*\"?#([0-9a-fA-F]{6})\b")
SPREAD = 40  # a channel spread above this is a hue; the dark themes' tinted greys stay below it
MIN_COLOURS = 3
WINDOW_DOTS = {"ff5f57", "febc2e", "28c840"}  # the exporter's fake title-bar buttons are coloured in any case


def chromatic_colours(svg: str) -> set[str]:
    """The distinct fill and stroke colours of ``svg`` that are not (nearly) grey."""
    found = set()
    for digits in HEX.findall(svg):
        channels = [int(digits[i : i + 2], 16) for i in (0, 2, 4)]
        if max(channels) - min(channels) > SPREAD and digits.lower() not in WINDOW_DOTS:
            found.add(digits.lower())
    return found


def require_colour(svg: str, name: str) -> None:
    """Raise when ``svg`` is monochrome, as happens when NO_COLOR is set in the capturing process."""
    if len(chromatic_colours(svg)) < MIN_COLOURS:
        raise SystemExit(f"{name} has no chromatic colour: it was captured without colour (is NO_COLOR set?)")
