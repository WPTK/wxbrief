"""Defects the UAT journeys found. Each test states what should be true and is expected to fail until the bug is fixed.

The tests are ``xfail(strict=True)``: when a fix lands the test XPASSes and fails the run, which is the cue to delete
the ``xfail`` mark here and keep the test as a regression test. The number in each reason is the GitHub issue.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from harness import SIZES, Run, footer_text, run_journey
from journeys import plain

from wxbrief.ui.screens.help import HelpScreen
from wxbrief.ui.widgets.station_card import StationCard


def known(issue: int) -> pytest.MarkDecorator:
    return pytest.mark.xfail(strict=True, reason=f"issue #{issue}")


async def _check(probe: object, size: str, tmp_path: Path) -> None:
    await run_journey(probe, SIZES[size], tmp_path)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "size",
    [pytest.param(s, marks=known(59)) for s in ("120x30", "80x24", "200x50")] + ["100x50", "60x20"],
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
    [pytest.param(s, marks=known(60)) for s in ("120x30", "80x24", "200x50", "40x12", "100x50")],
)
async def test_taf_header_values_do_not_wrap_a_unit_alone(size: str, tmp_path: Path) -> None:
    """The forecast header's dates fit on their line: no line of the screen is just ``UTC`` or a lone time."""

    async def probe(run: Run) -> None:
        await run.press("3")
        orphans = [line for line in run.text().splitlines() if re.search(r"(^|\s{3,})UTC\s*$", line)]
        assert not orphans, "the Valid: line wraps its zone onto a line of its own"

    await _check(probe, size, tmp_path)


@known(61)
async def test_add_station_results_visible_at_40x12(tmp_path: Path) -> None:
    async def probe(run: Run) -> None:
        await run.press("a")
        for char in "ksea":
            await run.pilot.press(char)
        await run.pilot.pause(0.2)
        await run.settle()
        assert "Seattle" in run.text(), "the match list has no room in a 12-row terminal"

    await _check(probe, "40x12", tmp_path)


@pytest.mark.parametrize("size", ["120x30", pytest.param("80x24", marks=known(61))])
async def test_dialog_hints_are_not_clipped(size: str, tmp_path: Path) -> None:
    """The hint line under the add-station dialog is shown whole."""

    async def probe(run: Run) -> None:
        await run.press("a")
        assert "Esc cancels" in run.text()

    await _check(probe, size, tmp_path)


@known(62)
async def test_theme_picker_hint_is_whole_at_120x30(tmp_path: Path) -> None:
    async def probe(run: Run) -> None:
        await run.press("T")
        text = run.text()
        assert "Up/Down previews, Enter keeps" in text, "the picker hint is cut at the dialog edge"

    await _check(probe, "120x30", tmp_path)


@known(62)
async def test_settings_hint_is_whole_in_german(tmp_path: Path) -> None:
    async def probe(run: Run) -> None:
        await run.press("S", "enter", "enter", "enter")
        assert run.app.ctx.translator.lang == "de"
        hint = run.app.screen.query_one("#settings-hint")
        assert hint.size.height >= 2 or "stehen" not in plain(hint).split()[-1], "hint cut at the dialog edge"
        assert plain(hint).rstrip().split()[-1] in run.text(), "the end of the settings hint is not on screen"

    await _check(probe, "120x30", tmp_path)


@known(63)
async def test_settings_values_stay_beside_their_labels_at_50x14(tmp_path: Path) -> None:
    async def probe(run: Run) -> None:
        await run.press("S", "enter", "enter", "enter")
        assert run.app.ctx.translator.lang == "de"
        row = next((line for line in run.text().splitlines() if "Sprache:" in line), "")
        assert "Deutsch" in row, f"the language value is not on its row: {row!r}"

    await _check(probe, "50x14", tmp_path)


@known(64)
@pytest.mark.parametrize("size", ["50x14", "40x12"])
async def test_footer_shows_help_and_quit(size: str, tmp_path: Path) -> None:
    """A tiny terminal still tells the user how to get help and how to leave."""

    async def probe(run: Run) -> None:
        await run.until(lambda: "Raw" in footer_text(run.app), "the detail keys in the footer")
        text = footer_text(run.app)
        assert "Quit" in text and "Help" in text, f"footer: {text!r}"

    await _check(probe, size, tmp_path)


@pytest.mark.parametrize("size", [pytest.param("50x14", marks=known(64)), "40x12"])
async def test_footer_does_not_cut_a_label_in_half(size: str, tmp_path: Path) -> None:
    async def probe(run: Run) -> None:
        await run.until(lambda: "Raw" in footer_text(run.app), "the detail keys in the footer")
        text = footer_text(run.app).rstrip()
        known_labels = ("Raw", "Decoded", "TAF", "Copy METAR", "Add", "Paste", "Refresh", "Help", "Quit", "Theme")
        last = text.split()[-1]
        assert last in known_labels, f"footer ends mid-word: {text!r}"

    await _check(probe, size, tmp_path)


@known(65)
async def test_help_wrapped_lines_keep_their_indent_at_80x24(tmp_path: Path) -> None:
    async def probe(run: Run) -> None:
        await run.press("question_mark")
        assert isinstance(run.app.screen, HelpScreen)
        lines = run.text().splitlines()
        wrapped = next(line for line in lines if "(the mouse works too)" in line)
        first = next(line for line in lines if "Left/Right" in line)
        assert wrapped.index("(the mouse") == first.index("move the"), "a wrapped help line starts at the left edge"

    await _check(probe, "80x24", tmp_path)


@known(66)
@pytest.mark.parametrize("size", ["80x24", "60x20"])
async def test_narrow_terminal_says_where_you_are_in_the_list(size: str, tmp_path: Path) -> None:
    """Below 90 columns the list is hidden: the screen still shows the position among the stations."""

    async def probe(run: Run) -> None:
        text = run.text()
        assert "1/10" in text or "(10)" in text or "1 of 10" in text, "no sign of the other nine stations"

    await _check(probe, size, tmp_path)


@known(70)
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


@known(71)
async def test_text_is_not_hidden_under_the_scrollbar_at_40x12(tmp_path: Path) -> None:
    async def probe(run: Run) -> None:
        await run.press("2")
        assert "11:53" in run.text(), "the observed time is covered by the scrollbar"

    await _check(probe, "40x12", tmp_path)
