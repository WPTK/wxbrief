"""The status bar: freshness, next poll and request budget (the view settings are on the Settings screen)."""

from __future__ import annotations

from datetime import datetime

from rich.text import Text
from textual.widgets import Static

from wxbrief.data.poll import Freshness, PollScheduler, Product
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
        position: tuple[int, int] | None = None,
    ) -> None:
        glyphs = ctx.glyphs
        palette = ctx.palette
        t = ctx.translator
        text = Text()
        if position is not None:  # which station of how many: the list may be out of sight
            text.append(f"{position[0]}/{position[1]} ", style=palette.muted)
        failed: Product | None = None
        if state.errors:
            # The label and the message come from the same error: the first network failure, else the first error.
            failed = next((p for p in state.errors if p in state.offline), next(iter(state.errors)))
            label = f" {t.t(K.UI_STATUS_OFFLINE)}" if failed in state.offline else ""
            text.append(f"{glyphs.error}{label}  ", style=palette.offline)
        if selected is not None and selected.metar is not None:
            if selected.freshness(now) is Freshness.FRESH:
                text.append(f"{glyphs.fresh} {t.t(K.UI_STATE_FRESH)}", style=palette.fresh)
            else:
                text.append(f"{glyphs.stale} {t.t(K.UI_STATE_STALE)}", style=palette.stale)
            if selected.from_cache and selected.updated is not None:
                text.append(f" {t.t(K.UI_STATUS_CACHED)}", style=palette.muted)
        elif selected is not None:
            text.append(f"{glyphs.missing} {t.t(K.UI_DETAIL_NO_REPORT)}", style=palette.muted)
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
        if failed is not None:  # the message can be long: last, so a narrow bar cuts it and not the freshness
            text.append(f" ({state.errors[failed]})", style=palette.muted)
        self.update(text)
