"""Shared machinery of the UAT suite: build the demo app, drive it through Textual's pilot, read what is on screen.

The journeys in ``journeys.py`` use only this module. The pytest file and ``scripts/uat_screenshots.py`` both run them,
so a screenshot always shows the state a test asserted on. Nothing here imports pytest.
"""

from __future__ import annotations

import time
import tomllib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from textual.widget import Widget

from wxbrief import clipboard
from wxbrief.__main__ import build_tui_parser, tui_options
from wxbrief.app import WxBriefApp
from wxbrief.config import Config
from wxbrief.ui.screens.briefing import BriefingScreen

# Terminal sizes (columns, rows): the common ones first, then the floor, then the smallest supported.
SIZES: dict[str, tuple[int, int]] = {
    "120x30": (120, 30),  # Windows Terminal default
    "200x50": (200, 50),  # maximized on a 1080p screen
    "100x50": (100, 50),  # half-screen split
    "280x70": (280, 70),  # large monitor
    "80x24": (80, 24),  # the floor
    "60x20": (60, 20),
    "60x16": (60, 16),  # the smallest the app draws; below it a notice asks for a larger window
}
COMMON = ("120x30", "200x50", "100x50", "280x70", "80x24")
SMALL = ("60x20", "60x16")
WIDE_FROM = 90  # app.tcss: HORIZONTAL_BREAKPOINTS; below this the station list gives way to the detail
TALL_FROM = 24  # VERTICAL_BREAKPOINTS


def size_name(size: tuple[int, int]) -> str:
    return f"{size[0]}x{size[1]}"


def demo_app(*flags: str, config_path: Path | None = None) -> WxBriefApp:
    """The real app on the bundled demo reports and fixed clock.

    Without ``config_path`` nothing is read or written. With one, the config is read from and saved to that file only
    (the app saves a changed watchlist, theme and settings the way it does outside the demo).
    """
    args = build_tui_parser().parse_args(["--demo", "--no-config", "--glyphs", "unicode", *flags])
    options = tui_options(args)
    if config_path is not None:
        options = replace(options, use_config=True, config=Config(), config_path=config_path)
    return WxBriefApp(options)


def screen_lines(app: WxBriefApp) -> list[str]:
    """What the current screen shows, one string per terminal row (trailing blanks trimmed).

    Reads the compositor, which is private Textual API; textual is pinned below 9 in pyproject.toml.
    """
    return [strip.text.rstrip() for strip in app.screen._compositor.render_strips()]


def toasts(app: WxBriefApp) -> list[str]:
    """The messages of the notifications raised so far (private Textual API, like ``screen_lines``)."""
    return [note.message for note in app._notifications]


def footer_text(app: WxBriefApp) -> str:
    """The bottom row of the screen: the key bar."""
    return screen_lines(app)[-1]


def card_lines_needed(widget: Widget) -> int:
    """How many rows a widget's content needs at its current width (compare with ``content_size.height``)."""
    app: Any = widget.app
    return int(widget.get_content_height(app.size, app.size, widget.content_size.width))


@dataclass
class Run:
    """One journey in progress: the app, its pilot, and the hooks the screenshot script uses."""

    app: WxBriefApp
    pilot: Any
    size: tuple[int, int]
    config_path: Path
    copied: list[str] = field(default_factory=list)
    on_shot: Callable[[str], None] | None = None
    shots: list[str] = field(default_factory=list)

    @property
    def wide(self) -> bool:
        return self.size[0] >= WIDE_FROM

    @property
    def briefing(self) -> BriefingScreen:
        return self.app.briefing

    def text(self) -> str:
        return "\n".join(screen_lines(self.app))

    async def settle(self) -> None:
        await self.pilot.pause()

    async def press(self, *keys: str) -> None:
        for key in keys:
            await self.pilot.press(key)
        await self.settle()

    async def until(self, condition: Callable[[], object], what: str, timeout: float = 5.0) -> None:
        """Wait (bounded, polling) until ``condition()`` is true; never a fixed sleep."""
        deadline = time.monotonic() + timeout
        while not condition():
            if time.monotonic() > deadline:
                raise AssertionError(f"timed out after {timeout}s waiting for: {what}")
            await self.pilot.pause(0.02)
        await self.settle()

    async def shot(self, label: str) -> None:
        """Mark a state worth a picture. The tests ignore it; the screenshot script exports it."""
        await self.settle()
        await self.until(lambda: screen_lines(self.app)[-1].strip(), "the footer to be drawn")
        await self.pilot.pause(0.1)  # the footer follows the focus a frame later; only the pictures care
        self.shots.append(label)
        if self.on_shot is not None:
            self.on_shot(label)

    def saved(self) -> dict[str, Any]:
        """The config file the app wrote, or ``{}`` when it wrote none."""
        try:
            return tomllib.loads(self.config_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}


Journey = Callable[[Run], Awaitable[None]]


async def run_journey(
    journey: Journey,
    size: tuple[int, int],
    work_dir: Path,
    *flags: str,
    on_shot: Callable[[Run, str], None] | None = None,
) -> Run:
    """Start the demo at ``size``, run ``journey`` against it and return the finished run.

    The clipboard is replaced for the duration, and the config goes to ``work_dir`` only.
    """
    config_path = work_dir / "config.toml"
    app = demo_app(*flags, config_path=config_path)
    original = clipboard._pyperclip_copy
    copied: list[str] = []
    clipboard._pyperclip_copy = copied.append
    try:
        async with app.run_test(size=size) as pilot:
            run = Run(app, pilot, size, config_path, copied)
            if on_shot is not None:
                run.on_shot = lambda label: on_shot(run, label)
            await run.until(lambda: isinstance(app.screen, BriefingScreen) and app.briefing._ready, "the briefing")
            await journey(run)
            return run
    finally:
        clipboard._pyperclip_copy = original
