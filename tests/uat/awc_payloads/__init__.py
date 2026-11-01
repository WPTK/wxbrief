"""Recorded AWC feeds re-stamped to "now", so a live-mode journey starts with FRESH data.

The recorded batches in ``tests/fixtures/awc`` are a day old: served as they are, the status bar says ``stale`` and the
detail pane "METAR is 1874 min old". ``fresh_payloads`` keeps the newest METAR and the newest TAF of each station,
moves every time in them (epoch fields, ISO fields, and the DDHHMMZ / DDHH/DDHH / FMDDHHMM groups inside the raw text)
so the METAR was observed ``metar_age`` minutes ago and the TAF issued about an hour ago, and returns the dict a
``FaultProxy`` takes. Nothing else is changed: the reports stay the real ones.
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "awc"
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
_EPOCH_KEYS = {"obsTime", "validTimeFrom", "validTimeTo", "timeFrom", "timeTo", "timeBec"}


def _rows(pattern: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in sorted(FIXTURES.glob(pattern)):
        out.extend(json.loads(path.read_text(encoding="utf-8")))
    return out


def recorded() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Newest recorded METAR and newest recorded TAF per station, from every batch of the 2026-10-31 recording."""
    metars: dict[str, dict[str, Any]] = {}
    for row in _rows("metar_*_20261031.json"):
        old = metars.get(row["icaoId"])
        if old is None or row["obsTime"] > old["obsTime"]:
            metars[row["icaoId"]] = row
    tafs: dict[str, dict[str, Any]] = {}
    for row in _rows("taf_*_20261031.json"):
        old = tafs.get(row["icaoId"])
        if old is None or row["validTimeFrom"] > old["validTimeFrom"]:
            tafs[row["icaoId"]] = row
    return metars, tafs


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _shift_value(key: str, value: Any, delta: int) -> Any:
    if key in _EPOCH_KEYS and isinstance(value, int):
        return value + delta
    if isinstance(value, str) and _ISO.match(value):
        return _iso(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() + delta)
    return value


def _shift_tree(node: Any, delta: int) -> Any:
    if isinstance(node, dict):
        return {k: _shift_tree(_shift_value(k, v, delta), delta) for k, v in node.items()}
    if isinstance(node, list):
        return [_shift_tree(v, delta) for v in node]
    return node


def _month_add(ref: datetime, day: int, hour: int, minute: int) -> datetime:
    """The datetime a DD/HH/MM group means, as seen from ``ref`` (the first month that is not before ref - 12 h)."""
    year, month = ref.year, ref.month
    for _ in range(3):
        try:
            cand = datetime(year, month, day, hour, minute, tzinfo=UTC)
        except ValueError:
            cand = None
        if cand is not None and cand >= ref - timedelta(hours=12):
            return cand
        month += 1
        if month == 13:
            year, month = year + 1, 1
    raise ValueError(f"cannot place day {day} near {ref}")


def _shift_raw(raw: str, ref: datetime, delta: int) -> str:
    """Rewrite the time groups of a METAR/TAF so they read ``delta`` seconds later."""

    def dhm(m: re.Match[str]) -> str:  # 310756Z, FM311500, FM3115 (no: FM is always DDHHMM)
        d, h, mi = int(m["d"]), int(m["h"]), int(m["m"])
        when = _month_add(ref, d, h, mi) + timedelta(seconds=delta)
        return f"{m['pre']}{when.day:02d}{when.hour:02d}{when.minute:02d}{m['post']}"

    def dh_range(m: re.Match[str]) -> str:  # 3109/0112 (hour 24 means the end of the day)
        out = []
        for d, h in ((m["d1"], m["h1"]), (m["d2"], m["h2"])):
            h_i = int(h)
            base = _month_add(ref, int(d), 0 if h_i == 24 else h_i, 0) + (timedelta(days=1) if h_i == 24 else timedelta())
            when = base + timedelta(seconds=delta)
            out.append(f"{when.day:02d}{when.hour:02d}")
        return f"{m['pre']}{out[0]}/{out[1]}"

    raw = re.sub(r"(?P<pre>\bFM)(?P<d>\d{2})(?P<h>\d{2})(?P<m>\d{2})(?P<post>\b)", dhm, raw)
    raw = re.sub(r"(?P<pre>\b)(?P<d>\d{2})(?P<h>\d{2})(?P<m>\d{2})(?P<post>Z\b)", dhm, raw)
    raw = re.sub(r"(?P<pre>\b)(?P<d1>\d{2})(?P<h1>\d{2})/(?P<d2>\d{2})(?P<h2>\d{2})\b", dh_range, raw)
    return raw


def restamp_metar(row: dict[str, Any], now: datetime, age_minutes: int) -> dict[str, Any]:
    """The same METAR, observed ``age_minutes`` before ``now`` (to the minute)."""
    target = now.replace(second=0, microsecond=0) - timedelta(minutes=age_minutes)
    delta = int(target.timestamp()) - int(row["obsTime"])
    ref = datetime.fromtimestamp(row["obsTime"], UTC)
    out = _shift_tree(copy.deepcopy(row), delta)
    out["rawOb"] = _shift_raw(row["rawOb"], ref, delta)
    return out


def restamp_taf(row: dict[str, Any], now: datetime, age_minutes: int = 60) -> dict[str, Any]:
    """The same TAF, issued about ``age_minutes`` before ``now``; shifted by whole hours so the validity text stays real."""
    issue = datetime.fromisoformat(row["issueTime"].replace("Z", "+00:00"))
    hours = round((now - timedelta(minutes=age_minutes) - issue).total_seconds() / 3600)
    delta = hours * 3600
    out = _shift_tree(copy.deepcopy(row), delta)
    out["rawTAF"] = _shift_raw(row["rawTAF"], issue, delta)
    return out


def fresh_payloads(
    stations: Iterable[str], *, now: datetime | None = None, metar_age: int = 12, taf_age: int = 60, no_taf: Iterable[str] = ()
) -> dict[str, Any]:
    """``{"metar": [...], "taf": [...], "stationinfo": [...]}`` for ``FaultProxy`` with fresh times.

    A station in ``no_taf`` gets a METAR only (the forecast section then has nothing to show)."""
    now = now or datetime.now(UTC)
    metars, tafs = recorded()
    skip = set(no_taf)
    out_m: list[dict[str, Any]] = []
    out_t: list[dict[str, Any]] = []
    info: list[dict[str, Any]] = []
    for icao in stations:
        m = metars[icao]
        out_m.append(restamp_metar(m, now, metar_age))
        if icao in tafs and icao not in skip:
            out_t.append(restamp_taf(tafs[icao], now, taf_age))
        info.append(
            {
                "icaoId": icao,
                "lat": m.get("lat"),
                "lon": m.get("lon"),
                "elev": m.get("elev"),
                "site": m.get("name"),
                "state": "",
                "country": (m.get("name") or "").rsplit(", ", 1)[-1],
            }
        )
    return {"metar": out_m, "taf": out_t, "stationinfo": info}


def shortest_with_both(count: int, prefix: str = "K") -> list[str]:
    """The ``count`` stations whose recorded METAR and TAF together are shortest: their three sections fit on one screen."""
    metars, tafs = recorded()
    both = [(len(metars[i]["rawOb"]) + len(tafs[i]["rawTAF"]), i) for i in metars if i in tafs and i.startswith(prefix)]
    return [i for _, i in sorted(both)[:count]]
