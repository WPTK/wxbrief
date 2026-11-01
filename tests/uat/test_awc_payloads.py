"""The re-stamped AWC payloads and the status-bar rule engine: pure functions, no program, no network (runs in CI)."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import pytest
from awc_payloads import fresh_payloads, recorded
from status_rules import broken_rules

NOW = datetime(2026, 11, 1, 19, 27, 13, tzinfo=UTC)


def test_every_station_with_both_products_restamps_consistently() -> None:
    metars, tafs = recorded()
    both = sorted(set(metars) & set(tafs))
    assert len(both) >= 40
    payload = fresh_payloads(both, now=NOW, metar_age=12, taf_age=60)
    for row in payload["metar"]:
        obs = datetime.fromtimestamp(row["obsTime"], UTC)
        assert obs == datetime(2026, 11, 1, 19, 15, tzinfo=UTC)
        assert re.search(rf"\b{obs:%d%H%M}Z\b", row["rawOb"]), row["rawOb"]
    for row in payload["taf"]:
        issue = datetime.fromisoformat(row["issueTime"].replace("Z", "+00:00"))
        assert abs(NOW - issue - timedelta(hours=1)) <= timedelta(minutes=31), (row["icaoId"], issue)
        assert f"{issue:%d%H%M}Z" in row["rawTAF"], row["rawTAF"]
        start = datetime.fromtimestamp(row["validTimeFrom"], UTC)
        end = datetime.fromtimestamp(row["validTimeTo"], UTC)
        assert re.search(rf"\b{start:%d%H}/{end:%d%H}\b", row["rawTAF"]), (row["rawTAF"], start, end)
        assert end >= NOW  # still valid (some recorded TAFs start hours after they are issued)


def test_fm_groups_follow_the_epoch_fields() -> None:
    _, tafs = recorded()
    icao = next(i for i, r in sorted(tafs.items()) if " FM" in r["rawTAF"])
    row = fresh_payloads([icao], now=NOW)["taf"][0] if icao in recorded()[0] else None
    if row is None:
        pytest.skip("no METAR for the chosen TAF station")
    froms = [datetime.fromtimestamp(f["timeFrom"], UTC) for f in row["fcsts"] if f["fcstChange"] == "FM"]
    tokens = re.findall(r"\bFM(\d{6})\b", row["rawTAF"])
    assert [f"{t:%d%H%M}" for t in froms] == tokens


@pytest.mark.parametrize(
    ("bar", "broken"),
    [
        ("1/3  fresh | next poll 9:51 | req 2/100", False),
        ("1/3  offline, showing saved data from 4 min ago | next poll 1:00 | req 9/100", False),
        ("1/3  offline  fresh | next poll 10:00 | req 4/100", True),
        ("1/3  fresh stale | req 1/100", True),
        ("1/3  offline | req 1/100", True),
    ],
)
def test_rule_engine(bar: str, broken: bool) -> None:
    assert bool(broken_rules(bar)) is broken
