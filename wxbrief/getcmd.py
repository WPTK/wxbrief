"""The ``wxbrief get`` subcommand: fetch the latest reports once and print them, no TUI."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from wxbrief.data.awc import AwcClient, AwcError
from wxbrief.data.models import AwcMetar, AwcTaf, latest_by_station
from wxbrief.data.stations import bundled
from wxbrief.decode.metar import parse_metar
from wxbrief.decode.model import Metar, Taf
from wxbrief.decode.taf import parse_taf
from wxbrief.decode.units import UnitsMode
from wxbrief.i18n import Translator
from wxbrief.render.discord import render_discord
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
    output.add_argument(
        "--discord", action="store_true", help="Discord code blocks (imperial units unless --units says otherwise)"
    )
    output.add_argument("--plain", action="store_true", help="plain text")
    get.add_argument(
        "--units",
        choices=[mode.value for mode in UnitsMode],
        help="us or metric units first, or mixed: as reported with the other system in parentheses "
        "(default: mixed, or us with --discord)",
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


def _local_hour(tz: str | None, moment: datetime | None) -> int | None:
    """The hour of day at the station when the report was made, for the day/night glyph."""
    if tz is None or moment is None:
        return None
    try:
        return moment.astimezone(ZoneInfo(tz)).hour
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None


def run_get(args: argparse.Namespace) -> int:
    """Exit 0 when everything arrived, 3 when a product failed but some data arrived, 1 when no station got anything."""
    # Always UTF-8, as `decode` does: never fail on a character the stream cannot encode.
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="replace")

    ids = _resolve(args.stations)
    metars, tafs, errors = asyncio.run(_fetch(ids))
    for message in errors:
        sys.stderr.write(f"wxbrief get: {message}\n")
    status = 1 if not (metars or tafs) else 3 if errors else 0

    now = datetime.now(UTC)
    decoded_metars: dict[str, Metar] = {icao: parse_metar(m.raw, m.observed or now) for icao, m in metars.items()}
    decoded_tafs: dict[str, Taf] = {icao: parse_taf(t.raw, t.issued or now) for icao, t in tafs.items()}

    if args.json:
        document = {
            icao: {
                "metar": to_dict(decoded_metars[icao]) if icao in decoded_metars else None,
                "taf": to_dict(decoded_tafs[icao]) if icao in decoded_tafs else None,
            }
            for icao in ids
        }
        sys.stdout.write(json.dumps(document, indent=2, ensure_ascii=False) + "\n")
        return status

    units = UnitsMode(args.units or (UnitsMode.US.value if args.discord else UnitsMode.MIXED.value))
    translator = Translator.load("en")
    db = bundled()
    blocks: list[str] = []
    for icao in ids:
        station = db.get(icao)
        name = station.name if station else None
        parts: list[str] = []
        if icao in decoded_metars:
            hour = _local_hour(station.tz if station else None, metars[icao].observed)
            if args.discord:
                parts.append(
                    render_discord(decoded_metars[icao], translator, units, station_name=name, local_hour=hour)
                )
            else:
                parts.append(render_plain(decoded_metars[icao], translator, units))
        else:
            parts.append(f"{icao}: no METAR in the last 2 hours")
        if icao in decoded_tafs:
            if args.discord:
                parts.append(render_discord(decoded_tafs[icao], translator, units, station_name=name))
            else:
                parts.append(render_plain(decoded_tafs[icao], translator, units))
        blocks.append("\n\n".join(parts))
    sys.stdout.write("\n\n".join(blocks) + "\n")
    return status
