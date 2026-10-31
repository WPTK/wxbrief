"""The aviation chrome themes, as Textual ``Theme`` objects."""

from __future__ import annotations

from textual.theme import Theme

COCKPIT_NIGHT = Theme(
    name="cockpit-night",
    primary="#d9993b",
    secondary="#b58a4a",
    accent="#c8b560",
    warning="#e0a030",
    error="#d0583f",
    success="#8aa85f",
    foreground="#c9a96a",
    background="#0b0d10",
    surface="#12161b",
    panel="#181d23",
    dark=True,
)

PHOSPHOR_GREEN = Theme(
    name="phosphor-green",
    primary="#33ff66",
    secondary="#22cc55",
    accent="#7dffa6",
    warning="#b3ff3d",
    error="#ff6b4a",
    success="#33ff66",
    foreground="#2bd957",
    background="#000d02",
    surface="#021a06",
    panel="#04240a",
    dark=True,
)

PHOSPHOR_AMBER = Theme(
    name="phosphor-amber",
    primary="#ffb000",
    secondary="#e09a00",
    accent="#ffd060",
    warning="#ffcc33",
    error="#ff6b4a",
    success="#d9b34a",
    foreground="#f2a600",
    background="#0d0700",
    surface="#1a0f00",
    panel="#241600",
    dark=True,
)

PAPER_CHART = Theme(
    name="paper-chart",
    primary="#1f4e9c",
    secondary="#a0176d",
    accent="#0b6e8a",
    warning="#9c5400",
    error="#b3261e",
    success="#2e7d32",
    foreground="#2b2a26",
    background="#f4ecd2",
    surface="#ece3c4",
    panel="#e4daba",
    dark=False,
)

HIGH_CONTRAST_DARK = Theme(
    name="high-contrast-dark",
    primary="#00e5ff",
    secondary="#ffd400",
    accent="#ff7bff",
    warning="#ffb000",
    error="#ff5252",
    success="#00ff66",
    foreground="#ffffff",
    background="#000000",
    surface="#0a0a0a",
    panel="#141414",
    dark=True,
)

HIGH_CONTRAST_LIGHT = Theme(
    name="high-contrast-light",
    primary="#0033cc",
    secondary="#7a0070",
    accent="#005a66",
    warning="#7a4200",
    error="#b00000",
    success="#006b1f",
    foreground="#000000",
    background="#ffffff",
    surface="#f2f2f2",
    panel="#e6e6e6",
    dark=False,
)

AVIATION_THEMES: tuple[Theme, ...] = (
    COCKPIT_NIGHT,
    PHOSPHOR_GREEN,
    PHOSPHOR_AMBER,
    PAPER_CHART,
    HIGH_CONTRAST_DARK,
    HIGH_CONTRAST_LIGHT,
)
