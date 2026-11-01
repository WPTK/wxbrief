"""The key help dialog; its text is in the catalog (``ui.help.*``)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, cast

from rich.console import Console
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.geometry import Size
from textual.screen import ModalScreen
from textual.widgets import Label, Static

from wxbrief.i18n.keys import K
from wxbrief.ui.bindings import bind, localize
from wxbrief.ui.wrap import wrap

if TYPE_CHECKING:
    from wxbrief.app import WxBriefApp


DESCRIPTION = re.compile(r"^( +\S.*? {3,})(?=\S)")  # the keys, then three or more spaces, then the text


class HelpBody(Static):
    """The help text, wrapped to the widget's width with a wrapped line hanging under its description."""

    DEFAULT_CSS = "HelpBody { height: auto; }"

    def __init__(self, body: str) -> None:
        super().__init__()
        self._body = body

    def render(self) -> Text:
        return self._wrapped(max(20, self.size.width - 1))

    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        del container, viewport
        return len(self._wrapped(max(20, width - 1)).plain.splitlines())

    def _wrapped(self, width: int) -> Text:
        lines: list[Text] = []
        for line in self._body.splitlines():
            found = DESCRIPTION.match(line)
            if found is None:  # a heading
                heading = Text.from_markup(line)  # wrapped here too, so the height counts the rows it fills
                lines.append(Text("\n").join(heading.wrap(Console(width=width), width)))
                continue
            keys = found.group(1)
            if len(keys) > width // 2:  # no room beside the keys: the description goes under them, indented
                parts = [keys.rstrip(), *("    " + part for part in wrap(line[len(keys) :], width - 4))]
            else:
                first, *rest = wrap(line[len(keys) :], width - len(keys))
                parts = [keys + first, *(" " * len(keys) + part for part in rest)]
            lines.append(Text("\n".join(parts)))
        return Text("\n").join(lines)


class HelpScreen(ModalScreen[None]):
    BINDINGS = [
        bind("escape", "close", K.UI_BINDING_CLOSE),
        bind("question_mark", "close", K.UI_BINDING_CLOSE, show=False),
    ]

    def compose(self) -> ComposeResult:
        t = cast("WxBriefApp", self.app).ctx.translator
        with VerticalScroll(id="help-box", classes="dialog"):
            yield Label(t.t(K.UI_HELP_TITLE), classes="dialog-title")
            yield Label(t.t(K.UI_HELP_HINT), classes="hint")
            yield HelpBody(t.t(K.UI_HELP_BODY))

    def on_mount(self) -> None:
        localize(self)

    def action_close(self) -> None:
        self.dismiss(None)
