"""The UAT journeys. Each one drives the real app key by key and asserts what a person would see.

A journey takes a ``Run`` (see harness.py) and adapts its expectations to the terminal size where the design differs:
below 90 columns the station list gives way to the detail pane. ``JOURNEYS`` says at which sizes each one runs.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

from harness import COMMON, SMALL, Journey, Run, toasts
from rich.console import Console
from textual.widgets import Input, OptionList, Static, TextArea

from wxbrief.data.demo import DEMO_ORDER
from wxbrief.i18n import Translator
from wxbrief.i18n.keys import K
from wxbrief.ui.screens.add_station import AddStationScreen
from wxbrief.ui.screens.help import HelpScreen
from wxbrief.ui.screens.paste import PasteDecodeScreen
from wxbrief.ui.screens.settings import SettingsScreen
from wxbrief.ui.screens.station_detail import StationDetailScreen
from wxbrief.ui.screens.theme_picker import ThemePickerScreen
from wxbrief.ui.themes import THEME_CYCLE
from wxbrief.ui.widgets.detail import DecodedTable, DetailPane, StationHeader
from wxbrief.ui.widgets.station_card import StationCard
from wxbrief.ui.widgets.station_grid import StationGrid
from wxbrief.ui.widgets.station_list import StationList
from wxbrief.ui.widgets.taf_timeline import TafTimeline

WIND = re.compile(r"\b(?:VRB|\d{3})\d{2}(?:G\d{2,3})?(?:KT|MPS)\b")
def _plain(widget: Static) -> str:
    """The text a widget draws, from its own renderable (not from the screen, where the typed text also shows)."""
    console = Console(width=100, record=True, file=io.StringIO())
    console.print(widget.content)
    return console.export_text()


PASTED = "KDEN 311153Z 32005KT 1/4SM FG VV001 07/07 A3001"


def plain(widget: object) -> str:
    from rich.text import Text

    content = widget.render()  # type: ignore[attr-defined]
    return content.plain if isinstance(content, Text) else str(content)


def header_text(run: Run) -> str:
    return plain(run.app.screen.query_one(StationHeader))


def themes(run: Run) -> list[str]:
    return [name for name in THEME_CYCLE if name in run.app.available_themes]


def footer_line(run: Run) -> str:
    from harness import screen_lines

    return screen_lines(run.app)[-1]


# --- the briefing --------------------------------------------------------------------------------------------------


async def briefing_list(run: Run) -> None:
    """First look: the first station is read, the list (when it fits) shows all ten, j and k move through them."""
    screen = run.briefing
    assert screen.layout_mode == "list" and screen.selected == "KDEN"
    assert "KDEN" in header_text(run) and "Denver" in header_text(run)
    text = run.text()
    assert "Raw" in text and "METAR KDEN" in text  # the report itself is on screen
    stations = screen.query_one(StationList)
    if run.wide:
        assert stations.display and "Stations (10)" in text
        for icao in DEMO_ORDER:
            assert icao in text, f"{icao} is missing from the list"
        assert run.app.focused is stations
        assert stations.highlighted == 0
    else:
        assert not stations.display  # the detail takes the whole width
        assert isinstance(run.app.focused, DetailPane)
    await run.shot("start")
    await run.press("j")
    await run.until(lambda: screen.selected == "EGLL" and "EGLL" in header_text(run), "EGLL selected and in the header")
    assert "KDEN" not in header_text(run)
    if run.wide:
        assert stations.highlighted == 1
    await run.press("k", "k")  # wraps to the last station
    await run.until(lambda: screen.selected == "NZSP" and "NZSP" in header_text(run), "NZSP selected and in the header")
    await run.press("j")
    await run.until(lambda: screen.selected == "KDEN", "KDEN selected again")
    await run.shot("walked")


async def sections(run: Run) -> None:
    """1, 2 and 3 jump to the raw report, the decoded table and the forecast; 3 hands the keys to the timeline."""
    screen = run.briefing
    pane = screen.query_one(DetailPane)
    await run.press("2")
    table = screen.query_one(DecodedTable)
    top = pane.region.y

    def decoded_in_view() -> bool:
        return table.row_count > 5 and top <= screen.query_one("#decoded-title").region.y < pane.region.bottom

    await run.until(decoded_in_view, "the decoded table scrolled into the pane")
    assert "Decoded" in run.text()
    await run.shot("decoded")
    await run.press("3")
    timeline = screen.query_one(TafTimeline)
    await run.until(
        lambda: timeline.has_focus and top <= screen.query_one("#taf-title").region.y < pane.region.bottom,
        "the forecast focused and scrolled into the pane",
    )
    assert "TAF" in run.text()
    await run.shot("taf")
    await run.press("right")
    await run.shot("taf-period")
    await run.press("1")
    await run.until(
        lambda: pane.scroll_y == 0 or top <= screen.query_one("#raw-title").region.y < pane.region.bottom,
        "the raw report scrolled into the pane",
    )
    assert "Raw" in run.text()


async def station_detail_from_list(run: Run) -> None:
    """Enter in the list moves into the detail pane, where 1 2 3 and the arrows read the report."""
    screen = run.briefing
    if run.wide:
        assert run.app.focused is screen.query_one(StationList)
        await run.press("enter")
        await run.until(lambda: isinstance(run.app.focused, DetailPane), "the detail pane focused")
    pane = screen.query_one(DetailPane)
    await run.press("down", "down")
    if pane.max_scroll_y:
        assert pane.scroll_y > 0, "the arrows do not scroll the report"
        await run.press("pageup")
        assert pane.scroll_y < pane.max_scroll_y, "page up does not scroll back"
    assert isinstance(run.app.focused, DetailPane)
    await run.press("3")
    await run.until(lambda: screen.query_one(TafTimeline).has_focus, "the timeline focused")
    await run.press("2")
    await run.press("escape")  # nothing to go back to: the briefing stays
    assert run.app.screen is screen


# --- the grid ------------------------------------------------------------------------------------------------------


async def grid(run: Run) -> None:
    """v shows a card per station with real report data; the arrows walk the cards; v goes back."""
    screen = run.briefing
    await run.press("v")
    view = screen.query_one(StationGrid)
    await run.until(
        lambda: screen.layout_mode == "grid"
        and run.app.focused is view
        and [c.icao for c in screen.query(StationCard)] == list(DEMO_ORDER),
        "the grid shown with a card per station and the focus on it",
    )
    cards = list(screen.query(StationCard))
    assert view.columns == max(1, view.size.width // 38)
    assert not screen.query_one(StationList).display and not screen.query_one(DetailPane).display
    assert "Stations (10)" in run.text()
    selected = [c.icao for c in cards if c.has_class("-selected")]
    assert selected == ["KDEN"]
    for card in cards:
        entry = next(r for r in run.app.state.reports() if r.icao == card.icao)
        assert entry.metar is not None
        wind = WIND.search(entry.metar.raw)
        assert wind is not None
        body = plain(card)
        assert card.icao in body and wind.group(0) in body, f"{card.icao} card lacks its code or wind"
    await run.shot("start")
    # the cards are laid out in rows of view.columns: right/left walk along a row, down/up between rows
    columns = view.columns
    await run.press("right" if columns > 1 else "down")
    await run.until(lambda: screen.selected == "EGLL", "EGLL selected")
    await run.press("left" if columns > 1 else "up")
    await run.until(lambda: screen.selected == "KDEN", "KDEN selected")
    for _ in range(len(DEMO_ORDER) // columns + 1):
        await run.press("down")
    last = screen.selected
    assert last is not None and last != "KDEN"
    selected_card = next(c for c in cards if c.icao == last)
    # the selected card has been marked and scrolled into the grid's viewport (inside it, not merely clamped to it)
    await run.until(
        lambda: selected_card.has_class("-selected")
        and selected_card.region.height > 0
        and view.region.contains_region(selected_card.region),
        "the selected card marked and scrolled into view",
    )
    await run.shot("scrolled")
    await run.press("v")
    await run.until(
        lambda: screen.layout_mode == "list" and screen.selected == last and last in header_text(run),
        "the list layout back with the same station",
    )


async def grid_detail(run: Run) -> None:
    """Enter on a card opens that station's own screen: header first, 1 2 3 and c work, Esc returns to the same card."""
    screen = run.briefing
    await run.press("v", "j")
    await run.until(lambda: screen.layout_mode == "grid" and screen.selected == "EGLL", "EGLL selected in the grid")
    await run.press("enter")
    await run.until(lambda: isinstance(run.app.screen, StationDetailScreen), "the station screen")
    detail = run.app.screen
    pane = detail.query_one(DetailPane)
    assert pane.scroll_y == 0
    assert "EGLL" in plain(detail.query_one(StationHeader)) and "London" in plain(detail.query_one(StationHeader))
    assert run.app.focused is pane
    assert "METAR EGLL" in run.text()
    await run.shot("top")
    await run.press("3")
    await run.until(lambda: detail.query_one(TafTimeline).has_focus, "the timeline focused")
    await run.shot("taf")
    await run.press("2")
    await run.shot("decoded")
    await run.press("1")
    await run.press("c")
    await run.until(lambda: bool(run.copied), "the copy")
    assert "EGLL" in run.copied[-1] and run.copied[-1].startswith("```")
    await run.press("escape")
    await run.until(
        lambda: run.app.screen is screen and run.app.focused is screen.query_one(StationGrid),
        "the grid focused again",
    )
    assert screen.layout_mode == "grid" and screen.selected == "EGLL"
    # open another one with the keys alone
    await run.press("j", "enter")
    await run.until(lambda: isinstance(run.app.screen, StationDetailScreen), "the second station screen")
    assert "ETHB" in plain(run.app.screen.query_one(StationHeader))
    await run.press("escape")
    await run.until(lambda: run.app.screen is screen, "the briefing")


# --- dialogs and screens -------------------------------------------------------------------------------------------


async def paste(run: Run) -> None:
    """p opens the paste screen; typing a report decodes it as you type; c copies the Discord text; Esc leaves."""
    await run.press("p")
    await run.until(lambda: isinstance(run.app.screen, PasteDecodeScreen), "the paste screen")
    area = run.app.screen.query_one(TextArea)
    await run.until(lambda: run.app.focused is area, "the box focused")
    assert "Paste" in run.text() or "paste" in run.text()
    await run.shot("empty")
    for char in "METAR " + PASTED:
        await run.pilot.press("space" if char == " " else char)
    await run.until(lambda: bool(run.app.screen.decoded), "the decode of the typed report")  # type: ignore[attr-defined]
    result = run.app.screen.query_one("#paste-result")
    await run.until(lambda: "KDEN" in _plain(result), "the decode in the output pane")  # not the typed text
    assert result.region.height > 0 and result.region.y < run.size[1], "the output pane is not on screen"
    if run.size[1] >= 20:
        await run.until(lambda: "Wind" in run.text(), "the decoded wind row")
    assert area.text == "METAR " + PASTED
    await run.shot("decoded")
    await run.press("f2")
    await run.until(lambda: bool(run.copied), "the copy")
    assert "KDEN" in run.copied[-1] and run.copied[-1].startswith("```")
    await run.press("escape")
    await run.until(lambda: run.app.screen is run.briefing, "the briefing")
    assert run.briefing.selected == "KDEN"


async def add_station(run: Run) -> None:
    """a opens the add dialog; an unknown code is refused; a real one is added, saved to the config, and removable."""
    screen = run.briefing
    await run.press("a")
    await run.until(lambda: isinstance(run.app.screen, AddStationScreen), "the add dialog")
    box = run.app.screen.query_one(Input)
    await run.until(lambda: run.app.focused is box, "the input focused")
    await run.shot("empty")
    for char in "zzzz":
        await run.pilot.press(char)
    await run.press("enter")
    assert isinstance(run.app.screen, AddStationScreen)  # refused: still open
    assert not run.saved()
    await run.press("ctrl+e", "ctrl+u")
    for char in "ksea":
        await run.pilot.press(char)
    results = run.app.screen.query_one("#results", OptionList)
    await run.until(lambda: results.option_count > 0, "the matches for ksea")
    assert "KSEA" in run.text() and "Seattle" in run.text()
    await run.shot("matches")
    await run.press("enter")
    await run.until(lambda: run.app.screen is screen, "the briefing after adding")
    assert "KSEA" in run.app.state.ids and len(run.app.state.ids) == 11
    assert screen.selected == "KSEA"
    assert run.saved()["stations"]["watchlist"][-1] == "KSEA"
    assert "KSEA" in header_text(run)
    if run.wide:
        assert "KSEA" in run.text() and "Stations (11)" in run.text()
    await run.shot("added")
    await run.press("d")
    await run.until(lambda: "KSEA" not in run.app.state.ids and screen.selected != "KSEA", "KSEA removed")
    await run.until(lambda: "KSEA" not in run.saved()["stations"]["watchlist"], "KSEA removed from the saved list")
    assert screen.selected == "KDEN"  # KSEA was the first row, so the row that took its place
    screen.select("ETHB")  # a row in the middle: the selection and the list highlight move to the row that closes the gap
    await run.settle()
    await run.press("d")
    await run.until(lambda: "ETHB" not in run.app.state.ids, "ETHB removed")
    ids = run.app.state.ids
    assert ids.index("UUEE") == 2 and screen.selected == "UUEE", screen.selected  # not KDEN, so a second d is safe
    if run.wide:
        assert screen.query_one(StationList).highlighted == 2


async def help_screen(run: Run) -> None:
    """? opens the key help (all of it reachable by scrolling), ? or Esc closes it."""
    await run.press("question_mark")
    await run.until(lambda: isinstance(run.app.screen, HelpScreen), "the help screen")
    t = Translator.load("en")
    body = [" ".join(re.sub(r"\[/?b\]", "", line).split()) for line in t.t(K.UI_HELP_BODY).splitlines() if line.strip()]
    box = run.app.screen.query_one("#help-box")
    assert t.t(K.UI_HELP_TITLE) in run.text()
    assert body[0].split()[0] in run.text()
    await run.shot("top")
    await run.press("end")
    await run.settle()
    assert box.scroll_y == box.max_scroll_y, "the help does not scroll to its end"
    assert body[-1].split()[-1] in run.text(), "the last help line is not on screen at the end"
    await run.shot("end")
    await run.press("escape")
    await run.until(lambda: run.app.screen is run.briefing, "the briefing")
    await run.press("question_mark", "question_mark")
    await run.until(lambda: run.app.screen is run.briefing, "the briefing after opening and closing the help")


async def theme_cycle(run: Run) -> None:
    """t visits every registered theme and comes back; the briefing stays readable in each."""
    names = themes(run)
    assert len(names) >= 10
    start = run.app.theme
    assert start in names
    seen = [start]
    for i in range(len(names)):
        await run.press("t")
        expected = names[(names.index(start) + i + 1) % len(names)]
        await run.until(lambda expected=expected: run.app.theme == expected, f"the theme {expected}")
        seen.append(run.app.theme)
        text = run.text()
        assert "KDEN" in text and "Raw" in text, f"theme {expected} lost the report"
        assert footer_line(run).strip()
        if i in (1, len(names) // 2):
            await run.shot(f"theme-{expected}")
    assert run.app.theme == start and len(set(seen)) == len(names)


async def theme_picker(run: Run) -> None:
    """T previews a theme as you move, Esc puts the old one back (nothing saved), Enter keeps and saves one."""
    app = run.app
    names = themes(run)
    start = app.theme
    await run.press("T")
    await run.until(lambda: isinstance(app.screen, ThemePickerScreen), "the theme picker")
    options = app.screen.query_one(OptionList)
    assert options.highlighted == names.index(start)
    for name in names[:4]:
        assert name in run.text() or run.size[1] < 20  # a short terminal scrolls the list
    await run.shot("open")
    await run.press("down")
    await run.until(lambda: app.theme == names[(names.index(start) + 1) % len(names)], "the previewed theme")
    await run.press("down")
    await run.shot("preview")
    await run.press("escape")
    await run.until(lambda: app.screen is run.briefing and app.theme == start, "the briefing in the old theme")
    assert "theme" not in run.saved().get("view", {})
    await run.press("T", "down", "down", "enter")
    kept = names[(names.index(start) + 2) % len(names)]
    await run.until(lambda: app.screen is run.briefing and app.theme == kept, "the briefing in the kept theme")
    await run.until(lambda: run.saved().get("view", {}).get("theme") == kept, "the saved theme")


async def settings(run: Run) -> None:
    """S: Enter cycles language (through de and back), units, time and glyphs; each is applied and saved."""
    app = run.app
    await run.press("S")
    await run.until(lambda: isinstance(app.screen, SettingsScreen), "the settings screen")
    box = app.screen.query_one(OptionList)
    await run.until(lambda: app.focused is box and box.highlighted == 0, "the first setting highlighted")
    assert "Language" in run.text()
    await run.shot("open")
    german = Translator.load("de")
    await run.until(lambda: app.screen.query_one(OptionList).option_count == 4, "the four settings")
    for _ in range(8):  # the language list is short; stop at German
        if app.ctx.translator.lang == "de":
            break
        await run.press("enter")
    assert app.ctx.translator.lang == "de"
    assert run.saved()["view"]["lang"] == "de"
    if run.size[0] >= 60:  # at 50 columns the value wraps out of view: see test_known_bugs
        assert german.language_name in run.text()
    await run.shot("german")
    await run.press("escape")
    await run.until(lambda: app.screen is run.briefing, "the briefing")
    assert german.t(K.UI_LIST_TITLE, n=10) in run.text() or not run.wide
    await run.press("S")
    for _ in range(8):  # back to English
        if app.ctx.translator.lang == "en":
            break
        await run.press("enter")
    assert app.ctx.translator.lang == "en" and run.saved()["view"]["lang"] == "en"
    units, glyphs, clock = app.ctx.units, app.ctx.glyphs, app.ctx.time_mode
    await run.press("down", "enter")
    assert app.ctx.units is not units and run.saved()["view"]["units"] == app.ctx.units.value
    await run.press("down", "enter")
    assert app.ctx.time_mode != clock and run.saved()["view"]["time"] == app.ctx.time_mode
    await run.press("down", "enter")
    assert app.ctx.glyphs != glyphs and run.saved()["view"]["glyph_set"] == app.glyph_set
    await run.shot("changed")
    await run.press("S")
    await run.until(lambda: app.screen is run.briefing, "the briefing")


async def copy_keys(run: Run) -> None:
    """c copies the METAR as a Discord block, C the METAR and TAF, y the raw reports; the station screen does the same."""
    screen = run.briefing
    entry = screen.current()
    assert entry is not None and entry.metar is not None and entry.taf is not None
    await run.press("c")
    await run.until(lambda: bool(run.copied), "the copy")
    assert run.copied[-1].startswith("```") and "KDEN" in run.copied[-1] and "TAF" not in run.copied[-1].split("\n")[0]
    await run.until(lambda: any("KDEN" in note and "Copied" in note for note in toasts(run.app)), "the copied toast")
    await run.shot("copied")
    await run.press("C")
    assert run.copied[-1].count("```") >= 4  # two blocks
    await run.press("y")
    assert run.copied[-1] == entry.metar.raw + "\n" + entry.taf.raw
    count = len(run.copied)
    await run.press("v", "enter")
    await run.until(lambda: isinstance(run.app.screen, StationDetailScreen), "the station screen")
    await run.press("y")
    assert run.copied[-1] == entry.metar.raw + "\n" + entry.taf.raw
    await run.press("C")
    assert len(run.copied) == count + 2
    await run.press("escape")


async def quit_app(run: Run) -> None:
    """q ends the program from the briefing; from a dialog Esc comes first."""
    await run.press("p")
    await run.until(lambda: isinstance(run.app.screen, PasteDecodeScreen), "the paste screen")
    await run.press("escape")
    await run.until(lambda: run.app.screen is run.briefing, "the briefing")
    assert run.app.is_running
    await run.pilot.press("q")
    await run.until(lambda: not run.app.is_running, "the app to exit")


# --- terminal sizes ------------------------------------------------------------------------------------------------


async def resize(run: Run) -> None:
    """Resize the live terminal through the sizes people use; layout switches, selection and focus survive."""
    app = run.app
    screen = run.briefing
    await run.press("j")
    await run.until(lambda: screen.selected == "EGLL", "EGLL selected")
    steps = [(120, 30), (100, 50), (200, 50), (80, 24), (60, 20), (280, 70), (120, 30)]
    for width, height in steps:
        await run.pilot.resize_terminal(width, height)
        await run.settle()
        await run.pilot.pause(0.05)
        await run.settle()
        name = f"{width}x{height}"
        assert app.size == (width, height)
        assert app.screen.has_class("-narrow") == (width < 90)
        assert app.screen.has_class("-wide") == (width >= 140)
        assert app.screen.has_class("-short") == (height < 24)
        assert screen.query_one(StationList).display == (width >= 90)
        assert screen.selected == "EGLL" and "EGLL" in header_text(run), f"selection lost at {name}"
        assert app.focused is not None and app.focused.display, f"focus lost at {name}"
        assert footer_line(run).strip(), f"footer blank at {name}"
        await run.shot(f"list-{name}")
    await run.press("v")
    await run.until(lambda: screen.layout_mode == "grid", "the grid layout")
    for width, height in [(200, 50), (80, 24), (120, 30)]:
        await run.pilot.resize_terminal(width, height)
        await run.settle()
        await run.pilot.pause(0.05)
        await run.settle()
        grid_view = screen.query_one(StationGrid)
        assert screen.layout_mode == "grid" and screen.selected == "EGLL"
        assert grid_view.columns == max(1, grid_view.size.width // 38)
        assert app.focused is grid_view
        await run.shot(f"grid-{width}x{height}")
    await run.press("enter")
    await run.until(lambda: isinstance(app.screen, StationDetailScreen), "the station screen")
    await run.pilot.resize_terminal(60, 20)
    await run.settle()
    assert "EGLL" in plain(app.screen.query_one(StationHeader))
    await run.pilot.resize_terminal(120, 30)
    await run.settle()
    await run.press("escape")
    await run.until(lambda: app.screen is screen, "the briefing")
    assert screen.selected == "EGLL"
    await run.press("S")
    await run.until(lambda: isinstance(app.screen, SettingsScreen), "the settings screen")
    await run.pilot.resize_terminal(60, 16)
    await run.settle()
    assert isinstance(app.screen, SettingsScreen)
    await run.pilot.resize_terminal(120, 30)
    await run.press("escape")
    await run.until(lambda: app.screen is screen, "the briefing")


@dataclass(frozen=True)
class Spec:
    name: str
    run: Journey
    sizes: tuple[str, ...]
    flags: tuple[str, ...] = ()
    slow: bool = False


EVERY = (*COMMON, *SMALL)
JOURNEYS = [
    Spec("briefing_list", briefing_list, EVERY),
    Spec("sections", sections, EVERY),
    Spec("station_detail_from_list", station_detail_from_list, EVERY),
    Spec("grid", grid, EVERY),
    Spec("grid_detail", grid_detail, EVERY),
    Spec("paste", paste, EVERY),
    Spec("add_station", add_station, EVERY),
    Spec("help", help_screen, EVERY),
    Spec("theme_cycle", theme_cycle, ("120x30", "80x24", "60x16"), slow=True),
    Spec("theme_picker", theme_picker, ("120x30", "80x24", "60x16")),
    Spec("settings", settings, EVERY),
    Spec("copy_keys", copy_keys, ("120x30", "80x24", "60x16")),
    Spec("quit", quit_app, ("120x30", "60x16")),
    Spec("resize", resize, ("120x30",), slow=True),
]
