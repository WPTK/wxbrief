"""Command-line entry point: ``python -m wxbrief`` or the ``wxbrief`` script."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TextIO

from wxbrief import __version__
from wxbrief.decode.metar import parse_metar
from wxbrief.decode.units import UnitsMode
from wxbrief.i18n import Translator
from wxbrief.render.plain import render_plain


def _parse_date(value: str) -> datetime:
    """``YYYY-MM-DD`` as noon UTC, the moment day-of-month timestamps are resolved against."""
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {value!r}") from exc
    return parsed.replace(hour=12, tzinfo=UTC)


def build_parser() -> argparse.ArgumentParser:
    """Return the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="wxbrief",
        description="Terminal METAR/TAF briefing with colorways and plain-language translation.",
    )
    parser.add_argument("--version", action="version", version=f"wxbrief {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="command")

    decode = commands.add_parser(
        "decode",
        help="decode METAR/SPECI text given as arguments or on stdin",
        description=(
            "Decode METAR or SPECI reports into plain language. Pass each report as one quoted argument (unquoted "
            "words are joined into a single report), or pipe text on stdin with one report per line. A group such "
            "as -RA is read as an option unless the report is quoted or follows --."
        ),
    )
    decode.add_argument("reports", nargs="*", metavar="RAW", help="raw report text")
    decode.add_argument(
        "--plain",
        action="store_true",
        help="plain text without colour (automatic when stdout is not a terminal)",
    )
    decode.add_argument(
        "--units",
        choices=[mode.value for mode in UnitsMode],
        default=UnitsMode.MIXED.value,
        help="us or metric units first, or mixed: as reported with the other system in parentheses (default)",
    )
    decode.add_argument(
        "--date",
        type=_parse_date,
        metavar="YYYY-MM-DD",
        help="date used to resolve the day of the month in the report's timestamp (default: now, UTC)",
    )
    return parser


def _collect_reports(arguments: Sequence[str], stdin: TextIO) -> list[str]:
    """One report per quoted argument; bare words are one report; otherwise one report per stdin line."""
    if arguments:
        if len(arguments) > 1 and not any(any(ch.isspace() for ch in arg) for arg in arguments):
            return [" ".join(arguments)]
        return [arg for arg in arguments if arg.strip()]
    if stdin.isatty():
        return []
    return [line for line in stdin.read().splitlines() if line.strip()]


def _run_decode(args: argparse.Namespace) -> int:
    reports = _collect_reports(args.reports, sys.stdin)
    if not reports:
        sys.stderr.write("wxbrief decode: no report text given (pass it as an argument or on stdin)\n")
        return 2

    # Never fail on a character the console cannot encode (the degree sign in a legacy code page, say).
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(errors="replace")

    units = UnitsMode(args.units)
    reference = args.date if args.date is not None else datetime.now(UTC)
    translator = Translator.load("en")
    decoded = [parse_metar(raw, reference) for raw in reports]
    plain = args.plain or not sys.stdout.isatty()

    if plain:
        sys.stdout.write("\n\n".join(render_plain(metar, translator, units) for metar in decoded) + "\n")
        return 0

    from rich.console import Console
    from rich.text import Text

    from wxbrief.render.richtext import DEFAULT_THEME, build_renderable

    console = Console(theme=DEFAULT_THEME)
    for index, metar in enumerate(decoded):
        if index:
            console.print(Text(""))
        console.print(build_renderable(metar, translator, units))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line and return the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "decode":
        return _run_decode(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
