"""The ``wxbrief get`` subcommand: fetch the latest reports once and print them, no TUI."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime

from wxbrief.data.awc import AwcClient, AwcError
from wxbrief.data.models import AwcMetar, AwcTaf, latest_by_station
from wxbrief.data.stations import bundled
from wxbrief.decode.metar import parse_metar
from wxbrief.decode.units import UnitsMode
from wxbrief.i18n import Translator
from wxbrief.render.jsonout import to_dict
from wxbrief.render.plain import render_plain


def add_get_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    get = commands.add_parser(
        "get",
        help="fetch the latest METAR and TAF for stations and print them",
        description="Fetch the latest METAR/SPECI and TAF from aviationweather.gov once and print the decode.",
    )
    get.add_argument("stations", nargs="+", metavar="ICAO", help="station ids (ICAO, or a unique IATA/FAA code)")
    output = get.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true", help="machine-readable output")
    output.add_argument("--discord", action="store_true", help="Discord message block (needs the S2b renderer)")
    output.add_argument("--plain", action="store_true", help="plain text (the default for now)")
    get.add_argument(
        "--units",
        choices=[mode.value for mode in UnitsMode],
        default=UnitsMode.MIXED.value,
        help="us or metric units first, or mixed (default)",
    )


def _resolve(codes: list[str]) -> list[str]:
    db = bundled()
    ids: list[str] = []
    for code in codes:
        key = code.strip().upper()
        station = db.get(key) if len(key) == 3 else None
        resolved = station.icao if station else key
        if resolved and resolved not in ids:
            ids.append(resolved)
    return ids


async def _fetch(ids: list[str]) -> tuple[dict[str, AwcMetar], dict[str, AwcTaf], list[str]]:
    """Fetch each product on its own, so one failing does not hide what the other returned."""
    errors: list[str] = []
    metars: list[AwcMetar] = []
    tafs: list[AwcTaf] = []
    async with AwcClient() as client:
        try:
            metars = await client.metars(ids)
        except AwcError as exc:
            errors.append(f"METAR: {exc}")
        try:
            tafs = await client.tafs(ids)
        except AwcError as exc:
            errors.append(f"TAF: {exc}")
    return latest_by_station(metars), {taf.icao: taf for taf in tafs}, errors


def run_get(args: argparse.Namespace) -> int:
    """Exit 0 when everything arrived, 3 when a product failed but some data arrived, 1 when no station got anything."""
    # TODO(S2b): render --discord with the Discord renderer and decode TAFs once s2b-taf-output has merged.
    if args.discord:
        sys.stderr.write("wxbrief get: --discord arrives with the TAF and output work (S2b)\n")
        return 2
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(errors="replace")

    ids = _resolve(args.stations)
    metars, tafs, errors = asyncio.run(_fetch(ids))
    for message in errors:
        sys.stderr.write(f"wxbrief get: {message}\n")
    status = 1 if not (metars or tafs) else 3 if errors else 0

    now = datetime.now(UTC)
    translator = Translator.load("en")
    units = UnitsMode(args.units)
    decoded = {icao: parse_metar(m.raw, m.observed or now) for icao, m in metars.items()}

    if args.json:
        document = {
            icao: {
                "metar": to_dict(decoded[icao]) if icao in decoded else None,
                "taf_raw": tafs[icao].raw if icao in tafs else None,
            }
            for icao in ids
        }
        sys.stdout.write(json.dumps(document, indent=2, ensure_ascii=False) + "\n")
        return status

    blocks: list[str] = []
    for icao in ids:
        parts: list[str] = []
        if icao in decoded:
            parts.append(render_plain(decoded[icao], translator, units))
        else:
            parts.append(f"{icao}: no METAR in the last 2 hours")
        if icao in tafs:
            parts.append("TAF (raw):\n  " + tafs[icao].raw)  # TODO(S2b): decode
        blocks.append("\n".join(parts))
    sys.stdout.write("\n\n".join(blocks) + "\n")
    return status
