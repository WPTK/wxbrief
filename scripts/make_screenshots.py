"""Write the small-terminal screenshot to ``docs/img/`` from the bundled ``--demo`` reports.

Usage::

    python scripts/make_screenshots.py

The demo runs on a fixed clock and needs no network, config or cache, so the pictures only change when the interface
does. Textual's exporter writes SVG text (sharp at any size); its credit comment is removed.
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wxbrief.__main__ import build_tui_parser, tui_options  # noqa: E402
from wxbrief.app import WxBriefApp  # noqa: E402

OUT = ROOT / "docs" / "img"
COMMENT = re.compile(r"[ \t]*<!-- Generated with Rich [^>]*-->\r?\n")

# name, terminal size, flags, keys pressed before the shot
SHOTS = [
    ("small", (60, 20), ["--theme", "phosphor-green"], []),
]


async def shoot(name: str, size: tuple[int, int], flags: list[str], keys: list[str]) -> None:
    args = build_tui_parser().parse_args(["--demo", "--no-config", "--glyphs", "unicode", *flags])
    app = WxBriefApp(tui_options(args))
    async with app.run_test(size=size) as pilot:
        await pilot.pause(0.2)
        for key in keys:
            await pilot.press(key)
            await pilot.pause(0.2)
        svg = COMMENT.sub("", app.export_screenshot(title="wxbrief"))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.svg").write_text(svg, encoding="utf-8", newline="\n")
    print(f"wrote docs/img/{name}.svg")


def main() -> None:
    for shot in SHOTS:
        asyncio.run(shoot(*shot))


if __name__ == "__main__":
    main()
