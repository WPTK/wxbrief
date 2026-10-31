"""TAF parser: the header, the base forecast, then the change groups, with the same tolerance as the METAR parser.

A TAF reads ``TAF [AMD|COR|CNL|NIL] STATION DDHHMMZ DDHH/DDHH`` followed by the base forecast and any number of change
groups (``FMDDHHMM``, ``BECMG``, ``TEMPO``, ``INTER`` and ``PROBnn [TEMPO]`` with a ``DDHH/DDHH`` window), ending
with an optional ``RMK`` trailer. The elements of every group (wind, visibility, weather, sky, colour state) are read
by the shared ``parse_trend_body`` with the same group parsers as the METAR body; the TAF-only groups (wind shear,
``TX``/``TN``, ``QNH``, icing, turbulence) come from ``groups/tafgroups.py``.

Times are resolved against the issue time: the valid period first (its end is forced to lie after its start, whatever
the month), then every group time against the start of the valid period. Old-style forms (``131212`` as the valid
period, ``BECMG 1315``, ``FM1800``) are read with a ``legacy_format`` warning.

``parse_taf`` never raises. A group that cannot be read leaves its tokens ``UNKNOWN`` with a warning and parsing
carries on; every non-blank character of the input ends up in exactly one token.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

from wxbrief.decode.derived import derive_taf
from wxbrief.decode.detect import detect_flavor
from wxbrief.decode.groups.header import parse_modifier
from wxbrief.decode.groups.tafgroups import (
    PeriodExtras,
    RawTemperature,
    fm_of,
    legacy_fm_of,
    legacy_valid_of,
    legacy_window_of,
    probability_of,
    starts_change_group,
    window_of,
)
from wxbrief.decode.groups.trend import parse_trend_body
from wxbrief.decode.model import (
    ChangeType,
    ForecastElements,
    Modifier,
    ParseWarning,
    SemanticKind,
    Taf,
    TafPeriod,
    TafTemperature,
)
from wxbrief.decode.tables import MODIFIER_CODES
from wxbrief.decode.timeline import categorize_periods
from wxbrief.decode.times import next_clock_time, resolve_day_time, resolve_day_time_after, resolve_report_time
from wxbrief.decode.tokens import Cursor, Token, tokenize

WARN_UNKNOWN_TOKEN = "unknown_token"
WARN_PARSER_ERROR = "parser_error"
WARN_LEGACY_FORMAT = "legacy_format"
WARN_MISSING_TIME = "missing_time"
WARN_OUTSIDE_PERIOD = "outside_period"

_STATION = re.compile(r"^[A-Z][A-Z0-9]{3}$")
_ISSUE = re.compile(r"^(\d{2})(\d{2})(\d{2})Z$")
# Times, change keywords and notes look like metre visibilities or trend words to the flavor detector but say nothing.
_KINDS_NEUTRAL_FOR_FLAVOR = frozenset({SemanticKind.TIME, SemanticKind.TREND, SemanticKind.REMARK})


@dataclass
class _Group:
    """A change group (or the base forecast) while it is being read; ``first``/``last`` index the report tokens."""

    change: ChangeType
    probability: int | None
    start: datetime | None
    end: datetime | None
    becoming_end: datetime | None
    first: int
    last: int = 0
    elements: ForecastElements = field(default_factory=ForecastElements)


@dataclass
class _Draft:
    reference: datetime
    warnings: list[ParseWarning] = field(default_factory=list)
    modifiers: list[Modifier] = field(default_factory=list)
    station: str | None = None
    issue_time: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    legacy: bool = False
    groups: list[_Group] = field(default_factory=list)
    temperatures: list[RawTemperature] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    remarks_index: int | None = None

    def warn(self, code: str, token: Token) -> None:
        self.warnings.append(ParseWarning(code, token.start, token.end, token.text))

    @property
    def anchor(self) -> datetime:
        """The moment group times are resolved against: the start of the valid period."""
        return self.valid_from or self.issue_time or self.reference

    def previous_start(self) -> datetime:
        """Start of the last group read so far, the lower bound for old-style times that give no day."""
        for group in reversed(self.groups):
            if group.start is not None:
                return group.start
        return self.anchor


# --- header --------------------------------------------------------------------------------------------------


def _looks_like_station(cur: Cursor) -> bool:
    """A four-character indicator is the station if a time follows it, or it comes straight after ``TAF``."""
    token = cur.peek()
    if token is None or not _STATION.match(token.text) or token.text.endswith("SM"):
        return False
    if token.text in MODIFIER_CODES:
        return False
    following = cur.peek(1)
    if following is not None and (
        _ISSUE.match(following.text) or window_of(following.text) or following.text in ("NIL", "CNL")
    ):
        return True
    at_head = all(cur.kind_at(i) in (SemanticKind.TYPE, SemanticKind.MODIFIER) for i in range(cur.pos))
    return at_head and (cur.pos > 0 or len(cur) == 1)


def _resolve_issue(draft: _Draft, token: Token) -> None:
    match = _ISSUE.match(token.text)
    if match is None:
        return
    moment, warning = resolve_report_time(
        int(match.group(1)), int(match.group(2)), int(match.group(3)), draft.reference
    )
    if moment is None and warning is not None:
        draft.warn(warning, token)
    draft.issue_time = moment


def _resolve_valid(draft: _Draft, token: Token, start: tuple[int, int], end: tuple[int, int]) -> None:
    """Set the valid period from ``(day, hour)`` pairs: the end is the first such moment after the start."""
    if draft.issue_time is not None:
        moment, warning = resolve_day_time(start[0], start[1], 0, draft.issue_time)
    else:  # no issue time: the period is read against the moment the TAF is read, which it cannot lie far after
        moment, warning = resolve_report_time(start[0], start[1], 0, draft.reference)
    if moment is None and warning is not None:
        draft.warn(warning, token)
        return
    draft.valid_from = moment
    if moment is None:
        return
    finish, warning = resolve_day_time_after(end[0], end[1], 0, moment)
    if finish is None and warning is not None:
        draft.warn(warning, token)
        return
    draft.valid_to = finish


def _resolve_legacy_valid(draft: _Draft, token: Token, day: int, from_hour: int, to_hour: int) -> None:
    """The old valid period ``DDHHHH``: the day, then the hour it starts and the hour it ends (the next such hour)."""
    if draft.issue_time is not None:
        moment, warning = resolve_day_time(day, from_hour, 0, draft.issue_time)
    else:
        moment, warning = resolve_report_time(day, from_hour, 0, draft.reference)
    if moment is None and warning is not None:
        draft.warn(warning, token)
        return
    draft.valid_from = moment
    if moment is not None:
        draft.valid_to = next_clock_time(to_hour, 0, moment + timedelta(minutes=1))


def _parse_header(cur: Cursor, draft: _Draft) -> None:
    stage = 0  # 0 type, 1 station, 2 issue time, 3 valid period, 4 done
    while (token := cur.peek()) is not None:
        text = token.text
        if token.kind is SemanticKind.TERMINATOR:
            return
        modifier = parse_modifier(cur)
        if modifier is not None:
            draft.modifiers.append(modifier)
            continue
        if stage == 0 and text == "TAF":
            cur.take(SemanticKind.TYPE)
            stage = 1
            continue
        if stage <= 1 and _looks_like_station(cur):
            cur.take(SemanticKind.STATION)
            draft.station = text
            stage = 2
            continue
        if stage <= 2 and _ISSUE.match(text):
            cur.take(SemanticKind.TIME)
            _resolve_issue(draft, token)
            stage = 3
            continue
        if stage <= 3 and (pair := window_of(text)) is not None:
            cur.take(SemanticKind.TIME)
            _resolve_valid(draft, token, (pair[0].day, pair[0].hour), (pair[1].day, pair[1].hour))
            stage = 4
            continue
        if 2 <= stage <= 3 and (old := legacy_valid_of(text)) is not None:
            cur.take(SemanticKind.TIME)
            draft.legacy = True
            draft.warn(WARN_LEGACY_FORMAT, token)
            _resolve_legacy_valid(draft, token, *old)
            stage = 4
            continue
        return


# --- change groups -------------------------------------------------------------------------------------------


def _day_hour(draft: _Draft, token: Token, day: int, hour: int, minute: int) -> datetime | None:
    moment, warning = resolve_day_time(day, hour, minute, draft.anchor)
    if moment is None and warning is not None:
        draft.warn(warning, token)
    return moment


def _read_window(cur: Cursor, draft: _Draft, keyword: Token) -> tuple[datetime | None, datetime | None]:
    """The ``DDHH/DDHH`` window after a change keyword (or, in an old-style TAF, ``HHHH``)."""
    token = cur.peek()
    if token is None:
        draft.warn(WARN_MISSING_TIME, keyword)
        return None, None
    pair = window_of(token.text)
    if pair is not None:
        cur.take(SemanticKind.TREND)
        start = _day_hour(draft, token, pair[0].day, pair[0].hour, 0)
        if start is None:
            return None, None
        end, warning = resolve_day_time_after(pair[1].day, pair[1].hour, 0, start)
        if end is None and warning is not None:
            draft.warn(warning, token)
        return start, end
    old = legacy_window_of(token.text) if draft.legacy else None
    if old is not None:
        cur.take(SemanticKind.TREND)
        draft.warn(WARN_LEGACY_FORMAT, token)
        start = next_clock_time(old[0], 0, draft.previous_start())
        end = next_clock_time(old[1], 0, start.replace(minute=1)) if start is not None else None
        return start, end
    draft.warn(WARN_MISSING_TIME, keyword)
    return None, None


def _read_header(cur: Cursor, draft: _Draft) -> _Group:
    """The keyword and time of the change group at the cursor."""
    first = cur.pos
    token = cur.peek()
    assert token is not None  # the caller peeked
    text = token.text
    fm = fm_of(text)
    if fm is not None:
        cur.take(SemanticKind.TREND)
        return _Group(ChangeType.FM, None, _day_hour(draft, token, fm.day, fm.hour, fm.minute), None, None, first)
    old_fm = legacy_fm_of(text)
    if old_fm is not None:
        cur.take(SemanticKind.TREND)
        draft.warn(WARN_LEGACY_FORMAT, token)
        start = next_clock_time(old_fm[0], old_fm[1], draft.previous_start())
        return _Group(ChangeType.FM, None, start, None, None, first)

    probability = probability_of(text)
    keyword = token
    cur.take(SemanticKind.TREND)
    if probability is None:
        change = {"BECMG": ChangeType.BECMG, "TEMPO": ChangeType.TEMPO, "INTER": ChangeType.INTER}[text]
    else:
        change = ChangeType.PROB
        following = cur.peek()
        if following is not None and following.text in ("TEMPO", "INTER"):
            cur.take(SemanticKind.TREND)
            keyword = following
            change = ChangeType.PROB_TEMPO if following.text == "TEMPO" else ChangeType.PROB_INTER
    start, end = _read_window(cur, draft, keyword)
    if change is ChangeType.BECMG:
        return _Group(change, None, start, end, end, first)
    return _Group(change, probability, start, end, None, first)


def _open_group(cur: Cursor, draft: _Draft, *, base: bool) -> _Group:
    """The base forecast (no keyword) or the change group whose keyword and window are at the cursor."""
    if base:
        return _Group(ChangeType.BASE, None, draft.valid_from, None, None, cur.pos)
    return _read_header(cur, draft)


def _check_inside_period(cur: Cursor, draft: _Draft, group: _Group) -> None:
    """Warn about a change group that starts outside the valid period: the timeline cannot place it."""
    if group.change is ChangeType.BASE or group.start is None:
        return
    before = draft.valid_from is not None and group.start < draft.valid_from
    after = draft.valid_to is not None and group.start >= draft.valid_to
    if before or after:
        draft.warn(WARN_OUTSIDE_PERIOD, cur.token_at(group.first))


def _read_group(cur: Cursor, draft: _Draft, *, base: bool) -> _Group:
    """One group: its keyword and window (none for the base forecast), then its elements up to the next group."""
    group = _open_group(cur, draft, base=base)
    _check_inside_period(cur, draft, group)
    body_start = cur.pos
    extras = PeriodExtras(draft.temperatures, draft.notes)

    def stop(token: Token) -> bool:
        return token.kind is SemanticKind.TERMINATOR or token.text == "RMK" or starts_change_group(token.text)

    _, elements = parse_trend_body(cur, None, stop, extras)
    group.elements = replace(
        elements,
        wind_shear=extras.wind_shear,
        altimeter=extras.altimeter,
        icing=tuple(extras.icing),
        turbulence=tuple(extras.turbulence),
    )
    group.last = cur.pos
    for index in range(body_start, cur.pos):
        if cur.kind_at(index) is SemanticKind.UNKNOWN:
            draft.warn(WARN_UNKNOWN_TOKEN, cur.token_at(index))
    return group


# --- assembling the result ---------------------------------------------------------------------------------


def _close(periods: list[TafPeriod], valid_to: datetime | None) -> list[TafPeriod]:
    """Set ``end`` on the base, ``FM`` and ``BECMG`` groups: where the next ``FM`` or ``BECMG`` begins.

    Only the next such group counts, and only if it starts later: a ``BECMG`` that opens at the start of the valid
    period (or is out of order) leaves the group before it running to the end of the valid period, as AWC does.
    """
    closed: list[TafPeriod] = []
    for index, period in enumerate(periods):
        if period.change not in (ChangeType.BASE, ChangeType.FM, ChangeType.BECMG):
            closed.append(period)
            continue
        end = valid_to
        following = next((p for p in periods[index + 1 :] if p.change in (ChangeType.FM, ChangeType.BECMG)), None)
        if following is not None and following.start is not None and (
            period.start is None or following.start > period.start
        ):
            end = following.start
        closed.append(replace(period, end=end))
    return closed


def _temperatures(draft: _Draft) -> tuple[TafTemperature, ...]:
    found: list[TafTemperature] = []
    for raw in draft.temperatures:
        moment, _ = resolve_day_time(raw.day, raw.hour, 0, draft.anchor)
        found.append(TafTemperature(raw.kind, raw.temperature, raw.day, raw.hour, moment))
    return tuple(found)


def _remarks_text(raw: str, tokens: tuple[Token, ...], index: int) -> str:
    body = [tok for tok in tokens[index + 1 :] if tok.kind is not SemanticKind.TERMINATOR]
    if not body:
        return ""
    return raw[body[0].start : body[-1].end]


def _remarks(raw: str, tokens: tuple[Token, ...], draft: _Draft) -> str | None:
    """The closing notes followed by the text after ``RMK``; ``None`` when the TAF has neither."""
    if draft.remarks_index is None and not draft.notes:
        return None
    trailer = _remarks_text(raw, tokens, draft.remarks_index) if draft.remarks_index is not None else ""
    return " ".join([*draft.notes, trailer]).strip()


def _parse(raw: str, reference: datetime | None) -> Taf:
    if reference is None:
        reference = datetime.now(UTC)
    elif reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)

    tokens = tokenize(raw)
    cur = Cursor(tokens)
    draft = _Draft(reference)

    _parse_header(cur, draft)
    first_body = True
    while not cur.at_end:
        token = cur.peek()
        if token is None:
            break
        if token.kind is SemanticKind.TERMINATOR:
            cur.take(SemanticKind.TERMINATOR)
            continue
        if token.text == "RMK":
            draft.remarks_index = cur.pos
            while (rest := cur.peek()) is not None:
                cur.take(SemanticKind.TERMINATOR if rest.kind is SemanticKind.TERMINATOR else SemanticKind.REMARK)
            break
        is_base = first_body and not starts_change_group(token.text)
        draft.groups.append(_read_group(cur, draft, base=is_base))
        first_body = False

    tagged = cur.tagged()
    periods = [
        TafPeriod(
            group.change,
            group.probability,
            group.start,
            group.end,
            group.elements,
            None,
            tagged[group.first : group.last],
            group.becoming_end,
        )
        for group in draft.groups
    ]
    periods = _close(periods, draft.valid_to)
    categories = categorize_periods(periods, draft.valid_from)
    periods = [replace(period, flight_category=category) for period, category in zip(periods, categories, strict=True)]

    base = periods[0] if periods and periods[0].change is ChangeType.BASE else None
    changes = tuple(periods[1:] if base is not None else periods)
    flavor = detect_flavor([tok for tok in tagged if tok.kind not in _KINDS_NEUTRAL_FOR_FLAVOR]).flavor
    taf = Taf(
        raw=raw,
        station=draft.station,
        issue_time=draft.issue_time,
        valid_from=draft.valid_from,
        valid_to=draft.valid_to,
        modifiers=tuple(draft.modifiers),
        base=base,
        changes=changes,
        remarks=_remarks(raw, tagged, draft),
        flavor=flavor,
        tokens=tagged,
        warnings=tuple(draft.warnings),
        temperatures=_temperatures(draft),
        legacy=draft.legacy,
    )
    return derive_taf(taf)


def _failsafe(raw: str) -> Taf:
    """The result when the parser itself fails: every token unknown, one warning, nothing lost."""
    tokens = tuple(tokenize(raw))
    return Taf(raw=raw, tokens=tokens, warnings=(ParseWarning(WARN_PARSER_ERROR, 0, len(raw), raw),))


def parse_taf(raw: str, reference: datetime | None = None) -> Taf:
    """Decode one TAF.

    ``reference`` resolves the day-of-month in the issue time (``DDHHMMZ``) to a real date: the receipt time of the
    forecast, a date chosen by the user, or now when omitted. Never raises.
    """
    try:
        return _parse(raw, reference)
    except Exception:
        return _failsafe(raw)
