"""J1-J10, J16, J18-J21, J23, J24 of the UAT plan as real-input journeys (no network).

The program runs in a pseudo-terminal (``python -m wxbrief`` or the built executable); input is keys and SGR mouse
reports with the pointer moving in before each click; assertions are on the drawn screen, on the config file and on
the exit code. Journey numbers are the plan's (``tests/uat/JOURNEYS.md``).
"""

from __future__ import annotations

import random
import re
import shutil
import sys
from pathlib import Path

import pytest
from journey_kit import (
    DEMO_STATIONS,
    Session,
    bottom,
    calm,
    detail_station,
    footer,
    needs_pty,
    position,
    quit_cleanly,
    row_of,
    saved_config,
    saved_stations,
    seed_config,
    stations_listed,
)
from uat_kit.styled import changed_rows, detail_overflows, styled_rows

pytestmark = needs_pty

F2 = "\x1bOQ"  # what a terminal sends for F2
CTRL_Q = "\x11"
EMPTY = "No stations yet. Press a to add one."
REFRESH_IN_DEMO = r"Polling is off|nothing to refresh"


# -- J1 ---------------------------------------------------------------------------------------------------------------


def test_J1_first_run_add_denver_read_forecast_quit_and_the_station_is_back(session: Session, tmp_path: Path) -> None:
    """No config, no network: the empty state, ``a``, type 'Denver', click Denver Intl, ``3``, quit; relaunch shows it."""
    term = session.start(100, 28, root=tmp_path)
    assert EMPTY in term.screen()
    assert stations_listed(term.screen()) == 0
    term.send_keys("a")
    term.wait_for(lambda s: "Add station" in s, 10, "the add dialog")
    term.send_keys("Denver")
    term.wait_for(lambda s: "KDEN Denver Intl" in s, 10, "the Denver results")
    term.click_text("KDEN Denver Intl")
    term.wait_for(lambda s: stations_listed(s) == 1 and "Add station" not in s, 10, "KDEN added by the click")
    assert detail_station(term.screen()) == "KDEN"
    term.send_keys("3")
    assert "No report yet" in bottom(calm(term)), "key 3 with nothing to show gave no message"
    quit_cleanly(term)
    assert saved_stations(tmp_path / "config.toml") == ["KDEN"]

    again = session.start(100, 28, root=tmp_path)
    assert stations_listed(again.screen()) == 1 and detail_station(again.screen()) == "KDEN"


# -- J2 ---------------------------------------------------------------------------------------------------------------


def test_J2_stations_on_the_command_line_are_for_this_run_only(session: Session, tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    seed_config(["KSFO"])(tmp_path)
    before = config.read_bytes()
    term = session.start(120, 30, ["KDEN", "EGLL", "ETHB"], root=tmp_path)
    screen = term.screen()
    assert stations_listed(screen) == 4
    for station in ("KSFO", "KDEN", "EGLL", "ETHB"):
        assert station in screen, f"{station} missing:\n{screen.text}"
    quit_cleanly(term)
    assert config.read_bytes() == before, "a run with stations on the command line rewrote the config"


def test_J2_no_config_file_means_no_file_written(session: Session, tmp_path: Path) -> None:
    term = session.start(120, 30, ["KDEN", "EGLL", "ETHB"], root=tmp_path)
    assert stations_listed(term.screen()) == 3
    quit_cleanly(term)
    assert not (tmp_path / "config.toml").exists()


# -- J3 ---------------------------------------------------------------------------------------------------------------


def test_J3_demo_browse_ten_stations_keys_refresh_add_remove_theme_and_nothing_saved(session: Session, tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    seed_config(["KSFO"], "[view]\ntheme = \"paper-chart\"\n")(tmp_path)
    before = config.read_bytes()
    term = session.start(120, 30, ["--demo"], root=tmp_path)
    assert "KSFO" not in term.screen(), "the saved list is shown in demo mode"
    for index, station in enumerate(DEMO_STATIONS):
        if index:
            term.send_keys("j")
            term.wait_for(lambda s, i=index: position(s) == (i + 1, 10), 10, f"{station} selected")
        assert detail_station(term.screen()) == station, term.screen_text()
        assert "demo data, not live" in bottom(term.screen()), f"{station}: demo label missing"
    for key in ("3", "2", "1"):
        before_rows = styled_rows(term)
        term.send_keys(key)
        calm(term)
        assert changed_rows(before_rows, styled_rows(term)), f"key {key} changed nothing visible in demo mode"
    term.send_keys("r")
    term.wait_for(lambda s: re.search(REFRESH_IN_DEMO, bottom(s)) is not None, 5, "the refresh message")
    term.send_keys("a", "EGKK")
    term.wait_for(lambda s: "EGKK" in s.text.split("Add station")[-1], 10, "the Gatwick result")
    term.send_keys("enter")
    term.wait_for(lambda s: stations_listed(s) == 11, 10, "Gatwick added in demo mode")
    term.send_keys("d")
    term.wait_for(lambda s: stations_listed(s) == 10, 10, "the added station removed again")
    colours = styled_rows(term)
    term.send_keys("t")
    assert changed_rows(colours, calm(term) and styled_rows(term)), "t changed no colour"
    assert "demo data, not live" in bottom(term.screen())
    quit_cleanly(term)
    assert config.read_bytes() == before, "demo mode wrote the config"


# -- J4 ---------------------------------------------------------------------------------------------------------------


def add(term, query: str, wait_for: str | None) -> None:
    term.send_keys("a")
    term.wait_for(lambda s: "Add station" in s, 10, "the add dialog")
    term.send_keys(query)
    if wait_for:
        term.wait_for(lambda s: wait_for in s.text.split("Add station")[-1], 10, f"{wait_for!r} among the results")
    calm(term, 0.3)
    term.send_keys("enter")


def test_J4_add_by_icao_iata_and_name_and_say_what_happened_otherwise(session: Session, tmp_path: Path) -> None:
    seed_config(["KDEN"])(tmp_path)
    term = session.start(120, 30, root=tmp_path)
    assert stations_listed(term.screen()) == 1

    add(term, "BOS", "KBOS")  # IATA
    term.wait_for(lambda s: stations_listed(s) == 2 and detail_station(s) == "KBOS", 10, "KBOS added by its IATA code")
    add(term, "heathrow", "EGLL")  # name
    term.wait_for(lambda s: stations_listed(s) == 3 and detail_station(s) == "EGLL", 10, "EGLL added by name")
    add(term, "KJFK", "KJFK")  # ICAO
    term.wait_for(lambda s: stations_listed(s) == 4 and detail_station(s) == "KJFK", 10, "KJFK added by its ICAO code")

    add(term, "KDEN", "KDEN")  # duplicate: stated, not added
    screen = term.wait_for(lambda s: "already in the list" in bottom(s), 10, "the duplicate message")
    assert stations_listed(screen) == 4 and "KDEN is already in the list" in bottom(screen)

    add(term, "KXYZ", None)  # unknown code: stated, nothing added
    screen = term.wait_for(lambda s: "Unknown station KXYZ" in bottom(s), 10, "the unknown-station message")
    assert stations_listed(screen) == 4
    term.send_keys("escape")
    term.wait_for(lambda s: "Add station" not in s, 10, "the dialog closed")

    add(term, "zzzz9", None)  # garbage: stated, dialog stays open for another try
    screen = term.wait_for(lambda s: "Type a station code or part of a name" in bottom(s), 10, "the garbage message")
    assert stations_listed(screen) == 4 and "Add station" in screen
    term.send_keys("escape")
    quit_cleanly(term)
    assert saved_stations(tmp_path / "config.toml") == ["KDEN", "KBOS", "EGLL", "KJFK"]


# -- J5 ---------------------------------------------------------------------------------------------------------------


def test_J5_remove_the_last_one_a_middle_one_then_all_of_them(session: Session) -> None:
    term = session.start(120, 30, ["--demo"])
    term.send_keys("end")
    term.wait_for(lambda s: position(s) == (10, 10), 10, "the last station selected")
    term.send_keys("d")  # the last one: the one before it is selected
    screen = term.wait_for(lambda s: stations_listed(s) == 9, 10, "NZSP removed")
    assert position(screen) == (9, 9) and detail_station(screen) == "CYYZ", screen.text
    assert "NZSP" not in chr(10).join(screen.lines[:-3]), "NZSP is still listed"  # the toast below names it

    term.send_keys("home", "j", "j")  # a middle one: its neighbour takes the selection
    term.wait_for(lambda s: detail_station(s) == "ETHB", 10, "ETHB selected")
    term.send_keys("d")
    screen = term.wait_for(lambda s: stations_listed(s) == 8, 10, "ETHB removed")
    assert position(screen) == (3, 8) and detail_station(screen) == "UUEE", screen.text

    for _ in range(8):
        term.send_keys("d")
        term.settle(0.3)
    screen = term.wait_for(lambda s: stations_listed(s) == 0, 10, "all stations removed")
    assert EMPTY in screen
    assert detail_station(screen) is None, f"a stale detail pane stays after the last removal:\n{screen.text}"
    assert position(screen) is None
    term.send_keys("d", "j", "enter", "3", "1")  # nothing to act on: inert, not a crash
    calm(term)
    assert term.alive() and EMPTY in term.screen()
    term.send_keys("a", "EGLL")
    term.wait_for(lambda s: "EGLL" in s.text.split("Add station")[-1], 10, "EGLL among the results")
    term.send_keys("enter")
    term.wait_for(lambda s: stations_listed(s) == 1 and detail_station(s) == "EGLL", 10, "a station added after the list was empty")


# -- J6 ---------------------------------------------------------------------------------------------------------------


def test_J6_list_and_grid_keep_the_selection_clicks_select_and_enter_opens(session: Session) -> None:
    term = session.start(160, 40, ["--demo"])
    term.send_keys("j", "j")
    term.wait_for(lambda s: position(s) == (3, 10), 10, "ETHB selected")
    term.send_keys("v")
    grid = term.wait_for(lambda s: "┏" in s.text and position(s) == (3, 10), 10, "the grid with ETHB's card selected")
    assert "d Remove" in footer(grid)
    term.settle()
    term.click(*row_of(term.screen(), "RJTT", left_of=200))  # the pointer moves in first, then the click
    term.wait_for(lambda s: position(s) == (6, 10), 10, "RJTT selected by the click in the grid")
    assert "d Remove" in footer(calm(term)) and "esc Back" not in footer(term.screen()), "a click must not take focus off the list"
    term.send_keys("enter")
    inside = term.wait_for(lambda s: "esc Back" in footer(s), 10, "the detail footer from the grid")
    assert "RJTT" in inside.text
    term.send_keys("escape")
    term.wait_for(lambda s: "d Remove" in footer(s), 10, "the list footer again")
    term.settle(0.3)
    term.send_keys("v")  # back to the list: the same station is selected
    term.wait_for(lambda s: "┏" not in s.text and position(s) == (6, 10) and detail_station(s) == "RJTT", 10, "the list with RJTT selected")
    term.click(*row_of(term.screen(), "VIDP"))
    term.wait_for(lambda s: position(s) == (7, 10), 10, "VIDP selected by a click in the list")
    assert "d Remove" in footer(calm(term)), "a single click opened the detail pane"
    term.click(*row_of(term.screen(), "SBGR"))
    term.click(*row_of(term.screen(), "SBGR"))  # a second click on the same row opens it
    term.wait_for(lambda s: "esc Back" in footer(s) and detail_station(s) == "SBGR", 10, "SBGR opened by the double click")
    term.send_keys("escape")
    term.wait_for(lambda s: "d Remove" in footer(s), 10, "the list footer after Esc")
    quit_cleanly(term)


# -- J7 ---------------------------------------------------------------------------------------------------------------


def silent_presses(term, size_note: str) -> list[str]:
    silent = []
    for key in ("3", "2", "1"):
        before = styled_rows(term)
        term.send_keys(key)
        screen = calm(term)
        if not changed_rows(before, styled_rows(term)) and not re.search(r"\b(no (TAF|METAR)|No report)", bottom(screen)):
            silent.append(key)
    return silent


@pytest.mark.parametrize("focus", ["list", "detail", "after_click"])
def test_J7_keys_1_2_3_on_every_demo_station_never_do_nothing_silently(session: Session, focus: str) -> None:
    """Every one of the ten demo stations, 120x30 (the detail pane scrolls): 3, 2, 1 each change what is visible or say why."""
    term = session.start(120, 30, ["--demo"])
    failures: list[str] = []
    for index, station in enumerate(DEMO_STATIONS):
        if focus == "after_click":
            term.click(*row_of(term.screen(), station))
        else:
            if focus == "detail" and index:
                term.send_keys("escape")
                term.settle(0.3)
            if index:
                term.send_keys("j")
            if focus == "detail":
                term.send_keys("enter")
                term.wait_for(lambda s: "esc Back" in footer(s), 10, "focus in the detail pane")
        term.wait_for(lambda s, st=station: detail_station(s) == st, 10, f"{station} selected")
        term.send_keys("1")  # back to the top, so 3 has somewhere to go
        calm(term, 0.3)
        silent = silent_presses(term, focus)
        if silent:
            failures.append(f"{station}: {silent}")
    assert not failures, f"silent key presses ({focus} focus): {failures}"


@pytest.mark.xfail(strict=True, reason="#245: keys 1 and 2 give no visible change when all detail sections fit on screen")
def test_J7b_keys_1_2_3_when_all_sections_fit_on_screen(session: Session) -> None:
    term = session.start(280, 70, ["--demo", "--layout", "list"])
    for index in range(3):  # three stations whose three sections fit one screen
        if index:
            term.send_keys("j")
            calm(term)
        assert not detail_overflows(term), f"precondition: the detail pane must not scroll:\n{term.screen_text()}"
        assert not silent_presses(term, "280x70"), f"{detail_station(term.screen())}: a key press did nothing"


# -- J8 ---------------------------------------------------------------------------------------------------------------

METAR = "METAR KDEN 131453Z 06007KT 3/4SM BR OVC003 09/08 A3001 RMK AO2 SFC"
TAF = "TAF KDEN 131130Z 1312/1418 06008KT P6SM SCT050 FM131800 18010KT P6SM BKN100"


def test_J8_paste_decodes_a_metar_and_a_taf_and_says_so_for_junk(session: Session) -> None:
    term = session.start(120, 40, ["--demo"])
    term.send_keys("p")
    term.wait_for(lambda s: "Paste a METAR or TAF" in s, 10, "the paste screen")
    term.send_raw(f"\x1b[200~{METAR}\n{TAF}\x1b[201~")  # one bracketed paste, two reports
    screen = term.wait_for(lambda s: "Flight category" in s, 10, "the decoded report")
    text = screen.text
    assert re.search(r"Station\s+KDEN", text) and re.search(r"Flight category\s+LIFR", text)
    assert re.search(r"Wind\s+From 060° \(ENE\) at 7 kt", text)
    assert re.search(r"Sky\s+Overcast at 300 ft", text)
    assert re.search(r"Visibility\s+3/4 SM", text)
    term.send_raw(F2)  # copy the Discord block: the clipboard is not readable everywhere, so the toast is the check
    after = term.wait_for(lambda s: re.search(r"[Cc]opied|[Cc]ould not copy|clipboard", bottom(s)) is not None, 10, "a copy message")
    assert "KDEN" in after.text
    term.send_keys("escape")
    term.wait_for(lambda s: "Paste a METAR" not in s and stations_listed(s) == 10, 10, "back on the list")

    term.send_keys("p")
    term.wait_for(lambda s: "Paste a METAR or TAF" in s, 10, "the paste screen again")
    term.send_raw("\x1b[200~blorp this is not a report\x1b[201~")
    junk = calm(term, 0.8)
    assert not re.search(r"Flight category", junk.text), "junk was decoded as a report"
    assert re.search(r"(?i)no (metar|report|taf)|not (a )?(metar|report)|nothing|could not|can't|unrecognis|unrecogniz", junk.text), (
        f"junk pasted and nothing said about it:\n{junk.text}"
    )


# -- J9 ---------------------------------------------------------------------------------------------------------------


def test_J9_look_and_feel_changes_persist_and_survive_a_relaunch(session: Session, tmp_path: Path) -> None:
    seed_config(["KDEN"])(tmp_path)
    config = tmp_path / "config.toml"
    term = session.start(120, 30, root=tmp_path)
    start = saved_config(config).get("view", {})
    assert start == {}, f"precondition: a seeded config has no [view]: {start}"
    for key, field in (("u", "units"), ("g", "glyph_set"), ("z", "time"), ("t", "theme")):
        rows = styled_rows(term)
        term.send_keys(key)
        calm(term)
        if key != "z":  # with no report on screen the time mode shows nowhere but in the settings screen (checked below)
            assert changed_rows(rows, styled_rows(term)), f"key {key} changed nothing visible"
        assert field in saved_config(config).get("view", {}), f"key {key} did not save {field}"
    chosen = saved_config(config)["view"]
    assert chosen["units"] == "us" and chosen["glyph_set"] == "ascii" and chosen["time"] == "local"

    term.send_keys("S")  # the language row is highlighted first: Enter changes it
    term.wait_for(lambda s: "Enter changes the value" in s or "Enter" in s, 10, "the settings screen")
    shown = term.screen().text
    assert "ASCII" in shown and "US (kt, SM, inHg)" in shown and "This computer's time" in shown
    term.send_keys("enter")
    calm(term)
    assert saved_config(config)["view"]["lang"] != "en", "the language did not change"
    term.send_keys("escape")
    bar = footer(calm(term))
    assert "Añadir" in bar or "Add" not in bar, bar
    quit_cleanly(term)

    again = session.start(120, 30, root=tmp_path, ready=None)
    again.wait_for(lambda s: footer(s) == bar, 45, "the key bar in the saved language")
    assert saved_config(config)["view"] == {**chosen, "lang": saved_config(config)["view"]["lang"]}
    again.send_keys("S")
    again.wait_for(lambda s: "ASCII" in s, 10, "the saved glyph set in the settings screen")
    for _ in range(6):  # restored by S: step the language round to English again
        if saved_config(config)["view"]["lang"] == "en":
            break
        again.send_keys("enter")
        calm(again, 0.4)
    assert saved_config(config)["view"]["lang"] == "en"


# -- J10 --------------------------------------------------------------------------------------------------------------

FLAGS = ["--theme", "paper-chart", "--glyphs", "ascii", "--units", "metric", "--time", "zulu", "--lang", "de", "--layout", "grid"]


def test_J10_per_run_flags_apply_to_this_run_and_are_never_saved(session: Session, tmp_path: Path) -> None:
    seed_config(["KDEN"], "[view]\ntheme = \"textual-dark\"\nunits = \"us\"\nlang = \"en\"\nlayout = \"list\"\n")(tmp_path)
    config = tmp_path / "config.toml"
    before = config.read_bytes()
    term = session.start(120, 30, FLAGS, root=tmp_path, ready="Stationen")
    screen = term.screen()
    assert "╭" in screen.text or "┏" in screen.text, "--layout grid did not draw cards"
    assert "Hinzufügen" in footer(screen), "--lang de did not translate the key bar"
    term.send_keys("S")
    shown = term.wait_for(lambda s: "Einstellungen" in s, 10, "the settings screen").text
    assert "Metrisch" in shown and "UTC (Zulu)" in shown and "ASCII" in shown
    term.send_keys("escape")
    term.settle()
    assert config.read_bytes() == before, "a flag was written to the config"
    # A change made in the app during a flagged run saves THAT change only, not the flags of this run.
    term.send_keys("g")  # a change made in the app saves that change, not the flags of this run
    calm(term)
    quit_cleanly(term)
    after = saved_config(config)["view"]
    assert (after["theme"], after["units"], after["lang"]) == ("textual-dark", "us", "en"), f"a flag leaked into the config: {after}"


def test_J10_no_config_reads_and_writes_nothing(session: Session, tmp_path: Path) -> None:
    seed_config(["KSFO"])(tmp_path)
    before = (tmp_path / "config.toml").read_bytes()
    term = session.start(120, 30, ["--no-config", "--demo"], config=False, root=tmp_path)
    for key in ("u", "g", "z", "t"):
        term.send_keys(key)
        term.settle(0.3)
    quit_cleanly(term)
    assert (tmp_path / "config.toml").read_bytes() == before
    fresh = tmp_path / "none"
    other = session.start(120, 30, ["--no-config", "KDEN"], config=False, env={"WXBRIEF_CACHE_DIR": str(fresh / "cache")})
    other.send_keys("u", "a")
    other.settle(0.3)
    other.send_keys("escape")
    quit_cleanly(other)
    assert not fresh.joinpath("config.toml").exists()


# -- J16 --------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "layout",
    [pytest.param("list", marks=pytest.mark.xfail(strict=True, reason="#255: key bar stays the detail pane's after a shrink and back")),
        pytest.param("grid", marks=pytest.mark.xfail(strict=False, reason="#259: intermittent, stale grid and wrapped key bar after a resize storm")),
    ],
)
def test_J16_resize_storm_keeps_the_selection_and_the_key_bar(session: Session, layout: str) -> None:
    term = session.start(120, 30, ["--demo", "--layout", layout])
    term.send_keys("j", "j", "j")
    term.wait_for(lambda s: position(s) == (4, 10), 10, "UUEE selected")
    rng = random.Random(20261101)
    for _ in range(50):
        term.resize(rng.randint(60, 200), rng.randint(16, 50))
        term.hold(0.04)
    term.resize(120, 30)
    screen = term.wait_for(lambda s: position(s) == (4, 10) and len(s.lines) == 30, 15, "the selection after the storm")
    screen = term.settle(0.6)
    assert term.alive() and "Traceback" not in screen.text
    assert "larger" not in screen.text.lower(), f"stuck on the too-small screen:\n{screen.text}"
    assert "d Remove" in footer(screen) and "esc Back" not in footer(screen), f"key bar after the storm: {footer(screen)}" + chr(10) + screen.text
    assert position(screen) == (4, 10)
    term.resize(40, 10)  # below the minimum: a message, not a crash
    small = term.wait_for(lambda s: "larger" in s.text.lower() or "too small" in s.text.lower(), 10, "the too-small message")
    assert small
    term.resize(120, 30)
    back = term.wait_for(lambda s: position(s) == (4, 10), 10, "the list again")
    assert "d Remove" in footer(back)
    quit_cleanly(term)


# -- J18 --------------------------------------------------------------------------------------------------------------


def test_J18_ctrl_q_quits_and_ctrl_c_says_how(session: Session) -> None:
    term = session.start(120, 30, ["--demo"])
    term.send_raw("\x03")
    term.wait_for(lambda s: "ctrl+q" in bottom(s).lower(), 10, "a hint that says how to quit")
    assert term.alive()
    term.send_raw(CTRL_Q)
    assert term.wait_exit(15) == 0, term.screen_text()


@pytest.mark.xfail(strict=True, reason="#258: the Ctrl-C hint shows its markup tags literally")
def test_J18_ctrl_c_hint_is_plain_text(session: Session) -> None:
    term = session.start(120, 30, ["--demo"])
    term.send_raw("\x03")
    hint = term.wait_for(lambda s: "ctrl+q" in bottom(s).lower(), 10, "a hint that says how to quit")
    assert "[b]" not in bottom(hint) and "[/b]" not in bottom(hint), f"the hint shows raw markup: {bottom(hint)}"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
@pytest.mark.parametrize("sig", ["SIGTERM", "SIGHUP"])
def test_J18_signals_end_the_program_and_restore_the_terminal(session: Session, sig: str) -> None:
    import os
    import signal

    term = session.start(120, 30, ["--demo"])
    pid = term.pid
    assert pid
    os.kill(pid, getattr(signal, sig))
    code = term.wait_exit(15)
    assert code is not None, f"{sig} did not end the program:\n{term.screen_text()}"
    state = term.state()
    assert state.mouse_mode == "none", f"mouse tracking left on after {sig}"
    assert not state.modes.get("bracketed_paste"), f"bracketed paste left on after {sig}"


def test_J18_kill_9_then_relaunch_recovers_the_config_and_the_cache(session: Session, tmp_path: Path) -> None:
    seed_config(["KDEN", "EGLL"])(tmp_path)
    term = session.start(120, 30, root=tmp_path)
    term.send_keys("a", "KJFK")
    term.wait_for(lambda s: "KJFK" in s.text.split("Add station")[-1], 10, "KJFK among the results")
    term.send_keys("enter")
    term.wait_for(lambda s: stations_listed(s) == 3, 10, "KJFK added")
    term.kill()  # no chance to clean up
    assert saved_stations(tmp_path / "config.toml") == ["KDEN", "EGLL", "KJFK"], "the added station was not on disk at once"
    again = session.start(120, 30, root=tmp_path)
    screen = again.screen()
    assert stations_listed(screen) == 3 and "Traceback" not in screen.text
    quit_cleanly(again)


# -- J19 --------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "expect"),
    [
        ("a Add", lambda s: "Add station" in s),
        ("? Help", lambda s: "wxbrief keys" in s),
        ("p Paste", lambda s: "Paste a METAR or TAF" in s),
        ("v List/grid", lambda s: "╭" in s.text or "┏" in s.text),
        ("d Remove", lambda s: stations_listed(s) == 9),
        ("r Refresh", lambda s: re.search(REFRESH_IN_DEMO, bottom(s)) is not None),
    ],
    ids=["add", "help", "paste", "grid", "remove", "refresh"],
)
def test_J19_every_key_bar_label_works_with_the_mouse_alone(session: Session, label: str, expect) -> None:
    term = session.start(120, 30, ["--demo"])
    term.click_text(label)
    term.wait_for(expect, 10, f"the effect of clicking {label!r}")


def test_J19_clicking_quit_in_the_key_bar_quits(session: Session) -> None:
    term = session.start(120, 30, ["--demo"])
    term.click_text("q Quit")
    assert term.wait_exit(15) == 0, term.screen_text()


# -- J20 / J21 --------------------------------------------------------------------------------------------------------

FIXTURES = Path(__file__).parent / "fixtures" / "upgrade-0.3.0"


def test_J20_a_config_and_cache_written_by_0_3_0_are_honoured(session: Session, tmp_path: Path) -> None:
    """The files in fixtures/upgrade-0.3.0 were written by the 0.3.0 release (see its README line in JOURNEYS.md)."""
    shutil.copytree(FIXTURES, tmp_path, dirs_exist_ok=True)
    wanted = saved_config(tmp_path / "config.toml")
    term = session.start(120, 30, root=tmp_path)
    screen = term.screen()
    assert "Traceback" not in screen.text and stations_listed(screen) == len(wanted["stations"]["watchlist"]), screen.text
    for station in wanted["stations"]["watchlist"]:
        assert station in screen, f"{station} of the 0.3.0 config is not shown"
    assert (detail_station(screen) or "") in wanted["stations"]["watchlist"]
    view = wanted.get("view", {})
    if view.get("layout") == "grid":
        assert "╭" in screen.text or "┏" in screen.text
    term.send_keys("S")
    shown = term.wait_for(lambda s: ("Enter" in s and "Units" in s) or "Einheiten" in s, 10, "settings").text
    expected = {"ascii": "ASCII", "nerd": "Nerd Font", "unicode": "Unicode"}
    if view.get("glyph_set") in expected:
        assert expected[view["glyph_set"]] in shown
    term.send_keys("escape")
    quit_cleanly(term)
    after = saved_config(tmp_path / "config.toml")
    assert after["stations"] == wanted["stations"], "the candidate rewrote the 0.3.0 station list"


def test_J21_nothing_is_left_behind_outside_the_two_folders_and_removing_them_resets_the_app(
    session: Session, tmp_path: Path
) -> None:
    root = tmp_path / "wx"
    root.mkdir()
    seed_config(["KDEN"])(root)
    term = session.start(120, 30, root=root)
    term.send_keys("v", "u")
    term.settle(0.4)
    quit_cleanly(term)
    names = sorted(p.name for p in root.iterdir())
    assert set(names) <= {"config.toml", "config.toml.bak", "cache"}, f"files outside config.toml, its backup and cache/: {names}"
    assert not [p for p in root.rglob("*") if p.name.endswith((".tmp", ".lock"))], "temp or lock files left after exit"
    shutil.rmtree(root)
    root.mkdir()
    fresh = session.start(120, 30, root=root)
    assert EMPTY in fresh.screen() and not fresh.screen().text.count("KDEN")


# -- J23 --------------------------------------------------------------------------------------------------------------


def corrupt_cache(directory: Path) -> None:
    seed_config(["KDEN"])(directory)
    for source in (FIXTURES / "cache").glob("*"):
        (directory / "cache").mkdir(exist_ok=True)
        (directory / "cache" / source.name).write_bytes(b"\x00\xff not json {{{" * 50)


LOCAL_FAULTS = {
    "config_is_garbage": lambda d: (d / "config.toml").write_text("[stations\nwatchlist = ", encoding="utf-8"),
    "config_is_binary": lambda d: (d / "config.toml").write_bytes(bytes(range(256)) * 4),
    "config_is_empty": lambda d: (d / "config.toml").write_bytes(b""),
    "config_is_a_directory": lambda d: (d / "config.toml").mkdir(),
    "cache_is_a_file": lambda d: (seed_config(["KDEN"])(d), (d / "cache").write_text("x", encoding="utf-8")),
    "cache_files_are_corrupt": corrupt_cache,
}


@pytest.mark.parametrize("fault", list(LOCAL_FAULTS))
def test_J23_a_broken_local_environment_starts_the_app_and_never_shows_a_traceback(session: Session, fault: str) -> None:
    term = session.start(120, 30, prepare=LOCAL_FAULTS[fault], ready=None)
    term.wait_for(lambda s: "Stations" in s, 30, "the app despite the fault")
    screen = calm(term, 1.0)
    assert "Traceback" not in screen.text and "Error" not in screen.text.replace("Errors", ""), screen.text
    term.send_keys("a")
    term.wait_for(lambda s: "Add station" in s, 10, "the add dialog still works")
    term.send_keys("escape")
    quit_cleanly(term)


def test_J23_a_corrupt_config_is_said_out_loud(session: Session) -> None:
    term = session.start(120, 30, prepare=LOCAL_FAULTS["config_is_garbage"], ready=None)
    screen = term.wait_for(lambda s: "config" in s.text.lower() and "Stations" in s, 30, "a message about the config")
    assert "using" in screen.text.lower() or "default" in screen.text.lower(), screen.text


# -- J24 --------------------------------------------------------------------------------------------------------------

DEGRADED = {
    "no_color": ({"NO_COLOR": "1"}, []),
    "dumb_terminal": ({"TERM": "dumb"}, []),
    "ascii_glyphs": ({}, ["--glyphs", "ascii"]),
    "linux_console": ({"TERM": "linux", "COLORTERM": ""}, []),
}


@pytest.mark.parametrize("name", list(DEGRADED))
def test_J24_the_first_run_and_the_section_keys_work_when_the_terminal_is_poor(session: Session, name: str) -> None:
    env, flags = DEGRADED[name]
    term = session.start(100, 28, ["--demo", *flags], env=env)
    assert stations_listed(term.screen()) == 10
    term.send_keys("j")
    term.wait_for(lambda s: position(s) == (2, 10) and detail_station(s) == "EGLL", 10, "EGLL selected")
    assert not silent_presses(term, name), "a section key did nothing"
    term.send_keys("a")
    term.wait_for(lambda s: "Add station" in s, 10, "the add dialog")
    term.send_keys("escape")
    quit_cleanly(term)
