"""Splitting pasted text into reports and decoding each one as a METAR/SPECI or a TAF.

``split_reports`` cuts a blob into one string per report. A new report starts at

* a line that begins with ``METAR``, ``SPECI`` or ``TAF`` (also in the middle of a line, when the keyword is followed by
  what looks like a station or a modifier: two reports pasted on one line),
* the text after an ``=`` (the report terminator, which stays on the report it ends),
* a blank line, and
* any other line, unless it continues the report before it. After a line of only keywords and modifiers
  (``TAF AMD``, the NWS bulletin form) the next line is the body. A ``TAF`` continues on any line that does not begin
  with a keyword or a station and issue time (``KSEA 131453Z``), since a TAF wraps anywhere. Another report
  continues on an indented line, or one that begins with ``FM``, ``BECMG``, ``TEMPO``, ``INTER``, ``PROBnn``,
  ``TX``/``TN``, ``RMK`` or ``NOSIG``.

So a METAR per line, a TAF over several lines, reports separated by blank lines or ``=`` all work, with CRLF or LF
line ends and in any case. Reports keep their original line breaks and indentation, so token offsets index what was
pasted, and every non-blank character of the input lands in exactly one report.

``detect_kind`` decides what a report is: an explicit keyword wins; without one, a ``DDHH/DDHH`` period, an
``FMDDHHMM`` or ``PROBnn`` group, or a ``BECMG``/``TEMPO`` with no temperature/dew-point group says TAF; anything else
is a METAR. Nothing here raises.
"""

from __future__ import annotations

import itertools
import re
from datetime import datetime
from enum import Enum

from wxbrief.decode.metar import parse_metar
from wxbrief.decode.model import Metar, Taf
from wxbrief.decode.taf import parse_taf

_WORD = re.compile(r"\S+")
_KEYWORDS = frozenset({"METAR", "SPECI", "TAF"})
_MODIFIERS = frozenset({"AMD", "COR", "CNL", "NIL", "RTD", "AUTO", "CCA", "CCB", "CCC"})
_STATION = re.compile(r"^[A-Z][A-Z0-9]{3}$")
_CONTINUATION = re.compile(r"^(?:FM\d|BECMG|TEMPO|INTER|PROB\d|T[XN]M?\d|RMK|NOSIG)", re.IGNORECASE)
_ISSUE_TIME = re.compile(r"^\d{6}Z$")
_VALID_PERIOD = re.compile(r"^\d{4}/\d{4}$")
_TAF_GROUP = re.compile(r"^(?:FM\d{6}|PROB[1-9]0)$")
_TEMPERATURE_DEW_POINT = re.compile(r"^(?:M?\d{2}|//)/(?:M?\d{2}|//)$")


class Kind(Enum):
    METAR = "METAR"
    TAF = "TAF"


def _first_word(line: str) -> str:
    match = _WORD.search(line)
    return match.group().upper() if match is not None else ""


def _split_keywords(line: str) -> list[str]:
    """Cut a line in front of a keyword that starts a second report on it (``... A3001 TAF KDEN 1312/...``)."""
    words = list(_WORD.finditer(line))
    cuts: list[int] = []
    for position, word in enumerate(words[1:], start=1):
        if word.group().upper() not in _KEYWORDS:
            continue
        previous = words[position - 1].group().upper()
        following = words[position + 1].group().upper() if position + 1 < len(words) else ""
        starts_report = _STATION.match(following) is not None or following in _MODIFIERS
        if previous not in _KEYWORDS and starts_report:
            cuts.append(word.start())
    if not cuts:
        return [line]
    bounds = [0, *cuts, len(line)]
    return [line[a:b] for a, b in itertools.pairwise(bounds)]


def _starts_report(piece: str) -> bool:
    """A keyword, or a station followed by an issue time (``KSEA 131453Z``): what a new report begins with."""
    words = _WORD.findall(piece.upper())
    if not words:
        return False
    if words[0] in _KEYWORDS:
        return True
    return len(words) > 1 and _STATION.match(words[0]) is not None and _ISSUE_TIME.match(words[1]) is not None


def _header_only(lines: list[str]) -> bool:
    """Whether a report so far is only keywords and modifiers (``TAF AMD``): its body is on the next line."""
    words = [word.upper() for line in lines for word in _WORD.findall(line)]
    return all(word in _KEYWORDS or word in _MODIFIERS for word in words)


def _split_chunk(chunk: str) -> list[str]:
    """Split text that holds no ``=`` (apart from a final one) into reports."""
    reports: list[list[str]] = []
    current: list[str] | None = None
    for line in chunk.split("\n"):
        for piece in _split_keywords(line):
            if not piece.strip():
                current = None
                continue
            word = _first_word(piece)
            indented = piece[:1].isspace()
            if current is None:
                continues = False
            elif _header_only(current):
                continues = word not in _KEYWORDS
            elif _first_word(current[0]) == "TAF":
                continues = not _starts_report(piece)  # a TAF wraps anywhere, not only before a change group
            else:
                continues = word not in _KEYWORDS and (indented or _CONTINUATION.match(word) is not None)
            if continues and current is not None:
                current.append(piece)
            else:
                current = [piece]
                reports.append(current)
    return ["\n".join(lines).strip() for lines in reports if "".join(lines).strip()]


def split_reports(text: str) -> list[str]:
    """Split pasted text into one string per report; never raises."""
    try:
        normalised = text.replace("\r\n", "\n").replace("\r", "\n")
        reports: list[str] = []
        for chunk in re.split(r"(?<==)", normalised):
            reports.extend(_split_chunk(chunk))
        return reports
    except Exception:
        return [text.strip()] if text.strip() else []


def detect_kind(report: str) -> Kind:
    """Whether ``report`` is a TAF or a METAR/SPECI (the fallback)."""
    words = [word.group().upper().rstrip("=") for word in _WORD.finditer(report)]
    if not words:
        return Kind.METAR
    if words[0] == "TAF":
        return Kind.TAF
    if words[0] in ("METAR", "SPECI"):
        return Kind.METAR
    if any(_VALID_PERIOD.match(word) or _TAF_GROUP.match(word) for word in words):
        return Kind.TAF
    has_trend = any(word in ("BECMG", "TEMPO", "INTER") for word in words)
    if has_trend and not any(_TEMPERATURE_DEW_POINT.match(word) for word in words):
        return Kind.TAF
    return Kind.METAR


def parse_any(text: str, reference: datetime | None = None) -> list[Metar | Taf]:
    """Split ``text`` into reports and decode each as a ``Taf`` or a ``Metar``; never raises."""
    decoded: list[Metar | Taf] = []
    for report in split_reports(text):
        if detect_kind(report) is Kind.TAF:
            decoded.append(parse_taf(report, reference))
        else:
            decoded.append(parse_metar(report, reference))
    return decoded
