"""The cells of a forecast strip, computed without Textual.

``Timeline.hourly()`` gives one summary per UTC hour. The full timeline groups them into display cells (one hour each,
or three in a narrow terminal); the mini strip on a station card takes the next dozen hours from now. Both are plain
data so they can be tested without a screen.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from wxbrief.decode.flightcat import worst_of
from wxbrief.decode.model import FlightCategory, Taf, Timeline, TimelineHour
from wxbrief.decode.timeline import expand_timeline

MINI_STRIP_HOURS = 12


@dataclass(frozen=True)
class StripCell:
    """One cell of a strip: one hour, or several hours merged (worst case wins).

    ``category`` is the prevailing category (the cell background) and ``worst_category`` the worst including temporary
    groups and a ``BECMG`` that may land at any moment. ``becoming`` hatches the cell; ``overlay`` and
    ``overlay_category`` describe the thin row under it. ``hours`` indexes into ``Timeline.hourly()`` and ``slices``
    into ``Timeline.slices``.
    """

    start: datetime
    end: datetime
    category: FlightCategory | None
    worst_category: FlightCategory | None
    becoming: bool
    overlay: bool
    overlay_category: FlightCategory | None
    hours: tuple[int, ...]
    slices: tuple[int, ...]


def merge_hours(hours: Sequence[TimelineHour], indexes: Sequence[int]) -> StripCell:
    """One cell covering ``hours[i]`` for every ``i`` in ``indexes`` (in order, not empty)."""
    chosen = [hours[i] for i in indexes]
    slices = tuple(dict.fromkeys(s for hour in chosen for s in hour.slices))
    return StripCell(
        chosen[0].start,
        chosen[-1].end,
        worst_of(h.category for h in chosen),
        worst_of(h.worst_category for h in chosen),
        any(h.becoming for h in chosen),
        any(h.overlay for h in chosen),
        worst_of(h.overlay_category for h in chosen),
        tuple(indexes),
        slices,
    )


def group_cells(hours: Sequence[TimelineHour], step: int = 1) -> tuple[StripCell, ...]:
    """Display cells of ``step`` hours each, counted from the first hour (the last one may be shorter)."""
    step = max(1, step)
    bounds = range(0, len(hours), step)
    return tuple(merge_hours(hours, range(first, min(first + step, len(hours)))) for first in bounds)


def strip_for(taf: Taf) -> tuple[Timeline, tuple[TimelineHour, ...]]:
    """The expanded timeline of a TAF and its hourly summaries (both empty without a usable valid period)."""
    timeline = expand_timeline(taf)
    return timeline, timeline.hourly()


def cell_at(cells: Sequence[StripCell], moment: datetime) -> int | None:
    """Index of the cell holding ``moment`` (start inclusive, end exclusive), or ``None``."""
    for index, cell in enumerate(cells):
        if cell.start <= moment < cell.end:
            return index
    return None


def is_expired(hours: Sequence[TimelineHour], now: datetime) -> bool:
    """Whether the forecast has run out: it has hours, and ``now`` is past the last one."""
    return bool(hours) and now >= hours[-1].end


def mini_cells(hours: Sequence[TimelineHour], now: datetime, count: int = MINI_STRIP_HOURS) -> tuple[StripCell, ...]:
    """The next ``count`` hourly cells from the hour containing ``now``.

    Before the valid period it starts at the first hour; when the forecast runs out sooner than ``count`` hours it is
    shorter (the card pads it); a forecast that is already over gives no cells.
    """
    if not hours or is_expired(hours, now):
        return ()
    floor = now.replace(minute=0, second=0, microsecond=0)
    first = next((i for i, hour in enumerate(hours) if hour.end > floor), 0)
    return tuple(merge_hours(hours, [i]) for i in range(first, min(first + count, len(hours))))


def hour_step(count: int, width: int, *, narrow: bool, cell_width: int = 2) -> int:
    """Hours per cell: 3 in a narrow terminal or when ``count`` hourly cells would not fit in ``width`` columns."""
    if narrow or (width > 0 and count * cell_width > width):
        return 3
    return 1
