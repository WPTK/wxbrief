"""Each raw token of a METAR next to its decoded meaning. Pure: tokens and the decoded model in, ``TokenPair`` out.

The decoded groups on a ``Metar`` come in report order, one per token for most kinds, so the Nth token of a kind
takes the Nth decoded group of that kind. A few groups span several tokens (``1 1/2SM``, ``WS ALL RWY``, a trend and
its elements); a run of such tokens is one pair. Every remark covers the token span the parser recorded for it.
"""

from __future__ import annotations

from dataclasses import dataclass

from wxbrief.decode.model import FreeText, Metar, Modifier, ParseWarning, SemanticKind
from wxbrief.decode.units import UnitsMode
from wxbrief.i18n import Translator
from wxbrief.i18n.keys import K
from wxbrief.render import phrases
from wxbrief.render.highlight import style_name

_LABELS: dict[SemanticKind, str] = {
    SemanticKind.TYPE: K.LABEL_REPORT,
    SemanticKind.STATION: K.LABEL_STATION,
    SemanticKind.TIME: K.LABEL_OBSERVED,
    SemanticKind.MODIFIER: K.LABEL_MODIFIERS,
    SemanticKind.WIND: K.LABEL_WIND,
    SemanticKind.WIND_VARIATION: K.LABEL_WIND,
    SemanticKind.VISIBILITY: K.LABEL_VISIBILITY,
    SemanticKind.RVR: K.LABEL_RVR,
    SemanticKind.WEATHER: K.LABEL_WEATHER,
    SemanticKind.SKY: K.LABEL_SKY,
    SemanticKind.TEMPERATURE: K.LABEL_TEMPERATURE,
    SemanticKind.PRESSURE: K.LABEL_ALTIMETER,
    SemanticKind.RECENT_WEATHER: K.LABEL_RECENT_WEATHER,
    SemanticKind.WIND_SHEAR: K.LABEL_WIND_SHEAR,
    SemanticKind.SEA_STATE: K.LABEL_SEA_STATE,
    SemanticKind.RUNWAY_STATE: K.LABEL_RUNWAY_STATE,
    SemanticKind.TREND: K.LABEL_TREND,
    SemanticKind.COLOR_STATE: K.LABEL_COLOR_STATE,
    SemanticKind.REMARK: K.LABEL_REMARK,
}
# Kinds whose consecutive tokens are one group.
_RUNS = frozenset(
    {
        SemanticKind.VISIBILITY,
        SemanticKind.WIND_SHEAR,
        SemanticKind.TREND,
        SemanticKind.COLOR_STATE,
        SemanticKind.SEA_STATE,
    }
)


@dataclass(frozen=True)
class TokenPair:
    """A stretch of the raw report, ``raw[start:end]``, and what it means.

    ``meaning`` is empty when nothing could be said about it (a remark nobody could decode); ``unknown`` marks a
    token the parser did not recognise, whose ``meaning`` is then the parser's warning.
    """

    start: int
    end: int
    text: str
    kind: SemanticKind
    label: str
    meaning: str
    unknown: bool = False

    @property
    def style(self) -> str:
        return style_name(self.kind)


def token_pairs(metar: Metar, t: Translator, units: UnitsMode) -> list[TokenPair]:
    """One pair per token (or run of tokens forming one group) of ``metar``, in report order."""
    raw = metar.raw
    pairs: list[TokenPair] = []
    counters: dict[SemanticKind, int] = {}
    warned = {w.start: w for w in metar.warnings}
    tokens = metar.tokens
    covered = _remark_pairs(metar, t, units)

    def nth(kind: SemanticKind) -> int:
        n = counters.get(kind, 0)
        counters[kind] = n + 1
        return n

    def pick(items: tuple, kind: SemanticKind) -> object | None:  # type: ignore[type-arg]
        n = nth(kind)
        return items[n] if n < len(items) else None

    index = 0
    while index < len(tokens):
        token = tokens[index]
        kind = token.kind
        start, end = token.start, token.end
        if kind is SemanticKind.TERMINATOR:
            index += 1
            continue
        if metar.remarks_index is not None and index > metar.remarks_index:
            remark = covered.get(index)
            if remark is not None:
                pairs.append(remark)
                index = remark.last + 1  # type: ignore[attr-defined]
                continue
        if kind in _RUNS:
            last = index
            while last + 1 < len(tokens) and tokens[last + 1].kind is kind:
                last += 1
            end = tokens[last].end
            index = last + 1
        else:
            index += 1
        meaning, unknown = _meaning(metar, t, units, kind, token.text, pick, warned.get(start))
        label = t.t(_LABELS[kind]) if kind in _LABELS else ""
        pairs.append(TokenPair(start, end, raw[start:end], kind, label, meaning, unknown))
    return pairs


def _meaning(  # noqa: PLR0911, PLR0912
    metar: Metar, t: Translator, units: UnitsMode, kind: SemanticKind, text: str, pick, warning: ParseWarning | None  # type: ignore[no-untyped-def]
) -> tuple[str, bool]:
    match kind:
        case SemanticKind.UNKNOWN:
            shown = warning or ParseWarning("unknown_token", 0, 0, text)
            return phrases.describe_warning(t, shown), True
        case SemanticKind.TYPE:
            return phrases.describe_report_type(t, metar.report_type), False
        case SemanticKind.STATION:
            return metar.station or "", False
        case SemanticKind.TIME:
            return phrases.describe_time(t, metar.observed), False
        case SemanticKind.MODIFIER:
            try:
                return phrases.describe_modifier(t, Modifier(text)), False
            except ValueError:
                return "", False
        case SemanticKind.WIND if metar.wind is not None:
            return phrases.describe_wind(t, metar.wind, units), False
        case SemanticKind.WIND_VARIATION if metar.wind_variation is not None:
            return f"{metar.wind_variation.start:03d}°-{metar.wind_variation.end:03d}°", False
        case SemanticKind.VISIBILITY if metar.visibility is not None:
            return phrases.describe_visibility(t, metar.visibility, units), False
        case SemanticKind.RVR:
            item = pick(metar.rvr, kind)
            return (phrases.describe_rvr(t, item, units) if item else ""), False  # type: ignore[arg-type]
        case SemanticKind.WEATHER:
            item = pick(metar.weather, kind)
            return (phrases.describe_weather_group(t, item) if item else ""), False  # type: ignore[arg-type]
        case SemanticKind.SKY:
            item = pick(metar.sky, kind)
            return (phrases.describe_cloud_layer(t, item, units) if item else ""), False  # type: ignore[arg-type]
        case SemanticKind.TEMPERATURE if metar.temperature is not None:
            temp = phrases.describe_temperature(t, metar.temperature, units)
            dew = phrases.describe_temperature(t, metar.dewpoint, units) if metar.dewpoint is not None else None
            if dew is None:
                return temp, False
            return f"{temp}; {t.t(K.LABEL_DEWPOINT)} {dew}", False
        case SemanticKind.PRESSURE:
            item = pick(metar.altimeters, kind)
            return (phrases.describe_pressure(t, item, units) if item else ""), False  # type: ignore[arg-type]
        case SemanticKind.RECENT_WEATHER:
            item = pick(metar.recent_weather, kind)
            return (phrases.describe_recent_weather(t, item) if item else ""), False  # type: ignore[arg-type]
        case SemanticKind.RUNWAY_STATE:
            item = pick(metar.runway_states, kind)
            return (phrases.describe_runway_state(t, item, units) if item else ""), False  # type: ignore[arg-type]
        case SemanticKind.WIND_SHEAR if metar.wind_shear:
            return phrases.describe_wind_shear(t, metar.wind_shear), False
        case SemanticKind.SEA_STATE if metar.sea_state is not None:
            return phrases.describe_sea_state(t, metar.sea_state, units), False
        case SemanticKind.COLOR_STATE if metar.color_state is not None:
            return phrases.describe_color_state(t, metar.color_state), False
        case SemanticKind.TREND if metar.trends:
            return "; ".join(phrases.describe_trend(t, trend, units) for trend in metar.trends), False
    return "", False


@dataclass(frozen=True)
class _RemarkPair(TokenPair):
    last: int = 0  # the index of the remark's last token


def _remark_pairs(metar: Metar, t: Translator, units: UnitsMode) -> dict[int, _RemarkPair]:
    """The pair of every remark after ``RMK``, keyed by the index of its first token."""
    found: dict[int, _RemarkPair] = {}
    for remark, (first, end) in zip(metar.remarks, metar.remark_spans, strict=False):
        if end <= first or end > len(metar.tokens):
            continue
        start, stop = metar.tokens[first].start, metar.tokens[end - 1].end
        if isinstance(remark, FreeText):
            meaning = phrases.decoded_free_text(t, remark.text) or ""
        else:
            meaning = phrases.describe_remark(t, remark, units)
        found[first] = _RemarkPair(
            start, stop, metar.raw[start:stop], SemanticKind.REMARK, t.t(K.LABEL_REMARK), meaning, False, end - 1
        )
    return found
