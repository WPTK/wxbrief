"""The settings dialog: language, units, time and glyphs change with Enter and are saved; the rest is for reference."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option

from wxbrief.i18n.keys import K
from wxbrief.render.plain import DecodeRow
from wxbrief.ui.bindings import bind, localize
from wxbrief.ui.widgets.period_detail import ROW_LABEL_PAD, RowBlocks

if TYPE_CHECKING:
    from wxbrief.app import WxBriefApp

# The view settings Enter cycles through, with the label key of each.
EDITABLE = (
    ("lang", K.UI_SETTINGS_LANGUAGE),
    ("units", K.UI_SETTINGS_UNITS),
    ("time", K.UI_SETTINGS_TIME),
    ("glyph_set", K.UI_SETTINGS_GLYPHS),
)


class SettingsScreen(ModalScreen[None]):
    BINDINGS = [
        bind("escape", "close", K.UI_BINDING_CLOSE),
        bind("S", "close", K.UI_BINDING_CLOSE, show=False),
    ]

    @property
    def wx(self) -> WxBriefApp:
        return cast("WxBriefApp", self.app)

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="settings-box", classes="dialog"):
            yield Label(classes="dialog-title", id="settings-title")
            yield OptionList(id="settings-options")
            yield RowBlocks(id="settings-info")
            yield Label(classes="hint", id="settings-hint")

    def on_mount(self) -> None:
        localize(self)
        self._draw(highlight=0)
        self.query_one(OptionList).focus()

    def _draw(self, highlight: int | None = None) -> None:
        wx = self.wx
        t = wx.ctx.translator
        self.query_one("#settings-title", Label).update(t.t(K.UI_SETTINGS_TITLE))
        self.query_one("#settings-hint", Label).update(t.t(K.UI_SETTINGS_HINT))
        options = self.query_one(OptionList)
        keep = options.highlighted if highlight is None else highlight
        editable = [(name, t.t(label), wx.setting_text(name)) for name, label in EDITABLE]
        extras = wx.settings_extra_lines()
        rows = [DecodeRow(label, value) for label, value in extras]
        labels = max(len(label) for label in [*(label for _, label, _ in editable), *(row.label for row in rows)])
        width = labels + ROW_LABEL_PAD  # the same label column as the rows below the list
        with options.prevent(OptionList.OptionHighlighted):
            options.clear_options()
            options.add_options(
                [
                    Option(Text(f"{label + ':':<{width}}{value}", no_wrap=True, overflow="ellipsis"), id=name)
                    for name, label, value in editable
                ]
            )
            options.highlighted = keep
        self.query_one("#settings-info", RowBlocks).set_blocks([(None, rows)], wx.ctx, labels=labels)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option_id:
            self.wx.cycle_setting(event.option_id)
            self._draw()

    def action_close(self) -> None:
        self.dismiss(None)
