"""Command-line entry point: ``python -m wxbrief`` or the ``wxbrief`` script."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
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
from wxbrief.decode.times import end_of_day
from wxbrief.decode.units import UnitsMode
from wxbrief.getcmd import add_get_parser, run_get
from wxbrief.i18n import DEFAULT_LANGUAGE, LANGUAGES, Translator, resolve_language
from wxbrief.i18n.keys import K
from wxbrief.render.discord import render_discord
from wxbrief.render.jsonout import to_dict
from wxbrief.render.plain import render_plain
from wxbrief.ui.glyphs import GLYPH_SETS

if TYPE_CHECKING:
    from wxbrief.app import AppOptions


def _parse_date(value: str) -> datetime:
    """``YYYY-MM-DD`` as the end of that day UTC, the moment day-of-month timestamps are resolved against."""
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {value!r}") from exc
    return end_of_day(parsed.date())


COMMANDS = ("decode", "get")
_GLOBAL_WITH_VALUE = frozenset({"--theme", "--glyphs", "--layout", "--units", "--time", "--lang", "--config"})


def _tui_theme(value: str) -> str:
    """A theme name the TUI can show: an aviation theme or a Textual built-in (not ``ansi-dark`` or ``ansi-light``)."""
    from wxbrief.render.palette import all_themes

    names = sorted(all_themes())
    if value not in names:
        raise argparse.ArgumentTypeError(f"unknown theme {value!r} (choose from: {', '.join(names)})")
    return value


def _language(value: str) -> str:
    """A language code that has a catalog (``de``, ``pt-BR`` -> ``pt``), as an argparse type."""
    found = resolve_language(value)
    if found is None:
        raise argparse.ArgumentTypeError(f"unknown language {value!r} (choose from: {', '.join(LANGUAGES)})")
    return found


def _help_translator(words: Sequence[str]) -> Translator:
    """The translator for the ``--help`` text: the language named by ``--lang`` on the command line, else English."""
    for index, word in enumerate(words):
        value = word.removeprefix("--lang=") if word.startswith("--lang=") else None
        if value is None and word == "--lang" and index + 1 < len(words):
            value = words[index + 1]
        if value is not None:
            return Translator.load(resolve_language(value) or DEFAULT_LANGUAGE)
    return Translator.load(DEFAULT_LANGUAGE)


def _add_global_flags(parser: argparse.ArgumentParser, t: Translator) -> None:
    """The flags that apply to the TUI (and are accepted before a subcommand)."""
    parser.add_argument("--version", action="version", version=f"wxbrief {__version__}")
    parser.add_argument("--theme", dest="tui_theme", type=_tui_theme, metavar="NAME", help=t.t(K.CLI_HELP_THEME))
    parser.add_argument("--glyphs", choices=GLYPH_SETS, help=t.t(K.CLI_HELP_GLYPHS))
    parser.add_argument("--layout", choices=LAYOUTS, help=t.t(K.CLI_HELP_LAYOUT))
    parser.add_argument(
        "--units", dest="tui_units", choices=[m.value for m in UnitsMode], help=t.t(K.CLI_HELP_UNITS)
    )
    parser.add_argument("--time", choices=TIME_MODES, help=t.t(K.CLI_HELP_TIME))
    parser.add_argument(
        "--lang",
        type=_language,
        metavar="CODE",
        help=t.t(K.CLI_HELP_LANG, languages=", ".join(LANGUAGES)),
    )
    parser.add_argument("--config", type=Path, metavar="FILE", help=t.t(K.CLI_HELP_CONFIG))
    parser.add_argument("--no-config", action="store_true", help=t.t(K.CLI_HELP_NO_CONFIG))
    parser.add_argument("--demo", action="store_true", help=t.t(K.CLI_HELP_DEMO))


def _add_language_flag(parser: argparse.ArgumentParser, t: Translator) -> None:
    """``--lang`` for a subcommand. Unset it leaves any ``--lang`` given before the subcommand alone."""
    parser.add_argument(
        "--lang",
        type=_language,
        metavar="CODE",
        default=argparse.SUPPRESS,
        help=t.t(K.CLI_HELP_LANG_COMMAND, languages=", ".join(LANGUAGES)),
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


def build_tui_parser(t: Translator | None = None) -> argparse.ArgumentParser:
    """The parser for ``wxbrief [ICAO ...]``, which opens the TUI; its help is in the language ``t``."""
    t = t or Translator.load(DEFAULT_LANGUAGE)
    parser = argparse.ArgumentParser(prog="wxbrief", description=t.t(K.CLI_DESCRIPTION), epilog=t.t(K.CLI_EPILOG))
    _add_global_flags(parser, t)
    parser.add_argument("stations", nargs="*", metavar="ICAO", help=t.t(K.CLI_HELP_STATIONS))
    return parser


def build_parser(t: Translator | None = None) -> argparse.ArgumentParser:
    """Return the top-level argument parser."""
    t = t or Translator.load(DEFAULT_LANGUAGE)
    parser = argparse.ArgumentParser(prog="wxbrief", description=t.t(K.CLI_DESCRIPTION))
    _add_global_flags(parser, t)
    commands = parser.add_subparsers(dest="command", metavar="command")

    decode = commands.add_parser(
        "decode", help=t.t(K.CLI_HELP_DECODE), description=t.t(K.CLI_HELP_DECODE_DESCRIPTION)
    )
    decode.add_argument("reports", nargs="*", metavar="RAW", help=t.t(K.CLI_HELP_RAW))
    _add_language_flag(decode, t)
    output = decode.add_mutually_exclusive_group()
    output.add_argument("--plain", action="store_true", help=t.t(K.CLI_HELP_PLAIN))
    output.add_argument("--json", action="store_true", help=t.t(K.CLI_HELP_JSON))
    output.add_argument("--discord", action="store_true", help=t.t(K.CLI_HELP_DISCORD))
    decode.add_argument(
        "--units", choices=[mode.value for mode in UnitsMode], default=None, help=t.t(K.CLI_HELP_UNITS_MODE)
    )
    decode.add_argument(
        "--date", type=_parse_date, metavar="YYYY-MM-DD", help=t.t(K.CLI_HELP_DATE)
    )
    decode.add_argument("--theme", metavar="NAME", default=None, help=t.t(K.CLI_HELP_DECODE_THEME))
    add_get_parser(commands, t)
    _add_language_flag(commands.choices["get"], t)
    return parser


def _collect_texts(arguments: Sequence[str], stdin: TextIO) -> list[str]:
    """The pieces of text to decode: one per quoted argument (bare words are one), or all of stdin."""
    if arguments:
        if len(arguments) > 1 and not any(any(ch.isspace() for ch in arg) for arg in arguments):
            return [" ".join(arguments)]
        return [arg for arg in arguments if arg.strip()]
    if stdin.isatty():
        return []
    buffer = getattr(stdin, "buffer", None)
    text = stdin.read() if buffer is None else _decode_bytes(buffer.read())  # no bytes under it: a test's StringIO
    return [text] if text.strip() else []


def _decode_bytes(data: bytes) -> str:
    """Piped report text: UTF-8 (a BOM is dropped) or, with a UTF-16 BOM, UTF-16; bad bytes become U+FFFD."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    return data.decode("utf-8-sig", errors="replace")


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

    if args.json:
        sys.stdout.write(json.dumps([to_dict(item) for item in decoded], indent=2, ensure_ascii=False) + "\n")
        return 0

    units = UnitsMode(args.units or args.tui_units or (UnitsMode.US.value if args.discord else UnitsMode.MIXED.value))
    translator = Translator.load(args.lang or DEFAULT_LANGUAGE)
    if args.discord:
        sys.stdout.write("\n\n".join(render_discord(item, translator, units) for item in decoded) + "\n")
        return 0

    plain = "\n\n".join(render_plain(item, translator, units) for item in decoded) + "\n"
    if args.plain:
        sys.stdout.write(plain)
        return 0

    from rich.console import Console
    from rich.text import Text

    from wxbrief.render.richtext import DEFAULT_THEME, build_renderable

    rich_theme = palette.rich_theme if palette else DEFAULT_THEME
    # A pipe has no Windows console to draw on, so a forced colour there has to be ANSI codes.
    console = Console(theme=rich_theme, legacy_windows=None if sys.stdout.isatty() else False)
    if not console.is_terminal:  # Rich decides, so FORCE_COLOR and NO_COLOR are honoured as everywhere else
        sys.stdout.write(plain)
        return 0
    for index, item in enumerate(decoded):
        if index:
            console.print(Text(""))
        console.print(build_renderable(item, translator, units))
    return 0


def _run_tui(args: argparse.Namespace, translator: Translator) -> int:
    """Open the TUI. Without a terminal there is nothing to draw on, so print the help instead."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        sys.stdout.write(build_tui_parser(translator).format_help())
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
    from_flags: set[str] = set()
    for name, value in (
        ("theme", args.tui_theme),
        ("glyph_set", args.glyphs),
        ("layout", args.layout),
        ("units", args.tui_units),
        ("time", args.time),
        ("lang", args.lang),
    ):
        if value:
            setattr(view, name, value)
            from_flags.add(name)
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
        ids=cleaned,
        notices=notices,
        config_usable=loaded.usable,
        config=loaded.config,
        view=view,
        config_path=args.config,
        use_config=not args.no_config,
        theme_from_flag=bool(args.tui_theme),
        flag_view=frozenset(from_flags),
        config_warnings=loaded.warnings,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line and return the process exit code."""
    words = list(sys.argv[1:] if argv is None else argv)
    if words == ["--selftest"]:  # hidden: the smoke test of a built binary
        from wxbrief.selftest import run_selftest

        return run_selftest()
    # Always UTF-8 on stdout, help text included: a pipe on Windows defaults to the ANSI code page, which turns the
    # degree sign into a lone 0xB0 byte. Never fail on a character the stream cannot encode.
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="replace")
    translator = _help_translator(words)
    if _first_positional(words) not in COMMANDS:
        tui_args = build_tui_parser(translator).parse_args(words)
        return _run_tui(tui_args, translator)
    args = build_parser(translator).parse_args(words)
    try:
        return _run_decode(args) if args.command == "decode" else run_get(args)
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:  # the reader (``| head``) went away: stop quietly
        with contextlib.suppress(OSError, ValueError):  # point stdout at nothing, so the flush at exit cannot raise
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
            os.close(devnull)
        return 1


if __name__ == "__main__":
    sys.exit(main())
