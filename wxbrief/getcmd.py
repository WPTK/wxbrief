"""The ``wxbrief get`` subcommand: fetch the latest reports once and print them, no TUI."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime

from wxbrief.config import station_id
from wxbrief.data.awc import AwcClient, AwcError
from wxbrief.data.models import AwcMetar, AwcTaf, latest_by_station
from wxbrief.data.poll import STALE_AFTER, Freshness, freshness
from wxbrief.data.stations import bundled
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


def resolve_ids(codes: list[str]) -> tuple[list[str], list[str]]:
    """The station ids to fetch (IATA and FAA codes resolved, no repeats) and the arguments that are not ids."""
    ids: list[str] = []
    rejected: list[str] = []
    for code in codes:
        resolved = station_id(code)  # the watchlist's rule: AWC would read ``KDEN,KSFO`` as two stations
        if resolved is None:
            rejected.append(code)
        elif resolved not in ids:
            ids.append(resolved)
    return ids, rejected


async def _fetch(ids: list[str]) -> tuple[dict[str, AwcMetar], dict[str, AwcTaf], dict[str, str]]:
    """Fetch each product on its own, so one failing does not hide what the other returned.

    The third item maps each product that failed (``METAR``, ``TAF``) to why.
    """
    errors: dict[str, str] = {}
    metars: list[AwcMetar] = []
    tafs: list[AwcTaf] = []
    try:
        client = AwcClient()
    except AwcError as exc:  # the HTTP client could not be built (a proxy or CA setting)
        return {}, {}, {"METAR": str(exc), "TAF": str(exc)}
    async with client:
        try:
            metars = await client.metars(ids)
        except AwcError as exc:
            errors["METAR"] = str(exc)
        try:
            tafs = await client.tafs(ids)
        except AwcError as exc:
            errors["TAF"] = str(exc)
    return latest_by_station(metars), {taf.icao: taf for taf in tafs}, errors


def run_get(args: argparse.Namespace) -> int:
    """Exit 0 when every station got a report, 3 when a product failed or a station got nothing but some data
    arrived, 2 for an argument that is not a station id, 1 when no station got anything."""
    ids, rejected = resolve_ids(args.stations)
    if rejected or not ids:
        shown = ", ".join(repr(code) for code in rejected)
        sys.stderr.write(
            f"wxbrief get: not a station id: {shown} (give 3 or 4 letters or digits, one id per argument)\n"
            if rejected
            else "wxbrief get: no station given\n"
        )
        return 2
    metars, tafs, errors = asyncio.run(_fetch(ids))
    for product, message in errors.items():
        sys.stderr.write(f"wxbrief get: {product}: {message}\n")
    empty = [icao for icao in ids if icao not in metars and icao not in tafs]
    if empty and not errors and args.json:  # the text output names each empty station itself; JSON has only nulls
        sys.stderr.write(f"wxbrief get: no report for {', '.join(empty)}\n")
    status = 1 if not (metars or tafs) else 3 if errors or empty else 0

    now = datetime.now(UTC)
    stale = {
        icao: now - m.observed
        for icao, m in metars.items()
        if m.observed is not None and freshness(m.observed, now) is Freshness.STALE
    }
    decoded_metars: dict[str, Metar] = {icao: parse_metar(m.raw, m.observed or now) for icao, m in metars.items()}
    decoded_tafs: dict[str, Taf] = {icao: parse_taf(t.raw, t.issued or now) for icao, t in tafs.items()}

    if args.json:
        document = {
            icao: {
                "metar": to_dict(decoded_metars[icao]) if icao in decoded_metars else None,
                "taf": to_dict(decoded_tafs[icao]) if icao in decoded_tafs else None,
                "stale": icao in stale,  # the METAR is older than the freshness limit
                "errors": [product.lower() for product in errors],  # a null above is a failed fetch for these
            }
            for icao in ids
        }
        sys.stdout.write(json.dumps(document, indent=2, ensure_ascii=False) + "\n")
        return status

    units = UnitsMode(args.units or args.tui_units or (UnitsMode.US.value if args.discord else UnitsMode.MIXED.value))
    translator = Translator.load(getattr(args, "lang", None) or DEFAULT_LANGUAGE)
    db = bundled()
    blocks: list[str] = []
    for icao in ids:
        station = db.get(icao)
        name = station.name if station else None
        parts: list[str] = []
        if icao in decoded_metars:
            if icao in stale:
                minutes = int(stale[icao].total_seconds() // 60)
                limit = int(STALE_AFTER.total_seconds() // 60)
                parts.append(translator.t(K.CLI_METAR_STALE, icao=icao, minutes=minutes, limit=limit))
            daylight = is_daylight(station.lat, station.lon, metars[icao].observed) if station else None
            if args.discord:
                parts.append(
                    render_discord(decoded_metars[icao], translator, units, station_name=name, daylight=daylight)
                )
            else:
                parts.append(render_plain(decoded_metars[icao], translator, units))
        elif "METAR" in errors:
            parts.append(translator.t(K.CLI_METAR_FAILED, icao=icao))
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
