"""J11-J15 and J17 of the UAT plan: the real program against a fault-injectable fake AWC.

The program is unmodified: it reaches the fake through HTTPS_PROXY and a test CA in SSL_CERT_FILE (no hook in the app).
Time is real, so these use ``r`` (both products due at once) to run poll cycles in seconds. The 12-minute session and the
slow-response cases carry ``uat_live`` and run with WXBRIEF_UAT_LIVE=1.
"""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest
from journey_kit import (
    FEED_STATIONS,
    Session,
    bottom,
    calm,
    counts,
    ctl,
    detail_station,
    forced_cycle,
    needs_feed,
    position,
    program,
    program_env,
    quit_cleanly,
    watch,
)
from status_rules import broken_rules, status_bar
from uat_kit.styled import changed_rows, styled_rows

pytestmark = needs_feed

BOTH_DOWN = [("metar", "reset"), ("taf", "reset")]
WHY = re.compile(r"(?i)offline|network|connect|reach|internet|unavailable|could not|can't|failed|problem")


def bar_of(term: Any) -> str:
    return status_bar(term.screen()) or ""


# -- J11 --------------------------------------------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="#236: first run with the network down shows no reason for about a minute")
def test_J11_first_run_with_the_network_down_says_why_within_5_seconds(session: Session) -> None:
    _fp, term = session.live(fresh=False, rules=BOTH_DOWN)
    term.hold(5.0)
    shown = term.screen().text.replace("No report yet. Press r to refresh.", "")
    assert WHY.search(shown), f"nothing says why there is no data after 5 s:\n{term.screen_text()}"


def test_J11_the_network_returns_and_the_data_arrives_without_a_restart(session: Session) -> None:
    fp, term = session.live(fresh=False, rules=BOTH_DOWN)
    assert "No report yet" in term.screen()
    ctl(fp, "/reset", {})
    forced_cycle(term, fp)
    screen = term.wait_for(lambda s: "fresh" in (status_bar(s) or ""), 40, "fresh data after the network came back")
    assert detail_station(screen) == FEED_STATIONS[0] and "METAR KLGA" in screen.text, screen.text
    shown = max(sum(line.count("Refreshing") for line in term.screen().lines) for _ in range(3))
    assert shown <= 1, "the refresh toast was shown more than once"
    assert not broken_rules(status_bar(screen) or "")
    quit_cleanly(term)


# -- J12 --------------------------------------------------------------------------------------------------------------


def test_J12_offline_with_a_warm_cache_shows_the_saved_data_and_recovers(session: Session, tmp_path: Path) -> None:
    fp, first = session.live(root=tmp_path)  # run once online: the cache is written
    assert "METAR KLGA" in first.screen().text
    quit_cleanly(first)
    assert list((tmp_path / "cache").glob("*.json")), "no cache was written"
    fp.reset()
    for product, behaviour in BOTH_DOWN:
        fp.set(product, behaviour)
    term = session.start(120, 30, ["--no-config", *FEED_STATIONS], config=False, root=tmp_path, env=fp.env())
    screen = term.wait_for(lambda s: "METAR KLGA" in s.text, 20, "the saved report on screen while the network is down")
    for _ in range(3):
        forced_cycle(term, fp)
        watch(term, 3.0)
    bar = bar_of(term)
    assert "offline" in bar.lower() and "saved" in bar.lower(), f"outage not stated with what is shown: {bar!r}"
    assert not re.search(r"\bfresh\b", bar.lower()) and not broken_rules(bar), bar
    assert "METAR KLGA" in term.screen().text, "the saved data went away when the network did"
    fp.reset()
    forced_cycle(term, fp)
    term.wait_for(lambda s: "fresh" in (status_bar(s) or "") and "offline" not in (status_bar(s) or ""), 40, "recovery")
    assert screen


# -- J13 --------------------------------------------------------------------------------------------------------------

COMBOS = {
    "taf_5xx": [("taf", "5xx")],
    "metar_reset_taf_ok": [("metar", "reset")],
    "both_fail_one_cycle": [("metar", "reset"), ("taf", "reset")],
    "bad_json": [("metar", "badjson")],
    "empty_list": [("metar", "empty_list")],
}


@pytest.mark.parametrize("combo", list(COMBOS))
def test_J13_partial_failures_never_make_the_status_bar_contradict_itself(session: Session, combo: str) -> None:
    fp, term = session.live()
    cycles = 1 if combo == "both_fail_one_cycle" else 3
    for product, behaviour in COMBOS[combo]:
        ctl(fp, "/rule", {"product": product, "behavior": behaviour, **({"count": 1} if cycles == 1 else {})})
    for _ in range(cycles):
        forced_cycle(term, fp)
        bars = watch(term, 3.0)
        assert bars, "the status bar was never visible"
        assert term.alive() and "Traceback" not in term.screen().text
    if combo == "both_fail_one_cycle":
        assert "offline" not in bar_of(term).lower(), f"one blip showed as an outage: {bar_of(term)!r}"
    ctl(fp, "/reset", {})
    forced_cycle(term, fp)
    term.wait_for(lambda s: recovered(status_bar(s) or ""), 40, "fresh again, no problem named")
    assert "METAR KLGA" in term.screen().text


def recovered(bar: str) -> bool:
    return bool(re.search(r"\bfresh\b", bar)) and not re.search(r"offline|problem", bar.lower()) and not broken_rules(bar)


def test_J13_a_429_with_retry_after_holds_the_product_then_recovers(session: Session) -> None:
    fp, term = session.live()
    ctl(fp, "/rule", {"product": "taf", "behavior": "429:12", "count": 1})
    forced_cycle(term, fp)
    watch(term, 3.0)
    held = len(fp.requests("taf"))
    term.send_keys("r")  # inside the Retry-After window: METAR may be asked again, the TAF must not be
    watch(term, 6.0)
    assert len(fp.requests("taf")) == held, "the TAF was requested again inside its Retry-After window"
    assert [r["status"] for r in fp.requests("taf")].count(429) == 1
    term.hold(8.0)
    forced_cycle(term, fp, 40)
    term.wait_for(lambda s: recovered(status_bar(s) or ""), 40, "fresh after the Retry-After window")


@pytest.mark.uat_live
def test_J13_a_slow_answer_does_not_freeze_the_keys_or_contradict_the_bar(session: Session) -> None:
    fp, term = session.live()
    ctl(fp, "/rule", {"product": "taf", "behavior": "slow:9000", "count": 1})
    ctl(fp, "/rule", {"product": "metar", "behavior": "slow:9000", "count": 1})
    forced_cycle(term, fp, 40)
    start = time.monotonic()
    term.send_keys("j")  # the keys stay live while the fetch is in flight
    term.wait_for(lambda s: position(s) == (2, 3), 2, "the selection moving within 2 s of the key")
    assert time.monotonic() - start < 3
    watch(term, 12.0)
    term.wait_for(lambda s: "fresh" in (status_bar(s) or ""), 30, "fresh after the slow answer")


# -- J14 --------------------------------------------------------------------------------------------------------------


def only_metar(station: str):
    def mutate(data: dict[str, Any]) -> None:
        data["taf"] = [r for r in data["taf"] if r["icaoId"] != station]

    return mutate


def only_taf(station: str):
    def mutate(data: dict[str, Any]) -> None:
        data["metar"] = [r for r in data["metar"] if r["icaoId"] != station]

    return mutate


def select(term: Any, index: int) -> None:
    for _ in range(index):
        term.send_keys("j")
    term.wait_for(lambda s: position(s) == (index + 1, len(FEED_STATIONS)), 10, f"station {index + 1} selected")
    calm(term, 0.3)


@pytest.mark.xfail(strict=True, reason="#253: a station with no TAF: the detail pane never says there is no forecast")
def test_J14_a_station_with_no_taf_says_so_in_the_detail_pane(session: Session) -> None:
    _fp, term = session.live(mutate=only_metar("KPIT"))
    select(term, 1)
    detail = "\n".join(line.partition("▎")[2] for line in term.screen().lines)
    assert re.search(r"(?i)no (TAF|forecast)", detail), f"the detail pane is silent about the missing forecast:\n{term.screen_text()}"


def test_J14_key_3_on_a_station_with_no_taf_explains_it(session: Session) -> None:
    _fp, term = session.live(mutate=only_metar("KPIT"))
    select(term, 1)
    before = styled_rows(term)
    term.send_keys("3")
    shown = calm(term)
    assert re.search(r"(?i)no TAF", bottom(shown)), f"key 3 said nothing about the missing TAF:\n{shown.text}"
    assert changed_rows(before, styled_rows(term))


def test_J14_a_station_with_a_taf_and_no_metar_says_so_for_key_2(session: Session) -> None:
    _fp, term = session.live(mutate=only_taf("KPIT"))
    select(term, 1)
    assert "TAF KPIT" in term.screen().text, "the forecast of a TAF-only station is not shown"
    term.send_keys("2")
    shown = calm(term)
    assert re.search(r"(?i)no (METAR|observation|report)", bottom(shown) + shown.text), shown.text


def test_J14_a_station_with_no_report_at_all_says_so(session: Session) -> None:
    _fp, term = session.live(stations=["KLGA", "KBOS"], feed_kw={"stations": ["KLGA"]})
    select_two = term
    select_two.send_keys("j")
    select_two.wait_for(lambda s: position(s) == (2, 2), 10, "KBOS selected")
    shown = calm(select_two, 0.4)
    assert "No report yet" in shown.text, shown.text
    for key in ("1", "2", "3"):
        select_two.send_keys(key)
        assert re.search(r"(?i)no (report|METAR|TAF)", bottom(calm(select_two, 0.3))), f"key {key}: silent on a station with nothing"


def test_J14_old_data_is_called_stale_never_fresh(session: Session) -> None:
    _fp, term = session.live(fresh=False, feed_kw={"metar_age": 100, "taf_age": 100})
    term.wait_for(lambda s: "METAR KLGA" in s.text, 45, "the old report")
    bar = bar_of(term)
    header = " ".join(term.screen().lines[:3])
    assert re.search(r"(?i)\bstale\b", header + " " + bar), f"a 100-minute-old report is not called stale:\n{term.screen_text()}"
    assert not re.search(r"\bfresh\b", header), f"stale data headed fresh: {header}"
    assert not broken_rules(bar), bar


# -- J15 --------------------------------------------------------------------------------------------------------------


@pytest.mark.uat_live
@pytest.mark.timeout(900)
def test_J15_a_twelve_minute_session_keeps_polling_politely_and_stays_steady(session: Session) -> None:
    fp, term = session.live()
    term.send_keys("j")
    term.wait_for(lambda s: position(s) == (2, 3), 10, "KPIT selected")
    started = time.monotonic()
    ages: list[str] = []
    while time.monotonic() - started < 12 * 60 + 15:
        bars = watch(term, 20.0, every=1.0)
        ages.append(bars[-1])
    assert position(term.screen()) == (2, 3) and detail_station(term.screen()) == "KPIT", "the selection moved by itself"
    metar, taf = counts(fp)
    assert metar >= 2, f"no METAR refresh in 12 minutes (10-minute interval): {metar}"
    assert taf == 1, f"the TAF was fetched {taf} times in 12 minutes (30-minute interval)"
    log = fp.requests("metar")
    assert all("wxbrief" in (r["user_agent"] or "") for r in log), "the User-Agent does not name wxbrief"
    assert any(r["if_none_match"] for r in log[1:]), "the second METAR request was not conditional (ETag unused)"
    assert len({re.sub(r"\d+", "#", a) for a in ages}) < 6, "the status bar keeps changing shape"
    assert max(r["t"] for r in log) - min(r["t"] for r in log) > 9 * 60


# -- J17 --------------------------------------------------------------------------------------------------------------


def run_cli(
    fp: Any, *args: str, stdin: str | None = None, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    import os

    env = {**os.environ, **program_env(), **fp.env(), "PYTHONUTF8": "1", "NO_COLOR": "1", **(env or {})}
    return subprocess.run([*program(), *args], capture_output=True, text=True, timeout=60, env=env, input=stdin, check=False)


def test_J17_get_prints_both_reports_and_exits_zero(session: Session) -> None:
    fp = session.feed()
    done = run_cli(fp, "get", "KLGA", "--plain")
    assert done.returncode == 0 and "Traceback" not in done.stderr, done.stderr
    assert "Routine observation (METAR)" in done.stdout and "Terminal forecast (TAF)" in done.stdout
    agent = {r["user_agent"] for r in fp.requests()}
    assert agent and all("wxbrief" in (a or "") for a in agent)
    as_json = run_cli(fp, "get", "KLGA", "--json")
    assert as_json.returncode == 0 and as_json.stdout.lstrip().startswith(("[", "{"))


def test_J17_get_retries_once_when_the_first_request_fails(session: Session) -> None:
    fp = session.feed()
    fp.set("metar", "reset", 1)
    done = run_cli(fp, "get", "KLGA", "--plain")
    assert done.returncode == 0 and "Routine observation (METAR)" in done.stdout, done.stdout + done.stderr
    assert [r["status"] for r in fp.requests("metar")].count("reset") == 1 and len(fp.requests("metar")) == 2


@pytest.mark.xfail(strict=True, reason="#254: wxbrief get prints raw ConnectError text when the network is down")
def test_J17_get_with_the_network_down_gives_a_plain_message(session: Session) -> None:
    fp = session.feed()
    dead = "http://127.0.0.1:9"  # nothing listens: the connection is refused, as with no network
    done = run_cli(fp, "get", "KLGA", "--plain", env={"HTTPS_PROXY": dead, "https_proxy": dead})
    text = done.stderr + done.stdout
    assert done.returncode != 0 and "Traceback" not in text
    assert "ConnectError" not in text and "httpx" not in text, text
