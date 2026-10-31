"""Expanding a TAF over time.

A TAF is a list of groups, each describing a forecast for a stretch of time. ``expand_timeline`` turns that into
slices: consecutive intervals over which the prevailing forecast and the set of temporary overlays do not change.

Semantics (from the reference notes ``taf.md`` and the COBOL decoder's ``657-INHERIT-GROUP``):

* The base forecast and every ``FM`` group *replace* the whole prevailing forecast from their time.
* ``BECMG`` lists only the elements that change. They take effect at the *end* of its window; slices inside the
  window are flagged ``becoming`` while the old elements still prevail. A later ``FM`` that starts before the window
  ends supersedes the ``BECMG``: it never takes effect, and its window closes where the ``FM`` begins.
* ``TEMPO``, ``PROB``, ``PROB TEMPO`` and ``INTER`` never change the prevailing forecast. Each is an overlay for its
  window (cut where a later ``FM`` begins: ``FM`` replaces everything, temporary groups included). Their elements
  are laid over what prevails (``merge``), so an overlay that lists only a visibility keeps the prevailing ceiling,
  exactly as the reference decoder inherits ``PREV-CEIL`` and ``PREV-VIS``. The overlay's flight category is that of
  the merged elements.
* A slice's ``category`` is the prevailing category, and ``worst_category`` the worst of it and every overlay's.

``TafPeriod.flight_category`` uses the same rules at the moment the group starts (``categorize_periods``).
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from wxbrief.decode.flightcat import flight_category, worst_of
from wxbrief.decode.model import (
    ChangeType,
    CloudLayer,
    FlightCategory,
    ForecastElements,
    SkyCondition,
    Taf,
    TafPeriod,
    Timeline,
    TimelineHour,
    TimelineOverlay,
    TimelineSlice,
    Visibility,
    WeatherGroup,
)
from wxbrief.decode.units import Distance, DistanceUnit

OVERLAY_TYPES = frozenset({ChangeType.TEMPO, ChangeType.PROB, ChangeType.PROB_TEMPO, ChangeType.INTER})

_TEN_KM_OR_MORE = Visibility(Distance(10000, DistanceUnit.M), unlimited=True)


def _spell_out_cavok(elements: ForecastElements) -> ForecastElements:
    """``CAVOK`` as what it states: visibility 10 km or more, no significant weather, no significant cloud."""
    if elements.visibility is None or not elements.visibility.cavok:
        return elements
    return replace(
        elements,
        visibility=_TEN_KM_OR_MORE,
        weather=elements.weather or (WeatherGroup(nsw=True),),
        sky=elements.sky or (CloudLayer(SkyCondition.NSC),),
    )


def merge(prevailing: ForecastElements, overlay: ForecastElements) -> ForecastElements:
    """The elements in force when ``overlay`` states some of them on top of ``prevailing``.

    An element the overlay lists replaces the prevailing one (a list of cloud layers or weather groups replaces the
    whole list; ``NSW`` replaces the weather); anything it leaves out carries over. ``CAVOK`` states visibility, weather
    and cloud together: when the overlay says ``CAVOK`` it replaces all three, and when it changes only some of them
    over a prevailing ``CAVOK`` the rest is what ``CAVOK`` meant (10 km or more, no significant weather, no
    significant cloud).
    """
    cavok = overlay.visibility is not None and overlay.visibility.cavok
    if not cavok and (overlay.visibility is not None or overlay.weather or overlay.sky):
        prevailing = _spell_out_cavok(prevailing)
    visibility = overlay.visibility if overlay.visibility is not None else prevailing.visibility
    weather = overlay.weather or prevailing.weather
    sky = overlay.sky or prevailing.sky
    if cavok:
        weather, sky = overlay.weather, overlay.sky
    return ForecastElements(
        wind=overlay.wind if overlay.wind is not None else prevailing.wind,
        visibility=visibility,
        weather=weather,
        sky=sky,
        color_state=overlay.color_state if overlay.color_state is not None else prevailing.color_state,
        wind_shear=overlay.wind_shear if overlay.wind_shear is not None else prevailing.wind_shear,
        altimeter=overlay.altimeter if overlay.altimeter is not None else prevailing.altimeter,
        icing=overlay.icing or prevailing.icing,
        turbulence=overlay.turbulence or prevailing.turbulence,
    )


def category_of(elements: ForecastElements) -> FlightCategory | None:
    """The flight category of a set of forecast elements (``None`` when neither visibility nor sky is known)."""
    return flight_category(elements.visibility, elements.sky)


@dataclass(frozen=True)
class _Event:
    """A moment at which the prevailing forecast changes: replaced (base, ``FM``) or merged into (``BECMG`` done)."""

    time: datetime
    index: int
    replace: bool
    elements: ForecastElements


@dataclass(frozen=True)
class _Window:
    """A stretch during which a group is visible on the timeline: a ``BECMG`` transition or an overlay."""

    index: int
    start: datetime
    end: datetime


@dataclass(frozen=True)
class _Plan:
    events: tuple[_Event, ...]
    transitions: tuple[_Window, ...]
    overlays: tuple[_Window, ...]


def _next_fm_start(periods: Sequence[TafPeriod], index: int) -> datetime | None:
    """Start of the first ``FM`` group after position ``index`` in the report that has a usable time."""
    for later in periods[index + 1 :]:
        if later.change is ChangeType.FM and later.start is not None:
            return later.start
    return None


def _plan(periods: Sequence[TafPeriod], valid_from: datetime | None) -> _Plan:
    events: list[_Event] = []
    transitions: list[_Window] = []
    overlays: list[_Window] = []
    for index, period in enumerate(periods):
        start = period.start
        change = period.change
        if change is ChangeType.BASE:
            when = start if start is not None else valid_from
            if when is not None:
                events.append(_Event(when, index, True, period.elements))
        elif change is ChangeType.FM:
            if start is not None:
                events.append(_Event(start, index, True, period.elements))
        elif change is ChangeType.BECMG:
            done = period.becoming_end
            if start is None or done is None:
                continue
            done = max(done, start)
            cut = _next_fm_start(periods, index)
            if cut is not None and cut <= done:
                # Superseded by an FM that begins before the transition is over: it never takes effect.
                if cut > start:
                    transitions.append(_Window(index, start, cut))
                continue
            transitions.append(_Window(index, start, done))
            events.append(_Event(done, index, False, period.elements))
        elif change in OVERLAY_TYPES and start is not None and period.end is not None:
            end = period.end
            cut = _next_fm_start(periods, index)
            if cut is not None and cut < end:
                end = cut
            if end > start:
                overlays.append(_Window(index, start, end))
    events.sort(key=lambda event: (event.time, event.index))
    return _Plan(tuple(events), tuple(transitions), tuple(overlays))


def _state_at(events: Sequence[_Event], moment: datetime) -> tuple[ForecastElements, int | None]:
    """The prevailing elements at ``moment`` and the index of the group that last set them."""
    state = ForecastElements()
    source: int | None = None
    for event in events:
        if event.time > moment:
            break
        state = event.elements if event.replace else merge(state, event.elements)
        source = event.index
    return state, source


def categorize_periods(periods: Sequence[TafPeriod], valid_from: datetime | None = None) -> list[FlightCategory | None]:
    """The flight category of each group, as the reference decoder prints it.

    ``BASE`` and ``FM`` are classified on their own elements. ``BECMG`` and the overlay kinds are classified on their
    elements merged over what prevails when the group starts (a group without a usable start inherits the forecast
    as it stands in report order).
    """
    plan = _plan(periods, valid_from)
    running = ForecastElements()
    categories: list[FlightCategory | None] = []
    for period in periods:
        if period.change in (ChangeType.BASE, ChangeType.FM):
            categories.append(category_of(period.elements))
            running = period.elements
            continue
        if period.start is not None:
            base, _ = _state_at(plan.events, period.start)
        else:
            base = running
        categories.append(category_of(merge(base, period.elements)))
        if period.change is ChangeType.BECMG:
            running = merge(running, period.elements)
    return categories


def _span(taf: Taf) -> tuple[datetime, datetime] | None:
    """The valid period, falling back to what the groups cover when the header lacks one."""
    starts = [period.start for period in taf.periods if period.start is not None]
    ends = [period.end for period in taf.periods if period.end is not None]
    start = taf.valid_from if taf.valid_from is not None else min(starts, default=None)
    end = taf.valid_to if taf.valid_to is not None else max(ends, default=None)
    if start is None or end is None or end <= start:
        return None
    return start, end


def expand_timeline(taf: Taf) -> Timeline:
    """Expand ``taf`` into slices; an empty timeline when the forecast has no usable valid period."""
    span = _span(taf)
    if span is None:
        return Timeline(taf.valid_from, taf.valid_to, (), worst_of(p.flight_category for p in taf.periods))
    start, end = span
    periods = taf.periods
    plan = _plan(periods, start)

    marks = {start, end}
    for event in plan.events:
        marks.add(event.time)
    for window in (*plan.transitions, *plan.overlays):
        marks.add(window.start)
        marks.add(window.end)
    bounds = sorted(mark for mark in marks if start <= mark <= end)

    slices: list[TimelineSlice] = []
    for lo, hi in itertools.pairwise(bounds):
        prevailing, source = _state_at(plan.events, lo)
        transition = next((w for w in plan.transitions if w.start <= lo < w.end), None)
        active = [w for w in plan.overlays if w.start <= lo < w.end]
        overlays = tuple(
            TimelineOverlay(
                w.index,
                periods[w.index].change,
                periods[w.index].probability,
                periods[w.index].elements,
                category_of(merge(prevailing, periods[w.index].elements)),
            )
            for w in active
        )
        category = category_of(prevailing)
        slices.append(
            TimelineSlice(
                lo,
                hi,
                prevailing,
                transition is not None,
                overlays,
                category,
                worst_of([category, *(overlay.category for overlay in overlays)]),
                source,
                transition.index if transition is not None else None,
            )
        )
    return Timeline(start, end, tuple(slices), worst_of(item.worst_category for item in slices))


def slice_at(timeline: Timeline, moment: datetime) -> TimelineSlice | None:
    """The slice containing ``moment`` (start inclusive, end exclusive); ``None`` outside the forecast."""
    for item in timeline.slices:
        if item.start <= moment < item.end:
            return item
    return None


def hourly_cells(timeline: Timeline) -> tuple[TimelineHour, ...]:
    """One cell per whole UTC hour covering the forecast, taking the worst case within each hour."""
    if timeline.start is None or timeline.end is None or not timeline.slices:
        return ()
    cell = timeline.start.replace(minute=0, second=0, microsecond=0)
    cells: list[TimelineHour] = []
    while cell < timeline.end:
        following = cell + timedelta(hours=1)
        touching = [i for i, item in enumerate(timeline.slices) if item.start < following and item.end > cell]
        chosen = [timeline.slices[i] for i in touching]
        overlay_categories = [overlay.category for item in chosen for overlay in item.overlays]
        cells.append(
            TimelineHour(
                cell,
                following,
                worst_of(item.category for item in chosen),
                worst_of(item.worst_category for item in chosen),
                any(item.becoming for item in chosen),
                any(item.overlays for item in chosen),
                worst_of(overlay_categories),
                tuple(touching),
            )
        )
        cell = following
    return tuple(cells)
