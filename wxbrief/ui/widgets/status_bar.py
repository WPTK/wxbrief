"""The status bar: freshness, next poll and request budget (the view settings are on the Settings screen)."""

from __future__ import annotations

from datetime import datetime

from rich.text import Text
from textual.widgets import Static

from wxbrief.data.poll import Freshness, PollScheduler
from wxbrief.i18n.keys import K
from wxbrief.state import AppState, StationReports
from wxbrief.ui.context import ViewContext


def countdown(seconds: float) -> str:
    whole = max(0, int(seconds + 0.5))
    return f"{whole // 60}:{whole % 60:02d}"


STATE_KEYS = {Freshness.FRESH: K.UI_STATE_FRESH, Freshness.STALE: K.UI_STATE_STALE}


class StatusBar(Static):
    def show(
        self,
        state: AppState,
        scheduler: PollScheduler | None,
        ctx: ViewContext,
        now: datetime,
        selected: StationReports | None,
    ) -> None:
        glyphs = ctx.glyphs
        palette = ctx.palette
        t = ctx.translator
        text = Text()
        if state.errors:
            message = next(iter(state.errors.values()))
            text.append(f"{glyphs.error} {t.t(K.UI_STATUS_OFFLINE)}", style=palette.offline)
            text.append(f" ({message})  ", style=palette.muted)
        if selected is not None and selected.metar is not None:
            if selected.freshness(now) is Freshness.FRESH:
                text.append(f"{glyphs.fresh} {t.t(K.UI_STATE_FRESH)}", style=palette.fresh)
            else:
                text.append(f"{glyphs.stale} {t.t(K.UI_STATE_STALE)}", style=palette.stale)
            if selected.from_cache and selected.updated is not None:
                text.append(f" {t.t(K.UI_STATUS_CACHED)}", style=palette.muted)
        elif selected is not None:
            text.append(f"{glyphs.missing} {t.t(K.UI_STATUS_NO_DATA)}", style=palette.muted)
        if scheduler is not None:
            wait = (
                t.t(K.UI_STATUS_AWAY)
                if scheduler.away
                else t.t(K.UI_STATUS_NEXT_POLL, time=countdown(scheduler.next_due_in()))
            )
            used = t.t(K.UI_STATUS_REQUESTS, used=scheduler.budget.used, limit=scheduler.budget.limit)
            text.append(f" | {wait} | {used}", style=palette.muted)
        else:
            text.append(f" | {t.t(K.UI_STATUS_POLLING_OFF)}", style=palette.muted)
        self.update(text)
