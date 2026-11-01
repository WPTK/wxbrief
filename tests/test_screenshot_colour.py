"""The screenshot scripts refuse monochrome pictures, and the app honours NO_COLOR."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from svgcolour import chromatic_colours, require_colour

from wxbrief.__main__ import build_tui_parser, tui_options
from wxbrief.app import WxBriefApp


def _svg(*colours: str) -> str:
    return "<svg><style>" + "".join(f".r{i} {{ fill: {c} }}" for i, c in enumerate(colours)) + "</style></svg>"


def test_greys_and_tinted_darks_are_not_colour() -> None:
    assert chromatic_colours(_svg("#121212", "#a8a8a8", "#242f38", "#ffffff")) == set()


def test_hues_are_colour() -> None:
    assert chromatic_colours(_svg("#3ddc6a", "#ff5cf0", "#0178d4", "#121212")) == {"3ddc6a", "ff5cf0", "0178d4"}


def test_require_colour_rejects_monochrome_and_accepts_colour() -> None:
    with pytest.raises(SystemExit, match="NO_COLOR"):
        require_colour(_svg("#121212", "#a8a8a8"), "mono")
    require_colour(_svg("#3ddc6a", "#ff5cf0", "#0178d4"), "colour")


def _briefing_svg() -> str:
    args = build_tui_parser().parse_args(["--demo", "--no-config", "--theme", "textual-dark"])

    async def run() -> str:
        app = WxBriefApp(tui_options(args))
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.3)
            return str(app.export_screenshot(title="wxbrief"))

    return asyncio.run(run())


def test_no_color_is_honoured_and_unset_gives_flight_category_colours(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    assert len(chromatic_colours(_briefing_svg())) < 3
    monkeypatch.delenv("NO_COLOR")
    assert len(chromatic_colours(_briefing_svg())) >= 3
