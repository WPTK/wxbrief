"""Regression tests for the defects the UAT journeys found (#59 to #66, #70, #71); each states what should be true.

The terminals below 60x16 (where #71 and the dialog defects at 50x14 and 40x12 lived) now show a notice instead; see
tests/test_layout.py."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from harness import SIZES, Run, footer_text, run_journey
from journeys import plain

from wxbrief.ui.screens.help import HelpScreen
from wxbrief.ui.widgets.station_card import StationCard


async def _check(probe: object, size: str, tmp_path: Path) -> None:
    await run_journey(probe, SIZES[size], tmp_path)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "size",
    ["120x30", "80x24", "200x50", "100x50", "60x20"],
)
async def test_grid_cards_hold_their_content(size: str, tmp_path: Path) -> None:
    """Every grid card shows all its lines: a long station name must not wrap and push the last row out."""
    from harness import card_lines_needed

    async def probe(run: Run) -> None:
        await run.press("v")
        clipped = [c.icao for c in run.briefing.query(StationCard) if card_lines_needed(c) > c.content_size.height]
        assert not clipped, f"cards with clipped content: {clipped}"

    await _check(probe, size, tmp_path)


@pytest.mark.parametrize(
    "size",
    ["120x30", "80x24", "200x50", "60x16", "100x50"],
)
async def test_taf_header_values_do_not_wrap_a_unit_alone(size: str, tmp_path: Path) -> None:
    """The forecast header's dates fit on their line: no line of the screen is just ``UTC`` or a lone time."""

    async def probe(run: Run) -> None:
        await run.press("3")
        orphans = [line for line in run.text().splitlines() if re.search(r"(^|\s{3,})UTC\s*$", line)]
        assert not orphans, "the Valid: line wraps its zone onto a line of its own"

    await _check(probe, size, tmp_path)


async def test_add_station_results_visible_at_60x16(tmp_path: Path) -> None:
    async def probe(run: Run) -> None:
        await run.press("a")
        for char in "ksea":
            await run.pilot.press(char)
        await run.pilot.pause(0.2)
        await run.settle()
        assert "Seattle" in run.text(), "the match list has no room in a 12-row terminal"

    await _check(probe, "60x16", tmp_path)


@pytest.mark.parametrize("size", ["120x30", "80x24"])
async def test_dialog_hints_are_not_clipped(size: str, tmp_path: Path) -> None:
    """The hint line under the add-station dialog is shown whole."""

    async def probe(run: Run) -> None:
        await run.press("a")
        assert "Esc cancels" in run.text()

    await _check(probe, size, tmp_path)


async def test_theme_picker_hint_is_whole_at_120x30(tmp_path: Path) -> None:
    async def probe(run: Run) -> None:
        await run.press("T")
        text = run.text()
        assert "Up/Down previews, Enter keeps" in text, "the picker hint is cut at the dialog edge"

    await _check(probe, "120x30", tmp_path)


async def test_settings_hint_is_whole_in_german(tmp_path: Path) -> None:
    async def probe(run: Run) -> None:
        await run.press("S", "enter", "enter", "enter")
        assert run.app.ctx.translator.lang == "de"
        hint = run.app.screen.query_one("#settings-hint")
        assert hint.size.height >= 2 or "stehen" not in plain(hint).split()[-1], "hint cut at the dialog edge"
        assert plain(hint).rstrip().split()[-1] in run.text(), "the end of the settings hint is not on screen"

    await _check(probe, "120x30", tmp_path)


async def test_settings_values_stay_beside_their_labels_at_60x16(tmp_path: Path) -> None:
    async def probe(run: Run) -> None:
        await run.press("S", "enter", "enter", "enter")
        assert run.app.ctx.translator.lang == "de"
        row = next((line for line in run.text().splitlines() if "Sprache:" in line), "")
        assert "Deutsch" in row, f"the language value is not on its row: {row!r}"

    await _check(probe, "60x16", tmp_path)


@pytest.mark.parametrize("size", ["60x16", "60x20"])
async def test_footer_shows_help_and_quit(size: str, tmp_path: Path) -> None:
    """A tiny terminal still tells the user how to get help and how to leave."""

    async def probe(run: Run) -> None:
        await run.until(lambda: "Raw" in footer_text(run.app), "the detail keys in the footer")
        text = footer_text(run.app)
        assert "Quit" in text and "Help" in text, f"footer: {text!r}"

    await _check(probe, size, tmp_path)


@pytest.mark.parametrize("size", ["60x16", "60x20"])
async def test_footer_does_not_cut_a_label_in_half(size: str, tmp_path: Path) -> None:
    async def probe(run: Run) -> None:
        await run.until(lambda: "Raw" in footer_text(run.app), "the detail keys in the footer")
        text = footer_text(run.app).rstrip()
        known_labels = ("Raw", "Decoded", "TAF", "Copy METAR", "Add", "Paste", "Refresh", "Help", "Quit", "Theme")
        last = text.split()[-1]
        assert last in known_labels, f"footer ends mid-word: {text!r}"

    await _check(probe, size, tmp_path)


async def test_help_wrapped_lines_keep_their_indent_at_80x24(tmp_path: Path) -> None:
    async def probe(run: Run) -> None:
        await run.press("question_mark")
        assert isinstance(run.app.screen, HelpScreen)
        lines = run.text().splitlines()
        first = next(line for line in lines if "Left/Right" in line)
        wrapped = next(line for line in lines if "mouse works too)" in line and "Left/Right" not in line)
        assert wrapped.index("mouse") == first.index("move the"), "a wrapped help line starts at the left edge"

    await _check(probe, "80x24", tmp_path)


@pytest.mark.parametrize("size", ["80x24", "60x20"])
async def test_narrow_terminal_says_where_you_are_in_the_list(size: str, tmp_path: Path) -> None:
    """Below 90 columns the list is hidden: the screen still shows the position among the stations."""

    async def probe(run: Run) -> None:
        text = run.text()
        assert "1/10" in text or "(10)" in text or "1 of 10" in text, "no sign of the other nine stations"

    await _check(probe, size, tmp_path)


async def test_no_stale_horizontal_scrollbar_after_resize(tmp_path: Path) -> None:
    async def probe(run: Run) -> None:
        await run.press("j")
        await run.pilot.resize_terminal(60, 20)
        await run.settle()
        await run.pilot.resize_terminal(100, 50)
        await run.settle()
        stale = [w.id for w in run.app.screen.query("*") if getattr(w, "show_horizontal_scrollbar", False)]
        assert not stale, f"horizontal scrollbar left on {stale}"

    await _check(probe, "120x30", tmp_path)


async def test_text_is_not_hidden_under_the_scrollbar_at_60x16(tmp_path: Path) -> None:
    async def probe(run: Run) -> None:
        await run.press("2")
        lines = [line for line in run.text().splitlines() if "11:53" in line]
        assert lines, "the observed time is not on screen"
        bars = [w for w in run.app.screen.query("*") if w.display and w.show_vertical_scrollbar]
        assert bars, "the probe needs a scrollbar on screen to mean anything"
        for line in lines:
            end = line.index("11:53") + len("11:53")
            for bar in bars:
                assert end <= bar.region.right - bar.scrollbar_size_vertical, "the observed time runs under a scrollbar"

    await _check(probe, "60x16", tmp_path)
