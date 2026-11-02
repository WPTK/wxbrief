"""L5: every text style of every cycled theme, resolved to colours and measured (no screenshots, no program)."""

from __future__ import annotations

import pytest

from wxbrief.render.palette import Palette, all_themes, contrast_ratio
from wxbrief.ui.themes import THEME_CYCLE

KNOWN_BAD = {"textual-light", "nord", "gruvbox", "catppuccin-mocha", "catppuccin-latte", "tokyo-night", "solarized-dark", "solarized-light"}


def failures(name: str) -> list[str]:
    """Text needs 4.5:1 on the surface and the panel; the bold flight-category and colour-state colours need 3:1."""
    palette = Palette.from_theme(all_themes()[name])
    found: list[str] = []
    text = [key for key in palette.variables if key.startswith("wx-")] + ["foreground", "text-muted"]
    for key in text:
        for ground in ("surface", "panel"):
            ratio = contrast_ratio(palette.color(key), palette.color(ground))
            if ratio < 4.5:
                found.append(f"{key} on {ground} {ratio:.2f} (needs 4.5)")
    for key in (key for key in palette.variables if key.startswith(("fcat-", "cs-"))):
        for ground in ("surface", "panel"):
            ratio = contrast_ratio(palette.color(key), palette.color(ground))
            if ratio < 3:
                found.append(f"{key} on {ground} {ratio:.2f} (needs 3)")
    return found


@pytest.mark.parametrize(
    "theme",
    [
        pytest.param(name, marks=pytest.mark.xfail(strict=True, reason="#260: text or category colours below the contrast floor"))
        if name in KNOWN_BAD
        else name
        for name in THEME_CYCLE
    ],
)
def test_L5_every_text_style_is_legible_in_every_theme(theme: str) -> None:
    assert not failures(theme), failures(theme)
