"""Help and read-only settings dialogs."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, Static

HELP_TEXT = """\
[b]Stations[/b]
  Up/Down  j/k       select a station
  \\[ and ]            previous / next station
  Enter              move into the detail pane
  a                  add a station (code or name)
  d                  remove the selected station
  r                  refresh now
[b]Detail[/b]
  1  2  3            jump to raw, decoded, forecast
  c                  copy the Discord METAR block
  C                  copy Discord METAR and TAF
  y                  copy the raw report text
[b]Tools[/b]
  t                  next theme (saved to the config)
  T                  pick a theme, with a live preview
  p                  paste and decode any METAR or TAF (offline)
  S                  show the current settings
  ?                  this help
  q                  quit
[b]Paste screen[/b]
  c (outside the box) or F2   copy the Discord block
  Esc                         back
"""


class HelpScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape", "close", "Close"), Binding("question_mark", "close", "Close", show=False)]

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help-box", classes="dialog"):
            yield Label("wxbrief keys", classes="dialog-title")
            yield Static(HELP_TEXT)
            yield Label("Esc closes", classes="hint")

    def action_close(self) -> None:
        self.dismiss(None)
