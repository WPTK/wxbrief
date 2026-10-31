"""The station list: one row per station with its flight category badge and a wind and visibility one-liner."""

from __future__ import annotations

from datetime import datetime

from rich.text import Text
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from wxbrief.data.poll import Freshness
from wxbrief.decode.model import Metar, SemanticKind
from wxbrief.i18n.keys import K
from wxbrief.state import StationReports
from wxbrief.ui.bindings import bind, localize
from wxbrief.ui.context import ViewContext


def short_conditions(metar: Metar | None) -> str:
    """The report's own wind and visibility groups (``06007KT 3/4SM``), the part a pilot scans first."""
    if metar is None:
        return ""
    end = metar.remarks_index if metar.remarks_index is not None else len(metar.tokens)
    wind = next((t.text for t in metar.tokens[:end] if t.kind is SemanticKind.WIND), "")
    vis: list[str] = []
    for token in metar.tokens[:end]:
        if token.kind is SemanticKind.VISIBILITY:
            vis.append(token.text)
        elif vis:
            break
    return " ".join(part for part in (wind, " ".join(vis)) if part)


class StationList(OptionList):
    """Selecting a row (or moving the highlight) shows that station in the detail pane."""

    BINDINGS = [
        bind("a", "screen.add_station", K.UI_BINDING_ADD_STATION),
        bind("d", "screen.remove_station", K.UI_BINDING_REMOVE_STATION),
        bind("v", "screen.toggle_layout", K.UI_BINDING_TOGGLE_LAYOUT),
    ]

    def on_mount(self) -> None:
        localize(self)

    def set_stations(
        self, reports: list[StationReports], ctx: ViewContext, now: datetime, selected: str | None
    ) -> None:
        palette = ctx.palette
        glyphs = ctx.glyphs
        options: list[Option] = []
        for entry in reports:
            if entry.metar is None:
                mark, mark_style = glyphs.missing, palette.muted
            elif entry.freshness(now) is Freshness.FRESH:
                mark, mark_style = glyphs.fresh, palette.fresh
            else:
                mark, mark_style = glyphs.stale, palette.stale
            category = entry.metar.flight_category if entry.metar else None
            line = Text.assemble((mark, mark_style), " ", (f"{entry.icao:<4}", "bold"), " ", palette.badge(category))
            theirs = ctx.awc_differs(entry)
            if theirs:
                line.append(f" {glyphs.differs}{theirs}", style=palette.stale)
            conditions = short_conditions(entry.metar)
            if conditions:
                line.append(" " + conditions)
            elif entry.metar is None:
                line.append(" " + ctx.translator.t(K.UI_LIST_NO_REPORT), style=palette.muted)
            options.append(Option(line, id=entry.icao))
        self.clear_options()
        self.add_options(options)
        ids = [entry.icao for entry in reports]
        if ids:
            self.highlighted = ids.index(selected) if selected in ids else 0
