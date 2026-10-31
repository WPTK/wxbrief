"""Semantic colour tokens shared by the TUI and the CLI.

Three layers feed a theme's final variables: ``SEMANTIC_DEFAULTS`` (the ``wx-*`` highlight tokens, written as
references to the chrome colours), the fixed-meaning flight-category and colour-state colours from
``semantic_variables`` (they do not follow the theme's accents, only its dark or light side), and the theme's own
``variables``. ``wxbrief.render.palette`` applies them in that order and resolves the ``$name`` references, because
Textual does not expand references held in a variables dict (only in CSS text).
"""

from __future__ import annotations

# Highlight tokens: the Rich style is ``wx.<key>`` and the Textual variable is ``$wx-<key>``.
SEMANTIC_DEFAULTS: dict[str, str] = {
    "wx-station": "$primary",
    "wx-time": "$text-muted",
    "wx-wind": "$secondary",
    "wx-vis": "$accent",
    "wx-wx": "$warning",
    "wx-cloud": "$foreground",
    "wx-temp": "$success",
    "wx-pressure": "$primary-lighten-2",
    "wx-remark": "$text-muted",
    "wx-trend": "$secondary-lighten-1",
    "wx-color-state": "$accent",
    "wx-unknown": "$error",
    "wx-label": "$foreground",
    "wx-warning": "$warning",
}

# Flight categories: (dark theme, light theme). Red means IFR and green means VFR in every theme.
FLIGHT_CATEGORY_COLORS: dict[str, tuple[str, str]] = {
    "vfr": ("#3ddc6a", "#1b7f2a"),
    "mvfr": ("#4d9dff", "#1e5fd6"),
    "ifr": ("#ff5c5c", "#c4161c"),
    "lifr": ("#ff5cf0", "#a8007f"),
}

# NATO colour states, from best to worst.
COLOR_STATE_COLORS: dict[str, tuple[str, str]] = {
    "blu": ("#4d9dff", "#1e5fd6"),
    "wht": ("#f0f0f0", "#767676"),
    "grn": ("#3ddc6a", "#1b7f2a"),
    "ylo": ("#ffe84d", "#8f6b00"),
    "amb": ("#ffb000", "#a85a00"),
    "red": ("#ff5c5c", "#c4161c"),
}

# Built-in Textual themes worth cycling through; every name ships in Textual 8.
BUILTIN_THEME_NAMES: tuple[str, ...] = (
    "textual-dark",
    "textual-light",
    "nord",
    "gruvbox",
    "catppuccin-mocha",
    "catppuccin-latte",
    "dracula",
    "tokyo-night",
    "monokai",
    "flexoki",
    "solarized-dark",
    "solarized-light",
)


def semantic_variables(dark: bool) -> dict[str, str]:
    """The ``fcat-*`` and ``cs-*`` variables as hex colours for a dark or a light theme."""
    index = 0 if dark else 1
    variables = {f"fcat-{name}": pair[index] for name, pair in FLIGHT_CATEGORY_COLORS.items()}
    variables.update({f"cs-{name}": pair[index] for name, pair in COLOR_STATE_COLORS.items()})
    return variables
