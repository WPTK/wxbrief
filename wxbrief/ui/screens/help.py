"""The key help dialog; its text is in the catalog (``ui.help.*``)."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, Static

from wxbrief.i18n.keys import K
from wxbrief.ui.bindings import bind, localize

if TYPE_CHECKING:
    from wxbrief.app import WxBriefApp


class HelpScreen(ModalScreen[None]):
    BINDINGS = [
        bind("escape", "close", K.UI_BINDING_CLOSE),
        bind("question_mark", "close", K.UI_BINDING_CLOSE, show=False),
    ]

    def compose(self) -> ComposeResult:
        t = cast("WxBriefApp", self.app).ctx.translator
        with VerticalScroll(id="help-box", classes="dialog"):
            yield Label(t.t(K.UI_HELP_TITLE), classes="dialog-title")
            yield Static(t.t(K.UI_HELP_BODY))
            yield Label(t.t(K.UI_HELP_HINT), classes="hint")

    def on_mount(self) -> None:
        localize(self)

    def action_close(self) -> None:
        self.dismiss(None)
