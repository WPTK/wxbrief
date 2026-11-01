"""Write the small-terminal screenshot to ``docs/img/`` from the bundled ``--demo`` reports.

Usage::

    python scripts/make_screenshots.py             # project venv: render SVGs into .shots/
    python scripts/make_screenshots.py --png-only  # Python with Playwright: .shots/*.svg -> docs/img/*.png

The demo runs on a fixed clock and needs no network, config or cache, so the pictures only change when the interface
does. Textual's exporter writes SVG text; its credit comment is removed. The README uses PNGs because GitHub does not
load the SVG's web font. Playwright is not a project dependency (``pip install playwright``, then
``playwright install chromium``); it may live in a different Python from the project venv, hence the two steps.
Without ``--png-only`` the PNGs are also written when Playwright happens to be importable.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from svgcolour import require_colour  # noqa: E402

WORK = ROOT / ".shots"
OUT = ROOT / "docs" / "img"
COMMENT = re.compile(r"[ \t]*<!-- Generated with Rich [^>]*-->\r?\n")

# name, terminal size, flags, keys pressed before the shot
SHOTS = [
    ("briefing", (120, 30), ["--theme", "textual-dark"], ["2"]),
    ("forecast", (120, 30), ["--theme", "paper-chart"], ["3"]),
    ("grid", (120, 30), ["--theme", "nord", "--layout", "grid"], []),
    ("paper-chart", (120, 30), ["--theme", "paper-chart"], ["2"]),
    ("theme-picker", (120, 30), ["--theme", "phosphor-amber"], ["2", "T"]),
]


async def shoot(name: str, size: tuple[int, int], flags: list[str], keys: list[str]) -> None:
    os.environ.pop("NO_COLOR", None)  # the pictures are for showing colour, whatever the shell sets
    from wxbrief.__main__ import build_tui_parser, tui_options
    from wxbrief.app import WxBriefApp

    args = build_tui_parser().parse_args(["--demo", "--no-config", "--glyphs", "unicode", *flags])
    app = WxBriefApp(tui_options(args))
    async with app.run_test(size=size) as pilot:
        await pilot.pause(0.6)
        for key in keys:
            await pilot.press(key)
            await pilot.pause(0.3)
        svg = COMMENT.sub("", app.export_screenshot(title="wxbrief"))
    require_colour(svg, name)
    WORK.mkdir(exist_ok=True)
    (WORK / f"{name}.svg").write_text(svg, encoding="utf-8", newline="\n")
    print(f"wrote .shots/{name}.svg")


def to_png() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is not installed here: run this script with --png-only from a Python that has it")
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    count = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        for svg in sorted(WORK.glob("*.svg")):
            box = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg.read_text(encoding="utf-8"))
            if box is None:
                continue
            page.set_viewport_size({"width": int(float(box[1])) + 1, "height": int(float(box[2])) + 1})
            page.goto(svg.resolve().as_uri())
            clip = {"x": 0, "y": 0, "width": float(box[1]), "height": float(box[2])}
            page.screenshot(path=str(OUT / f"{svg.stem}.png"), clip=clip)
            print(f"wrote docs/img/{svg.stem}.png")
            count += 1
        browser.close()
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--png-only", action="store_true", help="convert the SVGs in .shots/ to PNGs in docs/img/")
    args = parser.parse_args()
    if not args.png_only:
        for shot in SHOTS:
            asyncio.run(shoot(*shot))
    to_png()


if __name__ == "__main__":
    main()
