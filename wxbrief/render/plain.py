"""Readable plain-text decode: one labelled line per field, flags, a one-line summary and any parse warnings.

A METAR is a list of rows. A TAF is a header (station, issue time, valid period, worst category ...) followed by one
block per forecast period: its change type and time span in UTC, the decoded elements and its flight category.
"""

from __future__ import annotations

from dataclasses import dataclass

from wxbrief.decode.colorstate import reported_matches_computed
from wxbrief.decode.flightcat import ceiling_for_classification
from wxbrief.decode.model import (
    ChangeType,
    ColorState,
    ColorStateRemark,
    FlightCategory,
    ForecastElements,
    FreeText,
    Metar,
    Modifier,
    SemanticKind,
    Taf,
    TafPeriod,
)
from wxbrief.decode.units import UnitsMode
from wxbrief.i18n import Translator
from wxbrief.i18n.keys import K
from wxbrief.render import phrases
from wxbrief.render.highlight import style_name

_SHOWN_AS_FLAGS = frozenset({Modifier.AUTO, Modifier.COR})


@dataclass(frozen=True)
class DecodeRow:
    """One line of a decode. ``style`` is a Rich style name (``wx.wind``) for renderers that colour values."""

    label: str
    value: str
    style: str | None = None
    category: FlightCategory | None = None  # set on the flight-category row so a renderer can draw a badge


def _tail_rows(metar: Metar, t: Translator, units: UnitsMode) -> list[DecodeRow]:
    """Runway state, wind shear, recent weather, sea state, colour state and trends, decoded."""
    rows: list[DecodeRow] = []

    def add(label_key: str, value: str, kind: SemanticKind) -> None:
        rows.append(DecodeRow(t.t(label_key), value, style_name(kind)))

    for state in metar.runway_states:
        add(K.LABEL_RUNWAY_STATE, phrases.describe_runway_state(t, state, units), SemanticKind.RUNWAY_STATE)
    if metar.wind_shear:
        add(K.LABEL_WIND_SHEAR, phrases.describe_wind_shear(t, metar.wind_shear), SemanticKind.WIND_SHEAR)
    for recent in metar.recent_weather:
        add(K.LABEL_RECENT_WEATHER, phrases.describe_recent_weather(t, recent), SemanticKind.RECENT_WEATHER)
    if metar.sea_state is not None:
        add(K.LABEL_SEA_STATE, phrases.describe_sea_state(t, metar.sea_state, units), SemanticKind.SEA_STATE)
    if metar.color_state is not None:
        add(K.LABEL_COLOR_STATE, phrases.describe_color_state(t, metar.color_state), SemanticKind.COLOR_STATE)
        computed = metar.computed_color_state
        reported = _reported_color(metar)
        if computed is not None and reported_matches_computed(reported, computed, _ceiling_ft(metar)) is not True:
            shown = phrases.describe_color_code(t, ColorState(computed))
            add(K.LABEL_COLOR_STATE_COMPUTED, shown, SemanticKind.COLOR_STATE)
    for trend in metar.trends:
        add(K.LABEL_TREND, phrases.describe_trend(t, trend, units), SemanticKind.TREND)
    return rows


def _ceiling_ft(metar: Metar) -> float | None:
    return ceiling_for_classification(metar.sky, metar.cavok)


def _reported_color(metar: Metar) -> ColorState | None:
    return metar.color_state.current if metar.color_state is not None else None


def _remark_rows(metar: Metar, t: Translator, units: UnitsMode) -> list[DecodeRow]:
    """One row per decoded remark, then the free text that still contains words nobody could decode."""
    if metar.remarks_index is None:
        return []
    style = style_name(SemanticKind.REMARK)
    label = t.t(K.LABEL_REMARK)
    # A colour state found in the remarks is already the report's Color state row; it is not shown a second time.
    shown = [r for r in metar.remarks if not (isinstance(r, ColorStateRemark) and r.group == metar.color_state)]
    rows: list[DecodeRow] = []
    for remark in shown:
        if isinstance(remark, FreeText):  # spelled out only when every word is known; else the not-decoded row
            words = phrases.decoded_free_text(t, remark.text)
            if words is not None:
                rows.append(DecodeRow(label, words, style))
        else:
            rows.append(DecodeRow(label, phrases.describe_remark(t, remark, units), style))
    undecoded = phrases.undecoded_free_text(t, metar)
    if undecoded:
        rows.append(DecodeRow(t.t(K.LABEL_REMARKS), " ".join(undecoded), style))
    return rows


def decode_rows(metar: Metar, t: Translator, units: UnitsMode) -> list[DecodeRow]:
    """The decoded fields of ``metar`` in display order; absent groups produce no row."""
    rows: list[DecodeRow] = []

    def add(label_key: str, value: str, kind: SemanticKind | None = None) -> None:
        rows.append(DecodeRow(t.t(label_key), value, style_name(kind) if kind is not None else None))

    if metar.station:
        add(K.LABEL_STATION, metar.station, SemanticKind.STATION)
    if metar.station or metar.observed or any(token.kind is SemanticKind.TYPE for token in metar.tokens):
        add(K.LABEL_REPORT, phrases.describe_report_type(t, metar.report_type), SemanticKind.TYPE)
    # AUTO and COR already show up as flags; the other modifiers (NIL, RTD, ...) have no flag.
    notes = [modifier for modifier in metar.modifiers if modifier not in _SHOWN_AS_FLAGS]
    if notes:
        add(K.LABEL_MODIFIERS, "; ".join(phrases.describe_modifier(t, mod) for mod in notes), SemanticKind.MODIFIER)
    if metar.observed is not None:
        add(K.LABEL_OBSERVED, phrases.describe_time(t, metar.observed), SemanticKind.TIME)
    if metar.flight_category is not None:
        rows.append(
            DecodeRow(
                t.t(K.LABEL_CATEGORY),
                phrases.describe_flight_category(t, metar.flight_category),
                category=metar.flight_category,
            )
        )
    if metar.wind is not None:
        add(K.LABEL_WIND, phrases.describe_wind(t, metar.wind, units, metar.wind_variation), SemanticKind.WIND)
    if metar.visibility is not None:
        add(K.LABEL_VISIBILITY, phrases.describe_visibility(t, metar.visibility, units), SemanticKind.VISIBILITY)
    for rvr in metar.rvr:
        add(K.LABEL_RVR, phrases.describe_rvr(t, rvr, units), SemanticKind.RVR)
    if metar.weather:
        add(K.LABEL_WEATHER, phrases.describe_weather(t, metar.weather), SemanticKind.WEATHER)
    for layer in metar.sky:
        add(K.LABEL_SKY, phrases.describe_cloud_layer(t, layer, units), SemanticKind.SKY)
    if metar.sky:
        add(K.LABEL_CEILING, phrases.describe_ceiling(t, metar, units), SemanticKind.SKY)
    if metar.temperature is not None:
        add(K.LABEL_TEMPERATURE, phrases.describe_temperature(t, metar.temperature, units), SemanticKind.TEMPERATURE)
    if metar.dewpoint is not None:
        add(K.LABEL_DEWPOINT, phrases.describe_temperature(t, metar.dewpoint, units), SemanticKind.TEMPERATURE)
    if metar.relative_humidity is not None:
        add(K.LABEL_HUMIDITY, phrases.describe_humidity(t, metar.relative_humidity), SemanticKind.TEMPERATURE)
    for pressure in metar.altimeters:
        add(K.LABEL_ALTIMETER, phrases.describe_pressure(t, pressure, units), SemanticKind.PRESSURE)
    rows.extend(_tail_rows(metar, t, units))
    rows.extend(_remark_rows(metar, t, units))
    if metar.flags:
        add(K.LABEL_FLAGS, ", ".join(phrases.describe_flag(t, flag) for flag in metar.flags))
    add(K.LABEL_SUMMARY, phrases.summary_line(t, metar, units))
    return rows


@dataclass(frozen=True)
class DecodeBlock:
    """A titled group of rows: one forecast period of a TAF."""

    title: str
    rows: list[DecodeRow]
    change: ChangeType
    category: FlightCategory | None = None


def element_rows(
    elements: ForecastElements, category: FlightCategory | None, t: Translator, units: UnitsMode
) -> list[DecodeRow]:
    """The elements a forecast states, one row each, then its flight category."""
    rows: list[DecodeRow] = []

    def add(label_key: str, value: str, kind: SemanticKind) -> None:
        rows.append(DecodeRow(t.t(label_key), value, style_name(kind)))

    if elements.wind is not None:
        add(K.LABEL_WIND, phrases.describe_wind(t, elements.wind, units), SemanticKind.WIND)
    if elements.visibility is not None:
        add(K.LABEL_VISIBILITY, phrases.describe_visibility(t, elements.visibility, units), SemanticKind.VISIBILITY)
    if elements.weather:
        add(K.LABEL_WEATHER, phrases.describe_weather(t, elements.weather), SemanticKind.WEATHER)
    for layer in elements.sky:
        add(K.LABEL_SKY, phrases.describe_cloud_layer(t, layer, units), SemanticKind.SKY)
    if elements.color_state is not None:
        add(K.LABEL_COLOR_STATE, phrases.describe_color_code(t, elements.color_state), SemanticKind.COLOR_STATE)
    if elements.wind_shear is not None:
        shear = phrases.describe_wind_shear_layer(t, elements.wind_shear, units)
        add(K.LABEL_WIND_SHEAR, shear, SemanticKind.WIND_SHEAR)
    if elements.altimeter is not None:
        add(K.LABEL_ALTIMETER, phrases.describe_pressure(t, elements.altimeter, units), SemanticKind.PRESSURE)
    for icing in elements.icing:
        add(K.LABEL_ICING, phrases.describe_icing(t, icing, units), SemanticKind.HAZARD)
    for turbulence in elements.turbulence:
        add(K.LABEL_TURBULENCE, phrases.describe_turbulence(t, turbulence, units), SemanticKind.HAZARD)
    if not rows:
        rows.append(DecodeRow(t.t(K.LABEL_DETAILS), t.t(K.TREND_NO_DETAILS)))
    if category is not None:
        rows.append(DecodeRow(t.t(K.LABEL_CATEGORY), phrases.describe_flight_category(t, category), category=category))
    return rows


def _period_rows(period: TafPeriod, t: Translator, units: UnitsMode) -> list[DecodeRow]:
    """The elements a forecast period states, one row each, then its flight category."""
    return element_rows(period.elements, period.flight_category, t, units)


def taf_header_rows(taf: Taf, t: Translator, units: UnitsMode) -> list[DecodeRow]:
    """The report-level fields of a TAF: station, type, issue time, valid period, worst category, flags, extremes."""
    rows: list[DecodeRow] = []

    def add(label_key: str, value: str, kind: SemanticKind | None = None) -> None:
        rows.append(DecodeRow(t.t(label_key), value, style_name(kind) if kind is not None else None))

    def add_notes() -> None:
        notes = "; ".join(phrases.describe_modifier(t, modifier) for modifier in taf.modifiers)
        add(K.LABEL_MODIFIERS, notes, SemanticKind.MODIFIER)

    if taf.cancelled:  # a withdrawn forecast says so before anything else
        add_notes()
    if taf.station:
        add(K.LABEL_STATION, taf.station, SemanticKind.STATION)
    add(K.LABEL_REPORT, phrases.describe_report_type(t, taf.report_type), SemanticKind.TYPE)
    if taf.modifiers and not taf.cancelled:
        add_notes()
    if taf.issue_time is not None:
        add(K.LABEL_ISSUED, phrases.describe_time(t, taf.issue_time), SemanticKind.TIME)
    if taf.valid_from is not None:
        add(K.LABEL_VALID, phrases.describe_span(t, taf.valid_from, taf.valid_to), SemanticKind.TIME)
    if taf.worst_category is not None:
        worst = phrases.describe_flight_category(t, taf.worst_category)
        rows.append(DecodeRow(t.t(K.LABEL_WORST_CATEGORY), worst, category=taf.worst_category))
    if taf.flags:
        add(K.LABEL_FLAGS, ", ".join(phrases.describe_flag(t, flag) for flag in taf.flags))
    for item in taf.temperatures:
        label = phrases.describe_taf_temperature_label(t, item)
        value = phrases.describe_taf_temperature(t, item, units)
        rows.append(DecodeRow(label, value, style_name(SemanticKind.TEMPERATURE)))
    if taf.remarks:
        add(K.LABEL_REMARK, taf.remarks, SemanticKind.REMARK)
    return rows


def taf_blocks(taf: Taf, t: Translator, units: UnitsMode) -> list[DecodeBlock]:
    """One block per forecast period, in report order."""
    return [
        DecodeBlock(
            phrases.describe_change_header(t, period),
            _period_rows(period, t, units),
            period.change,
            period.flight_category,
        )
        for period in taf.periods
    ]


def taf_summary_row(taf: Taf, t: Translator, units: UnitsMode) -> DecodeRow:
    return DecodeRow(t.t(K.LABEL_SUMMARY), phrases.describe_taf_summary(t, taf, units))


def warning_lines(report: Metar | Taf, t: Translator) -> list[str]:
    """A heading with the warning count followed by one line per warning; empty when there are none."""
    if not report.warnings:
        return []
    lines = [t.plural(K.WARN_HEADING, len(report.warnings))]
    lines.extend(f"  - {phrases.describe_warning(t, warning)}" for warning in report.warnings)
    return lines


def _render_taf(taf: Taf, t: Translator, units: UnitsMode) -> list[str]:
    header = taf_header_rows(taf, t, units)
    blocks = taf_blocks(taf, t, units)
    summary = taf_summary_row(taf, t, units)
    every_row = [*header, summary, *(row for block in blocks for row in block.rows)]
    width = max((len(row.label) for row in every_row), default=0) + 2
    lines = [f"{row.label + ':':<{width}}{row.value}" for row in header]
    for block in blocks:
        lines.append("")
        lines.append(block.title)
        lines.extend(f"  {row.label + ':':<{width - 2}}{row.value}" for row in block.rows)
    lines.append("")
    lines.append(f"{summary.label + ':':<{width}}{summary.value}")
    return lines


def render_plain(report: Metar | Taf, t: Translator, units: UnitsMode = UnitsMode.MIXED) -> str:
    """The whole decode as plain text (no colour, no markup)."""
    if isinstance(report, Taf):
        lines = _render_taf(report, t, units)
    else:
        rows = decode_rows(report, t, units)
        width = max((len(row.label) for row in rows), default=0) + 2
        lines = [f"{row.label + ':':<{width}}{row.value}" for row in rows]
    warnings = warning_lines(report, t)
    if warnings:
        lines.append("")
        lines.extend(warnings)
    return "\n".join(lines)
