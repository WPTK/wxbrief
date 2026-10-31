"""The theme picker: highlighting a theme previews it on the whole UI, Enter keeps it, Esc puts the old one back."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option


class ThemePickerScreen(ModalScreen[str | None]):
    """Dismisses with the kept theme name, or ``None`` when the choice was cancelled (the old theme is restored)."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, names: Sequence[str], current: str) -> None:
        super().__init__()
        self.names = list(names)
        self.original = current

    def compose(self) -> ComposeResult:
        with Vertical(id="theme-box", classes="dialog"):
            yield Label("Theme", classes="dialog-title")
            yield OptionList(*(Option(name, id=name) for name in self.names), id="theme-list")
            yield Label("Up/Down previews, Enter keeps, Esc cancels", classes="hint")

    def on_mount(self) -> None:
        options = self.query_one(OptionList)
        if self.original in self.names:
            options.highlighted = self.names.index(self.original)
        options.focus()

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_id is not None:
            self._apply(event.option_id)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option_id)

    def action_cancel(self) -> None:
        self._apply(self.original)
        self.dismiss(None)

    def _apply(self, name: str) -> None:
        app: App[Any] = self.app
        if app.theme != name:
            app.theme = name
