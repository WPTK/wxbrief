"""A read-only view of the settings in effect. Editing them arrives with the settings session."""

from __future__ import annotations

from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, Static


class SettingsScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape", "close", "Close"), Binding("S", "close", "Close", show=False)]

    def __init__(self, lines: list[tuple[str, str]]) -> None:
        super().__init__()
        self._lines = lines

    def compose(self) -> ComposeResult:
        width = max((len(name) for name, _ in self._lines), default=0) + 2
        body = "\n".join(f"[b]{name + ':':<{width}}[/b]{escape(value)}" for name, value in self._lines)
        with VerticalScroll(id="settings-box", classes="dialog"):
            yield Label("Settings in effect (read-only)", classes="dialog-title")
            yield Static(body)
            yield Label("Esc closes. Edit config.toml to change the saved values.", classes="hint")

    def action_close(self) -> None:
        self.dismiss(None)
