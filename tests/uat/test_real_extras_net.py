"""L1 (fault matrix), L2 (error text hygiene on the screen) and L3 (slow data) through the fault proxy."""

from __future__ import annotations

import re
import time

import pytest
from journey_kit import Session, bottom, calm, needs_feed
from status_rules import broken_rules, status_bar

pytestmark = needs_feed

LEAKS = re.compile(r"Error|Exception|Traceback|https?://", re.IGNORECASE)
REASON = re.compile(r"offline|problem|fail|error|unavailable|retry|empty|no data|no (metar|taf)|not (available|found)|stale", re.I)
WITHIN = 25  # seconds for a failing source to show its state


SILENT = pytest.mark.xfail(strict=True, reason="#262: a dropped connection or an empty list gets no reason on screen")
CASES = [
    pytest.param(product, behaviour, marks=[SILENT] if (product, behaviour) in {("metar", "drop:99"), ("metar", "empty_list"), ("taf", "drop:99"), ("taf", "empty_list")} else [])
    for product in ("metar", "taf")
    for behaviour in ("5xx", "badjson", "empty_list", "drop:99")
]


@pytest.mark.parametrize("product,behaviour", CASES)
def test_L1_L2_a_failing_source_reaches_a_stated_state_with_a_way_to_retry(session: Session, product: str, behaviour: str) -> None:
    fp, term = session.live(fresh=False, rules=[(product, behaviour)])
    deadline = time.monotonic() + WITHIN
    seen = ""
    while time.monotonic() < deadline:
        screen = term.screen()
        bar = status_bar(screen) or ""
        seen = bottom(screen)
        assert not broken_rules(bar), f"{broken_rules(bar)} in {bar!r}"
        if len(fp.requests(product)) >= 1 and REASON.search(screen.text):
            break
        time.sleep(0.5)
    else:
        raise AssertionError(f"no stated reason within {WITHIN} s for {product} {behaviour}:\n{term.screen_text()}")
    # L2: nothing a person reads names an internal
    shown = [line for line in term.screen().lines if LEAKS.search(line)]
    assert not shown, f"internal wording on screen: {shown}"
    # and a way to retry: r asks again
    n0 = len(fp.requests(product))
    term.send_keys("r")
    end = time.monotonic() + 20
    while time.monotonic() < end and len(fp.requests(product)) <= n0:
        time.sleep(0.2)
    assert len(fp.requests(product)) > n0, f"r did not ask for {product} again: {seen}"


@pytest.mark.parametrize(
    "delay", [5, pytest.param(20, marks=pytest.mark.uat_live)]
)
def test_L3_slow_data_updates_the_view_without_a_keypress(session: Session, delay: int) -> None:
    _fp, term = session.live(fresh=False, rules=[("metar", f"slow:{delay}"), ("taf", f"slow:{delay}")])
    assert term.alive()
    term.wait_for(lambda s: "fresh" in (status_bar(s) or "") and "No report yet" not in s.text, delay + 40, "the view filled in by itself")
    assert not broken_rules(status_bar(term.screen()) or "")
    calm(term)
    assert term.alive()
