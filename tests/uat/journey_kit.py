"""Shared pieces of the real-input journeys (``test_real_*.py``): launch the program, a fault-injectable feed, helpers.

The program is the one under test: the built executable when ``WXBRIEF_PTY_EXE`` names one, else ``python -m wxbrief``
(from ``WXBRIEF_PTY_SRC`` when that names another source tree). Input is what a terminal sends (keys, SGR mouse reports
with the pointer moving in before every click); assertions are on drawn text, on files and on exit codes.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
import tomllib
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from awc_payloads import fresh_payloads
from status_rules import broken_rules, status_bar
from uat_kit import Screen, Terminal, unavailable_reason
from uat_kit.faultproxy import FaultProxy

EXE = os.environ.get("WXBRIEF_PTY_EXE")
SRC = os.environ.get("WXBRIEF_PTY_SRC")
Start = Callable[..., Terminal]

NO_PTY = unavailable_reason()
NO_OPENSSL = shutil.which("openssl") is None

needs_pty = [
    pytest.mark.pty,
    pytest.mark.timeout(120),
    pytest.mark.skipif(bool(NO_PTY), reason=f"real-terminal layer unavailable: {NO_PTY}"),
]
needs_feed = [*needs_pty, pytest.mark.skipif(NO_OPENSSL, reason="openssl is needed to make the test CA")]

DEMO_STATIONS = ["KDEN", "EGLL", "ETHB", "UUEE", "YSSY", "RJTT", "VIDP", "SBGR", "CYYZ", "NZSP"]
FEED_STATIONS = ["KLGA", "KPIT", "KJFK"]  # short US stations: METAR and TAF fit one 200x50 screen


def program() -> list[str]:
    return [EXE] if EXE else [sys.executable, "-m", "wxbrief"]


def program_env() -> dict[str, str]:
    return {"PYTHONPATH": SRC} if SRC and not EXE else {}


def launch(
    cols: int,
    rows: int,
    args: list[str] | None = None,
    *,
    config: bool = True,
    root: Path | None = None,
    env: dict[str, str] | None = None,
    prepare: Callable[[Path], None] | None = None,
) -> Terminal:
    """Start the program. ``config`` puts ``--config <root>/config.toml`` first (a scratch config, never the user's).

    ``root`` is a directory that outlives the terminal (for a relaunch); without it the terminal's own scratch directory."""
    here = str(root) if root else "{dir}"
    argv = [*program()]
    if config:
        argv += ["--config", f"{here}/config.toml"]
    argv += args or []
    extra = {"WXBRIEF_CACHE_DIR": f"{here}/cache", **program_env(), **(env or {})}
    return Terminal(argv, cols, rows, env=extra, env_remove=("WXBRIEF_CONFIG",), prepare=prepare)


class Session:
    """Everything a journey started, closed (killed by PID) at the end of the test."""

    def __init__(self) -> None:
        self.terminals: list[Terminal] = []
        self.proxies: list[FaultProxy] = []

    def start(
        self,
        cols: int = 120,
        rows: int = 30,
        args: list[str] | None = None,
        *,
        ready: str | None = "Stations",
        timeout: float = 45,
        **kw: Any,
    ) -> Terminal:
        term = launch(cols, rows, args, **kw)
        self.terminals.append(term)
        if ready:
            term.wait_for(lambda s: ready in s, timeout, f"{ready!r} on screen")
            term.settle()
        return term

    def feed(
        self, stations: list[str] | None = None, *, mutate: Callable[[dict[str, Any]], None] | None = None, **kw: Any
    ) -> FaultProxy:
        data = fresh_payloads(stations or FEED_STATIONS, **kw)
        if mutate:
            mutate(data)
        fp = FaultProxy(data, directory=Path(_pki_dir()) / f"pki{len(self.proxies)}")
        fp.start()
        self.proxies.append(fp)
        return fp

    def live(
        self,
        cols: int = 120,
        rows: int = 30,
        *,
        stations: list[str] | None = None,
        args: list[str] | None = None,
        fresh: bool = True,
        feed_kw: dict[str, Any] | None = None,
        mutate: Callable[[dict[str, Any]], None] | None = None,
        rules: list[tuple[str, str]] | None = None,
        **kw: Any,
    ) -> tuple[FaultProxy, Terminal]:
        """The program in live mode against a fake AWC (HTTPS_PROXY + SSL_CERT_FILE; no hook in the app).

        ``stations`` are given on the command line (``feed_kw["stations"]`` names the stations the fake knows when they
        differ); ``rules`` are (product, behaviour) pairs in force from the first request."""
        names = stations or FEED_STATIONS
        fp = self.feed((feed_kw or {}).pop("stations", names), mutate=mutate, **(feed_kw or {}))
        for product, behaviour in rules or []:
            fp.set(product, behaviour)
        env = {**fp.env(), **kw.pop("env", {})}  # the whole fp.env(): the kit's dead proxy must be overridden
        term = launch(cols, rows, ["--no-config", *(args or []), *names], config=False, env=env, **kw)
        self.terminals.append(term)
        term.wait_for(lambda s: "Stations" in s, 45, "the station list")
        if fresh:
            term.wait_for(lambda s: "fresh" in (status_bar(s) or ""), 45, "fresh data in the status bar")
        term.settle()
        return fp, term

    def close(self) -> None:
        for term in self.terminals:
            term.close()
        for fp in self.proxies:
            fp.stop()


_PKI: list[Path] = []


def _pki_dir() -> str:
    import tempfile

    if not _PKI:
        _PKI.append(Path(tempfile.mkdtemp(prefix="uat-pki-")))
    return str(_PKI[0])


@pytest.fixture
def session() -> Iterator[Session]:
    s = Session()
    yield s
    s.close()


# -- helpers ----------------------------------------------------------------------------------------------------------


def ctl(fp: FaultProxy, path: str, body: dict[str, Any] | None = None) -> Any:
    """The fake's control channel over HTTP, as a person with curl would use it."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(fp.control_url + path, data=data, method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.load(resp)


def counts(fp: FaultProxy) -> tuple[int, int]:
    return len(fp.requests("metar")), len(fp.requests("taf"))


def watch(term: Terminal, seconds: float, every: float = 0.4) -> list[str]:
    """Sample the status bar for ``seconds``; fail with the screen at the first sample that breaks a rule."""
    seen: list[str] = []
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        screen = term.screen()
        bar = status_bar(screen)
        if bar:
            seen.append(bar)
            bad = broken_rules(bar)
            assert not bad, f"{bad} in status bar {bar!r}\n{screen.text}"
        time.sleep(every)
    return seen


def forced_cycle(term: Terminal, fp: FaultProxy, timeout: float = 30) -> None:
    """Press ``r`` and wait until the program has asked for both METAR and TAF again."""
    m0, t0 = counts(fp)
    term.send_keys("r")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        m, t = counts(fp)
        if m > m0 and t > t0:
            return
        time.sleep(0.2)
    raise AssertionError(f"no METAR+TAF request in {timeout:g} s after r (was {m0},{t0}; now {counts(fp)})\n{term.screen_text()}")


def position(screen: Screen) -> tuple[int, int] | None:
    """The 'N/M' selection counter of the status bar, or None."""
    for line in screen.lines[-3:]:
        found = re.match(r"\s*(\d+)/(\d+)\s", line)
        if found:
            return int(found[1]), int(found[2])
    return None


def footer(screen: Screen) -> str:
    return screen.lines[-1]


def stations_listed(screen: Screen) -> int | None:
    """N of the 'Stations (N)' title of the list pane (None when the title shows no count)."""
    found = re.search(r"Stations \((\d+)\)", screen.text)
    return int(found[1]) if found else None


def row_of(screen: Screen, station: str, left_of: int = 40) -> tuple[int, int]:
    """Cell (col, row) of a station id in the list (or the card header in the grid)."""
    for row, line in enumerate(screen.lines[:-2]):
        col = line.find(station)
        if 0 <= col < left_of or (left_of > 100 and col >= 0):
            return col, row
    raise AssertionError(f"{station} not on screen:\n{screen.text}")


def saved_config(config: Path) -> dict[str, Any]:
    """The parsed config file (empty when there is none)."""
    return tomllib.loads(config.read_text(encoding="utf-8")) if config.exists() else {}


def saved_stations(config: Path) -> list[str]:
    return list(saved_config(config).get("stations", {}).get("watchlist", []))


def seed_config(stations: list[str], extra: str = "") -> Callable[[Path], None]:
    """``prepare=`` hook that writes a config naming ``stations`` (plus raw TOML ``extra``) before the program starts."""

    def write(directory: Path) -> None:
        listing = ", ".join(f'"{s}"' for s in stations)
        (directory / "config.toml").write_text("[stations]" + chr(10) + f"watchlist = [{listing}]" + chr(10) + extra, encoding="utf-8")

    return write


def detail_station(screen: Screen) -> str | None:
    """The station the detail pane is about: the id that starts the header line on the right of the list."""
    for line in screen.lines[:4]:
        pane = line.partition("▎")[2].strip() if "▎" in line else ""
        found = re.match(r"([A-Z0-9]{4})\s{2}\S", pane)
        if found:
            return found[1]
    return None


def bottom(screen: Screen) -> str:
    """The status bar, the toast beside it and the key bar."""
    return " ".join(screen.lines[-3:])


def calm(term: Terminal, seconds: float = 0.5) -> Screen:
    """Let the program draw what a key did, then wait until the screen is still."""
    term.hold(seconds)
    return term.settle(0.3)


def quit_cleanly(term: Terminal) -> None:
    term.settle(0.3)  # an Esc straight before q is read as Alt+q by every terminal program
    term.send_keys("q")
    assert term.wait_exit(15) == 0, "q did not end the program with exit code 0:" + chr(10) + term.screen_text()
