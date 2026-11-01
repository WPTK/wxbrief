"""Known-bad acceptance: Bill's reports, reproduced with the REAL program against a fault-injectable fake AWC.

Runs only when ``WXBRIEF_UAT_KNOWNBAD=1`` and ``WXBRIEF_PTY_EXE`` names the program (never in the default CI run):
every test takes 20 to 120 s of real time, because poll cycles are real time. The same file is run twice:

  candidate exe built from main        -> every test passes
  the v0.3.0 release exe               -> J13b, J7b and the fixed-defect tests FAIL (that is the point)

Nothing is staged: the program starts in live mode, talks HTTPS through a CONNECT proxy to a local server wearing a
test certificate for aviationweather.gov (HTTPS_PROXY + SSL_CERT_FILE, no hook in the app), and the test presses keys and
clicks with the bytes a terminal sends. Fixture times are re-stamped so the data is FRESH.

Timing each test relies on (no clock hook exists, so only what the app does by itself, plus ``r``):
  * ``r`` (poll_now) makes both products due at once: a forced cycle in a few seconds. Used for cycles 2-4.
  * the first-failure retry: the app re-polls a failed product after 60 s by itself (main; v0.3.0 waits a full interval).
  * real intervals (METAR 10 min, TAF 30 min) are never waited for.
"""

from __future__ import annotations

import json
import os
import shutil
import time
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from awc_payloads import fresh_payloads
from status_rules import broken_rules, status_bar
from uat_kit import Screen, Terminal
from uat_kit.faultproxy import FaultProxy
from uat_kit.styled import changed_rows, detail_overflows, styled_rows

EXE = os.environ.get("WXBRIEF_PTY_EXE")
pytestmark = [
    pytest.mark.skipif(
        os.environ.get("WXBRIEF_UAT_KNOWNBAD") != "1" or not EXE,
        reason="known-bad acceptance: set WXBRIEF_UAT_KNOWNBAD=1 and WXBRIEF_PTY_EXE=<exe> (real time, run locally)",
    ),
    pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl is needed to make the test CA"),
    pytest.mark.timeout(240),
]

# Three short US stations (recorded 2026-10-31): METAR and TAF both fit one 200x50 screen with no scrollbar.
STATIONS = ["KLGA", "KPIT", "KJFK"]


@pytest.fixture(autouse=True)
def offline() -> None:
    """Override the offline guard of tests/uat/conftest.py: this module talks to the exe, not through httpx."""


# -- helpers ----------------------------------------------------------------------------------------------------------


def ctl(fp: FaultProxy, path: str, body: dict[str, Any] | None = None, method: str | None = None) -> Any:
    """The fake's control channel over HTTP, as a person with curl would use it."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(fp.control_url + path, data=data, method=method or ("POST" if data is not None else "GET"))
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.load(resp)


def counts(fp: FaultProxy) -> tuple[int, int]:
    return len(fp.requests("metar")), len(fp.requests("taf"))


@pytest.fixture
def feed(tmp_path: Path) -> Iterator[Callable[..., FaultProxy]]:
    made: list[FaultProxy] = []

    def make(stations: list[str] | None = None, **kw: Any) -> FaultProxy:
        fp = FaultProxy(fresh_payloads(stations or STATIONS, **kw), directory=tmp_path / f"pki{len(made)}")
        fp.start()
        made.append(fp)
        return fp

    yield make
    for fp in made:
        fp.stop()


@pytest.fixture
def live(feed: Callable[..., FaultProxy]) -> Iterator[Callable[..., tuple[FaultProxy, Terminal]]]:
    """``live(cols, rows, stations=...)`` -> (fake, terminal) with the program in live mode and data on screen."""
    made: list[Terminal] = []

    def start(
        cols: int = 120,
        rows: int = 30,
        *,
        stations: list[str] | None = None,
        args: list[str] | None = None,
        demo: bool = False,
        ready: bool = True,
        **kw: Any,
    ) -> tuple[FaultProxy, Terminal]:
        fp = feed(stations, **kw)
        env = {**fp.env(), "WXBRIEF_CACHE_DIR": "{dir}/cache"}  # the whole fp.env(): the kit's dead proxy must be overridden
        argv = [EXE or "", "--no-config", *(["--demo"] if demo else []), *(args or []), *([] if demo else (stations or STATIONS))]
        term = Terminal(argv, cols, rows, env=env)
        made.append(term)
        term.wait_for(lambda s: "Stations" in s, 45, "the station list")
        if ready and not demo:
            term.wait_for(lambda s: "fresh" in (status_bar(s) or ""), 45, "fresh data in the status bar")
        term.settle()
        return fp, term

    yield start
    for term in made:
        term.close()


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


def screen_has(screen: Screen, text: str) -> bool:
    return text.lower() in screen.text.lower()


# -- J13b: METAR ok, TAF fails --------------------------------------------------------------------------------------


@pytest.mark.parametrize("fault", ["5xx", "reset", "drop:60"])
def test_j13b_metar_ok_taf_fails_three_cycles_never_offline_beside_fresh(live: Callable[..., Any], fault: str) -> None:
    """Cycle 1 ok. TAF fails in cycles 2, 3 and 4 while METAR answers every cycle (200, fresh). The status bar never
    shows 'offline' beside 'fresh' (rule engine, sampled every 0.4 s through every cycle); then TAF recovers."""
    fp, term = live()
    assert watch(term, 1.0), "no status bar"
    ctl(fp, "/rule", {"product": "taf", "behavior": fault})  # from now on, every TAF request fails
    for cycle in (2, 3, 4):
        forced_cycle(term, fp)
        bars = watch(term, 4.0)
        assert bars, f"cycle {cycle}: the status bar was never visible"
    metar_codes = {r["status"] for r in fp.requests("metar")}
    assert metar_codes == {200}, f"the fake did not answer METAR ok every cycle: {metar_codes}"
    ctl(fp, "/reset", {})
    forced_cycle(term, fp)
    bars = watch(term, 4.0)
    assert any("fresh" in b for b in bars), bars
    last = status_bar(term.screen()) or ""
    assert "problem" not in last and "offline" not in last, last


def test_j13b_one_blip_shows_nothing(live: Callable[..., Any]) -> None:
    """A single dropped TAF connection, then ok: no offline, no problem text, no toast (#219/#223)."""
    fp, term = live()
    ctl(fp, "/rule", {"product": "taf", "behavior": "reset", "count": 1})
    forced_cycle(term, fp)
    term.hold(1.0)
    bars = watch(term, 4.0)
    assert bars
    shown = term.screen()
    for text in ("offline", "problem", "Could not fetch", "Can't reach"):
        assert not screen_has(shown, text), f"{text!r} shown after one blip:\n{shown.text}"
    assert all("offline" not in b and "problem" not in b for b in bars), bars


@pytest.mark.parametrize("fault", ["5xx", "reset"])
def test_blips_in_cycle_two_then_ok_stay_quiet(live: Callable[..., Any], fault: str) -> None:
    """One failure in cycle 2, ok in cycles 3 and 4: still nothing, and 'fresh' stays."""
    fp, term = live()
    ctl(fp, "/rule", {"product": "taf", "behavior": fault, "count": 1})
    for _ in range(3):
        forced_cycle(term, fp)
        bars = watch(term, 3.0)
        assert all("offline" not in b for b in bars), bars
    assert "fresh" in (status_bar(term.screen()) or "")


def test_taf_failure_is_retried_without_pressing_anything(live: Callable[..., Any]) -> None:
    """Timing relied on: the app's own first-failure retry. TAF fails from cycle 2; after the forced failing cycle the
    program must ask for the TAF again by itself within 95 s (main: 60 s; v0.3.0 waits for the 30-minute interval)."""
    fp, term = live()
    ctl(fp, "/rule", {"product": "taf", "behavior": "5xx"})
    forced_cycle(term, fp)
    started = time.time()
    deadline = time.monotonic() + 95
    while time.monotonic() < deadline and not [r for r in fp.requests("taf") if r["t"] > started + 20]:
        watch(term, 3.0)
    again = [r for r in fp.requests("taf") if r["t"] > started + 20]
    assert again, f"no TAF re-poll in 95 s: {[(round(r['t'] - started), r['status']) for r in fp.requests('taf')]}"


# -- J7b: sections that fit -----------------------------------------------------------------------------------------


def section_titles(screen: Screen) -> dict[str, int]:
    """Rows of the three detail-pane section titles that are on screen."""
    found = {}
    for name, needle in (("raw", "Raw"), ("decoded", "Decoded"), ("taf", "Forecast (TAF)")):
        for row, line in enumerate(screen.lines[:-2]):
            pane = line.partition("▎")[2].strip() if "▎" in line else line.strip()
            if pane == needle:
                found[name] = row
                break
    return found


@pytest.mark.parametrize("size", [(200, 50), (280, 70)], ids=["200x50", "280x70"])
@pytest.mark.parametrize("focus", ["list", "detail", "after_click"])
def test_j7b_keys_1_2_3_always_visibly_do_something_when_all_sections_fit(
    live: Callable[..., Any], size: tuple[int, int], focus: str
) -> None:
    """All three sections are on screen at once, so there is nothing to scroll. Each of 1, 2, 3 must still change what is
    visible (a selected/highlighted section title, a cursor) or show a toast that says why not. A silent press fails (#224)."""
    _fp, term = live(*size)
    if focus == "detail":
        term.send_keys("enter")
        term.wait_for(lambda s: "esc Back" in s.lines[-1], 10, "focus in the detail pane")
    elif focus == "after_click":
        term.click_text(STATIONS[1])
        term.settle()
    term.settle()
    start = term.screen()
    titles = section_titles(start)
    assert set(titles) == {"raw", "decoded", "taf"}, f"precondition: all three titles on screen at {size}:\n{start.text}"
    assert not detail_overflows(term), f"precondition: the detail pane must not scroll at {size}:\n{start.text}"
    silent = []
    for key in ("1", "2", "3"):
        before = styled_rows(term)
        term.send_keys(key)
        term.hold(0.5)
        term.settle(0.3)
        if not changed_rows(before, styled_rows(term)):  # text, colours and attributes of every cell; countdown ignored
            silent.append(key)
    assert not silent, f"silent key presses {silent} (focus={focus}, size={size}); nothing changed:\n{term.screen_text()}"


# -- the already-merged defects, in the live (fake-feed) setting ----------------------------------------------------


def test_real_outage_is_visible_then_recovers(live: Callable[..., Any]) -> None:
    """Both products fail (connection reset) in cycles 2, 3 and 4: from the second failure on the bar says offline and
    what is shown instead, never 'fresh' beside it; when the feed returns the bar is fresh again (J13, J12)."""
    fp, term = live()
    ctl(fp, "/rule", {"product": "metar", "behavior": "reset"})
    ctl(fp, "/rule", {"product": "taf", "behavior": "reset"})
    for _ in range(3):
        forced_cycle(term, fp)
        bars = watch(term, 3.0)
    assert any("offline" in b for b in bars), f"a real outage must be visible after 3 cycles: {bars}"
    ctl(fp, "/reset", {})
    forced_cycle(term, fp)
    bars = watch(term, 4.0)
    assert "fresh" in (status_bar(term.screen()) or "") and "offline" not in (status_bar(term.screen()) or ""), bars


def test_221_demo_label_stays_when_a_feed_is_reachable(live: Callable[..., Any]) -> None:
    """--demo with a working fake feed in the environment: the demo label is on the bar after its toast is gone and
    nothing is fetched (#221)."""
    fp, term = live(demo=True)
    term.hold(9.0)  # the toast lasts 6 s
    screen = term.settle()
    bottom = " ".join(screen.lines[-3:]).lower()
    assert "demo data, not live" in bottom, screen.text
    assert not fp.requests(), f"--demo fetched: {fp.requests()}"


def test_live_mode_does_not_say_demo(live: Callable[..., Any]) -> None:
    _fp, term = live()
    assert "demo" not in term.screen().text.lower(), term.screen_text()


def test_222_repeated_refresh_in_live_shows_one_toast(live: Callable[..., Any]) -> None:
    """r, r, r quickly: one 'Refreshing' toast, not a stack of them (#222)."""
    _fp, term = live()
    term.send_keys("r", "r", "r")
    seen = 0
    for _ in range(6):
        seen = max(seen, sum(line.count("Refreshing") for line in term.screen().lines))
        time.sleep(0.2)
    assert seen <= 1, f"{seen} 'Refreshing' toasts stacked:\n{term.screen_text()}"


def test_222_repeated_refresh_in_demo_with_a_feed_shows_one_toast(live: Callable[..., Any]) -> None:
    _fp, term = live(demo=True)
    term.send_keys("r", "r", "r")
    seen = 0
    for _ in range(6):
        seen = max(seen, sum(line.count("Polling is off") + line.count("nothing to refresh") for line in term.screen().lines))
        time.sleep(0.2)
    assert seen <= 1, f"{seen} toasts stacked:\n{term.screen_text()}"


def test_225_click_keeps_focus_on_the_list_in_live(live: Callable[..., Any]) -> None:
    """A click on a row selects it and the focus stays in the list: the key bar still offers 'd Remove' and not
    'esc Back' (the focus did not jump to the detail pane), half a second later too (#225)."""
    _fp, term = live()
    term.click_text(STATIONS[2])
    term.wait_for(lambda s: "3/3" in s.text, 10, "the third station selected")
    term.hold(0.6)
    keys = term.screen().lines[-1]
    assert "d Remove" in keys and "esc Back" not in keys, keys
    term.send_keys("up")  # a list key still moves the selection
    term.wait_for(lambda s: "2/3" in s.text, 5, "up moved the list selection")


def test_224_absent_section_is_explained_not_silent(live: Callable[..., Any]) -> None:
    """The part of #224 that #228 fixed: on a station with a METAR and no TAF, key 3 says so (a toast) instead of nothing."""
    _fp, term = live(stations=["KLGA", "KPIT"], no_taf=["KPIT"])
    term.send_keys("down")
    term.wait_for(lambda s: "2/2" in s.text, 5, "KPIT selected")
    term.settle()
    before = styled_rows(term)
    term.send_keys("3")
    term.hold(0.5)
    shown = term.screen()
    assert "no TAF" in shown.text, f"key 3 on a station without a TAF said nothing:\n{shown.text}"
    assert changed_rows(before, styled_rows(term))
