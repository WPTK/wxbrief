"""Command-line entry point: ``python -m wxbrief`` or the ``wxbrief`` script."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from wxbrief import __version__


def build_parser() -> argparse.ArgumentParser:
    """Return the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="wxbrief",
        description="Terminal METAR/TAF briefing with colorways and plain-language translation.",
    )
    parser.add_argument("--version", action="version", version=f"wxbrief {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line and return the process exit code."""
    parser = build_parser()
    parser.parse_args(argv)
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
