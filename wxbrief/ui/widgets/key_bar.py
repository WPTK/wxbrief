"""The key bar: Textual's footer that leaves out whole keys, never half a label, when the terminal is narrow."""

from __future__ import annotations

from collections.abc import Iterator

from textual.events import Resize
from textual.widget import Widget
from textual.widgets import Footer
from textual.widgets._footer import FooterKey

ALWAYS = ("help", "quit", "close")  # never dropped: a small-terminal user must see how to get help, go back and leave
STEPPING = "next_station"  # j/k, shown only while the station list is hidden: the next to last to go
COMPACT_BELOW = 100  # columns: tighter keys
# The command palette hint shows from the first width the app calls -normal (WxBriefApp.HORIZONTAL_BREAKPOINTS).
PALETTE_WIDTH = 14  # what the docked palette key takes at the right
KEY_SLACK = 3  # the padding or margin a key takes around its label


def key_width(key: FooterKey) -> int:
    return len(key.key_display) + len(key.description) + KEY_SLACK


class KeyBar(Footer):
    """Keys drop from the right, lowest priority first, until the rest fit; ``? Help`` and ``q Quit`` stay."""

    def __init__(self) -> None:
        super().__init__()
        self._fitted = 0  # the width the keys were last chosen for

    def _adapt(self, width: int) -> None:
        """Choose the key style for ``width`` and remember it, so the first resize does not compose the bar again."""
        self._fitted = width
        self.compact = width < COMPACT_BELOW
        self.show_command_palette = not self.screen.has_class("-narrow")

    def compose(self) -> Iterator[Widget]:
        self._adapt(self.size.width or self.app.size.width)  # the bar is not laid out yet on its first compose
        widgets = list(super().compose())
        keys = [w for w in widgets if isinstance(w, FooterKey) and not w.has_class("-command-palette")]
        budget = self._fitted - (PALETTE_WIDTH if self.show_command_palette else 0)
        used = sum(key_width(k) for k in keys)
        dropped: set[Widget] = set()
        # right to left, then the stepping keys, so the rest of the bar goes before them
        order = [k for k in reversed(keys) if k.action != STEPPING] + [k for k in keys if k.action == STEPPING]
        for key in order:
            if budget <= 0 or used <= budget:
                break
            if key.action not in ALWAYS:
                dropped.add(key)
                used -= key_width(key)
        yield from (w for w in widgets if w not in dropped)

    def on_resize(self, event: Resize) -> None:
        if event.size.width != self._fitted:
            self._adapt(event.size.width)
            self.call_later(self.recompose)
