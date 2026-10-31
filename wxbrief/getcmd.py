"""The ``wxbrief get`` subcommand: fetch the latest reports once and print them, no TUI."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime

from wxbrief.data.awc import AwcClient, AwcError
from wxbrief.data.models import AwcMetar, AwcTaf, latest_by_station
from wxbrief.data.stations import bundled, resolve_id
from wxbrief.decode.metar import parse_metar
from wxbrief.decode.model import Metar, Taf
from wxbrief.decode.taf import parse_taf
from wxbrief.decode.units import UnitsMode
from wxbrief.i18n import DEFAULT_LANGUAGE, Translator
from wxbrief.i18n.keys import K
from wxbrief.render.discord import render_discord
from wxbrief.render.jsonout import to_dict
from wxbrief.render.plain import render_plain
from wxbrief.solar import is_daylight


def add_get_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser], t: Translator) -> None:
    get = commands.add_parser("get", help=t.t(K.CLI_HELP_GET), description=t.t(K.CLI_HELP_GET_DESCRIPTION))
    get.add_argument("stations", nargs="+", metavar="ICAO", help=t.t(K.CLI_HELP_GET_STATIONS))
    output = get.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true", help=t.t(K.CLI_HELP_GET_JSON))
    output.add_argument("--discord", action="store_true", help=t.t(K.CLI_HELP_GET_DISCORD))
    output.add_argument("--plain", action="store_true", help=t.t(K.CLI_HELP_GET_PLAIN))
    get.add_argument("--units", choices=[mode.value for mode in UnitsMode], help=t.t(K.CLI_HELP_UNITS_MODE))


def resolve_ids(codes: list[str]) -> list[str]:
    ids: list[str] = []
    for code in codes:
        resolved = resolve_id(code)
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
    # Always UTF-8, as `decode` does: never fail on a character the stream cannot encode.
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="replace")

    ids = resolve_ids(args.stations)
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
    translator = Translator.load(getattr(args, "lang", None) or DEFAULT_LANGUAGE)
    db = bundled()
    blocks: list[str] = []
    for icao in ids:
        station = db.get(icao)
        name = station.name if station else None
        parts: list[str] = []
        if icao in decoded_metars:
            daylight = is_daylight(station.lat, station.lon, metars[icao].observed) if station else None
            if args.discord:
                parts.append(
                    render_discord(decoded_metars[icao], translator, units, station_name=name, daylight=daylight)
                )
            else:
                parts.append(render_plain(decoded_metars[icao], translator, units))
        else:
            parts.append(translator.t(K.CLI_NO_METAR, icao=icao))
        if icao in decoded_tafs:
            if args.discord:
                parts.append(render_discord(decoded_tafs[icao], translator, units, station_name=name))
            else:
                parts.append(render_plain(decoded_tafs[icao], translator, units))
        blocks.append("\n\n".join(parts))
    sys.stdout.write("\n\n".join(blocks) + "\n")
    return status
