"""Readable plain-text decode: one labelled line per field, flags, a one-line summary and any parse warnings."""

from __future__ import annotations

from dataclasses import dataclass

from wxbrief.decode.model import FlightCategory, Metar, Modifier, SemanticKind
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


def _joined(texts: list[str]) -> str:
    return " ".join(texts)


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
        add(K.LABEL_CEILING, phrases.describe_ceiling(t, metar.ceiling, units), SemanticKind.SKY)
    if metar.temperature is not None:
        add(K.LABEL_TEMPERATURE, phrases.describe_temperature(t, metar.temperature, units), SemanticKind.TEMPERATURE)
    if metar.dewpoint is not None:
        add(K.LABEL_DEWPOINT, phrases.describe_temperature(t, metar.dewpoint, units), SemanticKind.TEMPERATURE)
    if metar.relative_humidity is not None:
        add(K.LABEL_HUMIDITY, phrases.describe_humidity(t, metar.relative_humidity), SemanticKind.TEMPERATURE)
    for pressure in metar.altimeters:
        add(K.LABEL_ALTIMETER, phrases.describe_pressure(t, pressure, units), SemanticKind.PRESSURE)
    tail = _joined([token.text for token in metar.tail_tokens])
    if tail:
        add(K.LABEL_TAIL, tail, SemanticKind.TREND)
    if metar.remarks_index is not None:
        remarks = _joined([token.text for token in metar.remarks_tokens])
        if remarks:
            add(K.LABEL_REMARKS, remarks, SemanticKind.REMARK)
    if metar.flags:
        add(K.LABEL_FLAGS, ", ".join(phrases.describe_flag(t, flag) for flag in metar.flags))
    add(K.LABEL_SUMMARY, phrases.summary_line(t, metar, units))
    return rows


def warning_lines(metar: Metar, t: Translator) -> list[str]:
    """A heading with the warning count followed by one line per warning; empty when there are none."""
    if not metar.warnings:
        return []
    lines = [t.plural(K.WARN_HEADING, len(metar.warnings))]
    lines.extend(f"  - {phrases.describe_warning(t, warning)}" for warning in metar.warnings)
    return lines


def render_plain(metar: Metar, t: Translator, units: UnitsMode = UnitsMode.MIXED) -> str:
    """The whole decode as plain text (no colour, no markup)."""
    rows = decode_rows(metar, t, units)
    width = max((len(row.label) for row in rows), default=0) + 2
    lines = [f"{row.label + ':':<{width}}{row.value}" for row in rows]
    warnings = warning_lines(metar, t)
    if warnings:
        lines.append("")
        lines.extend(warnings)
    return "\n".join(lines)
