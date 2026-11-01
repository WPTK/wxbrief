"""The base of the two screens that show stations: the keys every one of them answers (``r`` refresh, ``?`` help)."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from wxbrief.i18n.keys import K
from wxbrief.ui.bindings import bind
from wxbrief.ui.copying import CopyActions
from wxbrief.ui.screens.help import HelpScreen

if TYPE_CHECKING:
    from wxbrief.app import WxBriefApp


class StationScreen(CopyActions):
    """A screen with a ``current()`` station: the copy actions, refresh now and help. A pushed screen inherits no
    bindings from the one beneath it, so these live here and each station screen gets them."""

    BINDINGS = [
        bind("r", "refresh_now", K.UI_BINDING_REFRESH_NOW),
        bind("question_mark", "help", K.UI_BINDING_HELP),
    ]

    def action_refresh_now(self) -> None:
        cast("WxBriefApp", self.app).refresh_now()

    def action_help(self) -> None:
        self.app.push_screen(HelpScreen())
