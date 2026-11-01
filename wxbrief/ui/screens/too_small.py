"""Shown over everything while the terminal is smaller than the app can draw."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.geometry import Size
from textual.screen import ModalScreen
from textual.widgets import Static

from wxbrief.i18n.keys import K
from wxbrief.ui.bindings import bind, translator_of

MIN_SIZE = Size(60, 16)  # below this the briefing and its dialogs cannot be drawn whole; 80x24 is the supported floor


class TooSmallScreen(ModalScreen[None]):
    """A notice with the size needed and the size now; ``q`` still quits. The app removes it when the window grows."""

    DEFAULT_CSS = """
    TooSmallScreen {
        align: center middle;
        background: $background;
    }
    TooSmallScreen Static {
        width: 100%;
        padding: 0 1;
        text-align: center;
    }
    """

    BINDINGS = [bind("q", "quit", K.UI_BINDING_QUIT, show=False)]

    def action_quit(self) -> None:
        self.app.exit()

    def compose(self) -> ComposeResult:
        yield Static(id="notice")

    def on_mount(self) -> None:
        self.show_size(self.app.size)

    def show_size(self, size: Size) -> None:
        text = translator_of(self).t(
            K.UI_SMALL_TEXT, width=MIN_SIZE.width, height=MIN_SIZE.height, now_width=size.width, now_height=size.height
        )
        self.query_one("#notice", Static).update(text)
