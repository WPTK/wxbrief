"""The status bar: freshness, next poll and request budget (the view settings are on the Settings screen)."""

from __future__ import annotations

from datetime import datetime, timedelta

from rich.text import Text
from textual.widgets import Static

from wxbrief.data.poll import Freshness, PollScheduler, Product
from wxbrief.i18n import Translator
from wxbrief.i18n.keys import K
from wxbrief.state import AppState, StationReports
from wxbrief.ui.context import ViewContext


def countdown(seconds: float) -> str:
    whole = max(0, int(seconds + 0.5))
    return f"{whole // 60}:{whole % 60:02d}"


def age_text(delta: timedelta, t: Translator) -> str:
    """``12 min``, ``3 h 05 min``, ``2 d 4 h``: how long ago, never negative."""
    minutes = max(0, int(delta.total_seconds() // 60))
    if minutes < 60:
        return t.t(K.UI_AGE_MINUTES, minutes=minutes)
    hours, rest = divmod(minutes, 60)
    if hours < 24:
        return t.t(K.UI_AGE_HOURS, hours=hours, minutes=rest)
    days, hours = divmod(hours, 24)
    return t.t(K.UI_AGE_DAYS, days=days, hours=hours)


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
        offline = False
        if state.errors:
            # The label and the message come from the same error: the first network failure, else the first error.
            failed = next((p for p in state.errors if p in state.offline), next(iter(state.errors)))
            offline = failed in state.offline
            label = f" {t.t(K.UI_STATUS_OFFLINE)}" if offline else "  "
            text.append(f"{glyphs.error}{label}", style=palette.offline)
        if offline:
            # One state, not two: what is on screen is saved data, however recent its observation is.
            if selected is not None and selected.updated is not None:
                saved = t.t(K.UI_STATUS_SAVED_FROM, age=age_text(now - selected.updated, t))
                text.append(f", {saved}", style=palette.offline)
            elif selected is not None:
                text.append(f", {t.t(K.UI_DETAIL_NO_REPORT)}", style=palette.muted)
        elif selected is not None and selected.metar is not None:
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
            text.append(f" | {t.t(K.UI_STATUS_DEMO if ctx.demo else K.UI_STATUS_POLLING_OFF)}", style=palette.muted)
        if failed is not None and not offline:  # the message can be long: last, so a narrow bar cuts it
            text.append(f" ({t.t(K.UI_STATUS_FEED_PROBLEM)})", style=palette.muted)
        self.update(text)
