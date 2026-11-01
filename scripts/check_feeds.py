"""Fetch each live feed wxbrief depends on, once, and run it through the app's own client and parsers.

Used by ``feed-check.yml``. Needs wxbrief installed (``pip install .``). One request per endpoint, three in all, with
the app's User-Agent. Exit codes keep two failures apart:

* 0: every feed answered and parsed.
* 1: a format change. The feed answered but is no longer what the parsers expect (not JSON, not a list, rows the
  parsers drop, or a report the decoder fails on). The workflow raises an issue at once.
* 2: unavailable. Timeout, connection error, 429, 5xx, or an empty answer for stations that always report. This says
  nothing about the format, so the workflow raises an issue only after repeated failure.

Writes nothing.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable
from typing import Any

from wxbrief.data import awc
from wxbrief.data.models import parse_metars, parse_stations, parse_tafs
from wxbrief.decode.metar import WARN_PARSER_ERROR, parse_metar
from wxbrief.decode.taf import parse_taf

# Large airports that always issue a METAR and a TAF.
IDS = ["KJFK", "KDEN", "KORD", "EGLL", "RJTT"]
OK, FORMAT, DOWN = 0, 1, 2
EMPTY = "empty answer"


async def _rows(client: awc.AwcClient, endpoint: str, extra: dict[str, str]) -> list[Any]:
    """The raw JSON rows of one endpoint, one request."""
    return await client._get(endpoint, {"ids": ",".join(IDS), "format": "json", **extra})


def _dropped(name: str, raw: list[Any], parsed: list[Any]) -> list[str]:
    if len(parsed) < len(raw):
        return [f"{name}: parsers kept {len(parsed)} of {len(raw)} rows (a field the app reads is missing or renamed)"]
    return []


async def check_metar(client: awc.AwcClient) -> list[str]:
    raw = await _rows(client, "metar", {"hours": "2"})
    parsed = parse_metars(raw)
    print(f"metar: {len(raw)} rows, {len(parsed)} parsed")
    problems = _dropped("metar", raw, parsed)
    for report in parsed:
        if any(w.code == WARN_PARSER_ERROR for w in parse_metar(report.raw).warnings):
            problems.append(f"metar {report.icao}: the decoder failed on {report.raw!r}")
    return problems or ([] if raw else [f"metar: {EMPTY}"])


async def check_taf(client: awc.AwcClient) -> list[str]:
    raw = await _rows(client, "taf", {})
    parsed = parse_tafs(raw)
    print(f"taf: {len(raw)} rows, {len(parsed)} parsed")
    problems = _dropped("taf", raw, parsed)
    for report in parsed:
        if any(w.code == WARN_PARSER_ERROR for w in parse_taf(report.raw).warnings):
            problems.append(f"taf {report.icao}: the decoder failed on {report.raw!r}")
    return problems or ([] if raw else [f"taf: {EMPTY}"])


async def check_stationinfo(client: awc.AwcClient) -> list[str]:
    raw = await _rows(client, "stationinfo", {})
    parsed = parse_stations(raw)
    print(f"stationinfo: {len(raw)} rows, {len(parsed)} parsed")
    return _dropped("stationinfo", raw, parsed) or ([] if raw else [f"stationinfo: {EMPTY}"])


CHECKS: list[Callable[[awc.AwcClient], Awaitable[list[str]]]] = [check_metar, check_taf, check_stationinfo]


async def run() -> int:
    changed: list[str] = []
    down: list[str] = []
    async with awc.AwcClient() as client:
        for check in CHECKS:
            name = check.__name__.removeprefix("check_")
            try:
                found = await check(client)
            except (awc.RateLimited, awc.ServerError, awc.TransportError) as error:
                down.append(f"{name}: unavailable ({error})")
            except awc.ClientError as error:  # a 4xx, or a body that is not a JSON list: the endpoint changed
                changed.append(f"{name}: {error}")
            else:
                for problem in found:
                    (down if problem.endswith(EMPTY) else changed).append(problem)
    for line in changed:
        print(f"FORMAT: {line}")
    for line in down:
        print(f"DOWN: {line}")
    if changed:
        return FORMAT
    return DOWN if down else OK


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
