"""The key help dialog; its text is in the catalog (``ui.help.*``)."""

from __future__ import annotations

import re
import textwrap
from typing import TYPE_CHECKING, cast

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, Static

from wxbrief.i18n.keys import K
from wxbrief.ui.bindings import bind, localize

if TYPE_CHECKING:
    from wxbrief.app import WxBriefApp


DESCRIPTION = re.compile(r"^( +\S.*? {3,})(?=\S)")  # the keys, then three or more spaces, then the text


class HelpBody(Static):
    """The help text, wrapped to the widget's width with a wrapped line hanging under its description."""

    def __init__(self, body: str) -> None:
        super().__init__()
        self._body = body

    def on_resize(self) -> None:
        self.update(self._wrapped(max(20, self.size.width)))

    def _wrapped(self, width: int) -> Text:
        lines: list[Text] = []
        for line in self._body.splitlines():
            found = DESCRIPTION.match(line)
            if found is None:  # a heading
                lines.append(Text.from_markup(line))
                continue
            hang = " " * len(found.group(1))
            wrapped = textwrap.wrap(line, width, subsequent_indent=hang, drop_whitespace=True, break_long_words=False)
            lines.append(Text("\n".join(wrapped)))
        return Text("\n").join(lines)


class HelpScreen(ModalScreen[None]):
    BINDINGS = [
        bind("escape", "close", K.UI_BINDING_CLOSE),
        bind("question_mark", "close", K.UI_BINDING_CLOSE, show=False),
    ]

    def compose(self) -> ComposeResult:
        t = cast("WxBriefApp", self.app).ctx.translator
        with Vertical(id="help-box", classes="dialog"):
            yield Label(t.t(K.UI_HELP_TITLE), classes="dialog-title")
            with VerticalScroll():
                yield HelpBody(t.t(K.UI_HELP_BODY))
            yield Label(t.t(K.UI_HELP_HINT), classes="hint")

    def on_mount(self) -> None:
        localize(self)

    def action_close(self) -> None:
        self.dismiss(None)
