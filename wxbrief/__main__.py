"""Command-line entry point: ``python -m wxbrief`` or the ``wxbrief`` script."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

from wxbrief import __version__
from wxbrief.config import LAYOUTS, TIME_MODES, Config, LoadedConfig, clean_watchlist, load_config
from wxbrief.decode.model import Metar, Taf
from wxbrief.decode.split import parse_any
from wxbrief.decode.units import UnitsMode
from wxbrief.getcmd import add_get_parser, resolve_ids, run_get
from wxbrief.i18n import Translator
from wxbrief.render.discord import render_discord
from wxbrief.render.jsonout import to_dict
from wxbrief.render.plain import render_plain
from wxbrief.ui.glyphs import GLYPH_SETS

if TYPE_CHECKING:
    from wxbrief.app import AppOptions


def _parse_date(value: str) -> datetime:
    """``YYYY-MM-DD`` as noon UTC, the moment day-of-month timestamps are resolved against."""
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {value!r}") from exc
    return parsed.replace(hour=12, tzinfo=UTC)


COMMANDS = ("decode", "get")
_GLOBAL_WITH_VALUE = frozenset({"--glyphs", "--layout", "--units", "--time", "--lang", "--config"})


def _add_global_flags(parser: argparse.ArgumentParser) -> None:
    """The flags that apply to the TUI (and are accepted before a subcommand)."""
    parser.add_argument("--version", action="version", version=f"wxbrief {__version__}")
    parser.add_argument("--glyphs", choices=GLYPH_SETS, help="glyph set (default: from config, nerd)")
    parser.add_argument("--layout", choices=LAYOUTS, help="list or grid layout (v toggles it)")
    parser.add_argument("--units", dest="tui_units", choices=[m.value for m in UnitsMode], help="units mode")
    parser.add_argument("--time", choices=TIME_MODES, help="time shown: station, local or zulu")
    parser.add_argument("--lang", help="language of the plain-language decode (en)")
    parser.add_argument("--config", type=Path, metavar="FILE", help="read and save this config file")
    parser.add_argument("--no-config", action="store_true", help="ignore the config file and never write it")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="open with the bundled sample reports of ten stations: fully offline, nothing is fetched, cached or saved",
    )


def _first_positional(argv: Sequence[str]) -> str | None:
    """The first word that is not a flag or a flag's value."""
    skip = False
    for word in argv:
        if skip:
            skip = False
        elif word in _GLOBAL_WITH_VALUE:
            skip = True
        elif not word.startswith("-"):
            return word
    return None


def build_tui_parser() -> argparse.ArgumentParser:
    """The parser for ``wxbrief [ICAO ...]``, which opens the TUI."""
    parser = argparse.ArgumentParser(
        prog="wxbrief",
        description="Terminal METAR/TAF briefing with colorways and plain-language translation. "
        "Give station ids to watch them for this run; saved stations load from the config.",
        epilog="commands: decode (decode text without the TUI), get (fetch once and print). "
        "Run 'wxbrief decode --help' or 'wxbrief get --help'.",
    )
    _add_global_flags(parser)
    parser.add_argument("stations", nargs="*", metavar="ICAO", help="station ids to add for this run")
    return parser


def build_parser() -> argparse.ArgumentParser:
    """Return the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="wxbrief",
        description="Terminal METAR/TAF briefing with colorways and plain-language translation.",
    )
    _add_global_flags(parser)
    commands = parser.add_subparsers(dest="command", metavar="command")

    decode = commands.add_parser(
        "decode",
        help="decode METAR, SPECI and TAF text given as arguments or on stdin",
        description=(
            "Decode METAR, SPECI and TAF reports into plain language. Pass each report as one quoted argument "
            "(unquoted words are joined into a single report), or pipe text on stdin: a blob with several reports, "
            "TAFs wrapped over several lines, reports separated by blank lines or '=', in upper or lower case. "
            "A group such as -RA is read as an option unless the report is quoted or follows --."
        ),
    )
    decode.add_argument("reports", nargs="*", metavar="RAW", help="raw report text")
    output = decode.add_mutually_exclusive_group()
    output.add_argument(
        "--plain",
        action="store_true",
        help="plain text without colour (automatic when stdout is not a terminal)",
    )
    output.add_argument(
        "--json",
        action="store_true",
        help="print the decoded reports as a JSON list (language-neutral: codes, numbers, UTC times)",
    )
    output.add_argument(
        "--discord",
        action="store_true",
        help="print each report as a Discord code block (inside an outer four-backtick fence); imperial units "
        "unless --units says otherwise",
    )
    decode.add_argument(
        "--units",
        choices=[mode.value for mode in UnitsMode],
        default=None,
        help="us or metric units first, or mixed: as reported with the other system in parentheses "
        "(default: mixed, or us with --discord)",
    )
    decode.add_argument(
        "--date",
        type=_parse_date,
        metavar="YYYY-MM-DD",
        help="date used to resolve the day of the month in the report's timestamp (default: now, UTC)",
    )
    decode.add_argument(
        "--theme",
        metavar="NAME",
        default=None,
        help="colourway for the coloured terminal output, such as paper-chart (default: the built-in palette)",
    )
    add_get_parser(commands)
    return parser


def _collect_texts(arguments: Sequence[str], stdin: TextIO) -> list[str]:
    """The pieces of text to decode: one per quoted argument (bare words are one), or all of stdin."""
    if arguments:
        if len(arguments) > 1 and not any(any(ch.isspace() for ch in arg) for arg in arguments):
            return [" ".join(arguments)]
        return [arg for arg in arguments if arg.strip()]
    if stdin.isatty():
        return []
    text = stdin.read()
    return [text] if text.strip() else []


def _run_decode(args: argparse.Namespace) -> int:
    palette = None
    if args.theme:
        from textual.color import ColorParseError

        from wxbrief.render.palette import Palette, all_themes

        themes = all_themes()
        if args.theme not in themes:
            names = ", ".join(sorted(themes))
            sys.stderr.write(f"wxbrief decode: unknown theme {args.theme!r} (choose from: {names})\n")
            return 2
        try:
            palette = Palette.from_theme(themes[args.theme])
        except (ColorParseError, KeyError, ValueError) as exc:
            sys.stderr.write(f"wxbrief decode: cannot build theme {args.theme!r}: {exc}\n")
            return 2
    texts = _collect_texts(args.reports, sys.stdin)
    reference = args.date if args.date is not None else datetime.now(UTC)
    decoded: list[Metar | Taf] = [item for text in texts for item in parse_any(text, reference)]
    if not decoded:
        sys.stderr.write("wxbrief decode: no report text given (pass it as an argument or on stdin)\n")
        return 2

    # Always UTF-8: a pipe on Windows defaults to the ANSI code page, which turns the degree sign into a lone 0xB0 byte.
    # Never fail on a character the stream cannot encode.
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="replace")

    if args.json:
        sys.stdout.write(json.dumps([to_dict(item) for item in decoded], indent=2) + "\n")
        return 0

    units = UnitsMode(args.units or (UnitsMode.US.value if args.discord else UnitsMode.MIXED.value))
    translator = Translator.load("en")
    if args.discord:
        sys.stdout.write("\n\n".join(render_discord(item, translator, units) for item in decoded) + "\n")
        return 0

    if args.plain or not sys.stdout.isatty():
        sys.stdout.write("\n\n".join(render_plain(item, translator, units) for item in decoded) + "\n")
        return 0

    from rich.console import Console
    from rich.text import Text

    from wxbrief.render.richtext import DEFAULT_THEME, build_renderable

    rich_theme = palette.rich_theme if palette else DEFAULT_THEME
    console = Console(theme=rich_theme)
    for index, item in enumerate(decoded):
        if index:
            console.print(Text(""))
        console.print(build_renderable(item, translator, units))
    return 0


def _run_tui(args: argparse.Namespace) -> int:
    """Open the TUI. Without a terminal there is nothing to draw on, so print the help instead."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        sys.stdout.write(build_tui_parser().format_help())
        return 0
    from wxbrief.app import WxBriefApp

    options = tui_options(args)
    app = WxBriefApp(options)
    app.run()
    return app.return_code or 0


def tui_options(args: argparse.Namespace) -> AppOptions:
    """Build the app options from the parsed flags: config first, then each flag overrides it for this run only."""
    from wxbrief.app import AppOptions

    loaded = LoadedConfig(Config()) if args.no_config else load_config(args.config)
    demo = bool(args.demo)
    view = replace(loaded.config.view)
    for name, value in (
        ("glyph_set", args.glyphs),
        ("layout", args.layout),
        ("units", args.tui_units),
        ("time", args.time),
        ("lang", args.lang),
    ):
        if value:
            setattr(view, name, value)
    notices: list[str] = []
    cleaned = clean_watchlist([s.strip().upper() for s in args.stations], notices)
    if demo:
        # The sample stations replace the list; the config is read for the view settings only and never written.
        from wxbrief.data.demo import DEMO_NOW, demo_ids

        return AppOptions(
            ids=demo_ids(),
            config=Config(),
            view=view,
            use_config=False,
            config_warnings=[],
            use_cache=False,
            poll=False,
            demo=True,
            now=lambda: DEMO_NOW,
        )
    return AppOptions(
        ids=resolve_ids(cleaned),
        notices=notices,
        config_usable=loaded.usable,
        config=loaded.config,
        view=view,
        config_path=args.config,
        use_config=not args.no_config,
        config_warnings=loaded.warnings,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line and return the process exit code."""
    words = list(sys.argv[1:] if argv is None else argv)
    if _first_positional(words) not in COMMANDS:
        tui_args = build_tui_parser().parse_args(words)
        return _run_tui(tui_args)
    args = build_parser().parse_args(words)
    if args.command == "decode":
        return _run_decode(args)
    return run_get(args)


if __name__ == "__main__":
    sys.exit(main())
