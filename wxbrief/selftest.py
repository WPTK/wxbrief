"""``wxbrief --selftest``: a smoke test of a built binary. It checks that the bundled data files are present and the
decoder runs, prints one line per check and returns 0 only if every check passed. No network, no config, no cache."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from importlib import resources
from zoneinfo import ZoneInfo

from wxbrief import __version__

METAR = "METAR KDEN 131453Z 06007KT 3/4SM BR OVC003 09/08 A3001"
TAF = "TAF KDEN 131130Z 1312/1418 06007KT P6SM SCT050 FM131800 18010KT P6SM BKN080"


def _catalogs() -> str:
    from wxbrief.i18n import LANGUAGES, Translator

    for lang in LANGUAGES:
        if Translator.load(lang).lang != lang:
            raise RuntimeError(f"catalog {lang} did not load")
    return f"{len(LANGUAGES)} catalogs"


def _stations() -> str:
    from wxbrief.data.stations import bundled

    db = bundled()
    station = db.get("KDEN")
    if len(db) < 1000 or station is None or not station.tz:
        raise RuntimeError("station database is incomplete")
    ZoneInfo(station.tz)  # needs tzdata on Windows
    return f"{len(db)} stations"


def _assets() -> str:
    if not resources.files("wxbrief.ui").joinpath("app.tcss").is_file():
        raise RuntimeError("app.tcss is missing")
    return "app.tcss"


def _decode() -> str:
    from wxbrief.decode.model import Metar, Taf
    from wxbrief.decode.split import parse_any
    from wxbrief.i18n import Translator
    from wxbrief.render.plain import render_plain

    translator = Translator.load("en")
    reference = datetime(2026, 10, 13, 15, 0, tzinfo=UTC)
    reports = parse_any(f"{METAR}\n{TAF}", reference)
    if [type(r) for r in reports] != [Metar, Taf]:
        raise RuntimeError("the bundled METAR and TAF did not decode")
    for report in reports:
        if not render_plain(report, translator).strip():
            raise RuntimeError("empty decode")
    return "METAR and TAF"


def _demo() -> str:
    from wxbrief.data.demo import demo_ids, load_demo

    stations = load_demo()
    if not stations or len(stations) != len(demo_ids()):
        raise RuntimeError("demo data did not load")
    return f"{len(stations)} demo stations"


def _app() -> str:
    import importlib
    import io

    from rich.console import Console
    from rich.text import Text

    screens = ("add_station", "briefing", "help", "paste", "settings", "station_detail", "theme_picker")
    for module in ("wxbrief.app", *(f"wxbrief.ui.screens.{name}" for name in screens)):
        importlib.import_module(module)

    out = io.StringIO()
    console = Console(file=out, width=40, force_terminal=True, color_system="truecolor")
    console.print(Text("LIFR ▒▀ ° →", "bold red"))
    if "LIFR" not in out.getvalue():
        raise RuntimeError("rich did not render")
    return "TUI modules and rich"


CHECKS: tuple[tuple[str, Callable[[], str]], ...] = (
    ("app", _app),
    ("catalogs", _catalogs),
    ("stations", _stations),
    ("assets", _assets),
    ("decode", _decode),
    ("demo", _demo),
)


def run_selftest() -> int:
    print(f"wxbrief {__version__} selftest")
    failed = 0
    for name, check in CHECKS:
        try:
            detail = check()
        except Exception as error:
            failed += 1
            print(f"FAIL {name}: {error!r}")
        else:
            print(f"ok   {name}: {detail}")
    return 1 if failed else 0
