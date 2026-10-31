"""The status bar: freshness, next poll, request budget and the current view settings."""

from __future__ import annotations

from datetime import datetime

from rich.text import Text
from textual.widgets import Static

from wxbrief.data.poll import Freshness, PollScheduler
from wxbrief.state import AppState, StationReports
from wxbrief.ui.context import ViewContext


def countdown(seconds: float) -> str:
    whole = max(0, int(seconds + 0.5))
    return f"{whole // 60}:{whole % 60:02d}"


class StatusBar(Static):
    def show(
        self,
        state: AppState,
        scheduler: PollScheduler | None,
        ctx: ViewContext,
        now: datetime,
        selected: StationReports | None,
        glyph_set: str,
    ) -> None:
        glyphs = ctx.glyphs
        palette = ctx.palette
        text = Text()
        if state.errors:
            message = next(iter(state.errors.values()))
            text.append(f"{glyphs.error} offline", style=palette.offline)
            text.append(f" ({message})  ", style=palette.muted)
        if selected is not None and selected.metar is not None:
            if selected.freshness(now) is Freshness.FRESH:
                text.append(f"{glyphs.fresh} fresh", style=palette.fresh)
            else:
                text.append(f"{glyphs.stale} stale", style=palette.stale)
            if selected.from_cache and selected.updated is not None:
                text.append(" (cached)", style=palette.muted)
        elif selected is not None:
            text.append(f"{glyphs.missing} no data", style=palette.muted)
        if scheduler is not None:
            wait = "away" if scheduler.away else f"next poll {countdown(scheduler.next_due_in())}"
            text.append(f" | {wait} | req {scheduler.budget.used}/{scheduler.budget.limit}", style=palette.muted)
        else:
            text.append(" | polling off", style=palette.muted)
        view = f"{ctx.app.theme} | {glyph_set} | {ctx.translator.lang} | {ctx.units.value} | {ctx.time_mode}"
        text.append(f" | {view}", style=palette.muted)
        self.update(text)
