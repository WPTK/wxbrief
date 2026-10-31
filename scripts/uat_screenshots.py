"""Export the UAT journeys' states as SVG, then PNG, into a directory you name.

Usage::

    python scripts/uat_screenshots.py OUT_DIR                  # the default plan (about fifty pictures)
    python scripts/uat_screenshots.py OUT_DIR --all            # every state of every journey at every size
    python scripts/uat_screenshots.py OUT_DIR --sizes 80x24 --journeys grid grid_detail
    python scripts/uat_screenshots.py OUT_DIR --no-png         # SVG only
    python scripts/uat_screenshots.py OUT_DIR --png-only       # convert the SVGs already in OUT_DIR

It runs the same journeys as ``tests/uat`` (so each picture is a state a test asserted on) on the demo data. The
SVGs come from Textual's exporter with its credit comment removed. The PNGs need Playwright with Chromium
(``pip install playwright`` and ``playwright install chromium``); without it the SVGs are still written. The output
directory is never inside the repo's tracked files: pass a folder outside the checkout.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMMENT = re.compile(r"[ \t]*<!-- Generated with Rich [^>]*-->\r?\n")
ENDS_WITH_SIZE = re.compile(r"\d+x\d+$")
EVERY_SIZE = ("120x30", "200x50", "100x50", "280x70", "80x24", "60x20", "60x16")

# (journey, state) -> the sizes the default plan pictures it at; a state not listed here is only shot with --all.
PLAN: dict[tuple[str, str], tuple[str, ...]] = {
    ("briefing_list", "start"): EVERY_SIZE,
    ("grid", "start"): EVERY_SIZE,
    ("grid", "scrolled"): ("120x30", "80x24", "60x20"),
    ("grid_detail", "top"): ("120x30", "80x24", "60x20"),
    ("grid_detail", "taf"): ("120x30", "80x24"),
    ("sections", "decoded"): ("120x30", "80x24", "60x16"),
    ("sections", "taf"): ("120x30", "100x50", "80x24", "60x16"),
    ("sections", "taf-period"): ("120x30", "80x24"),
    ("paste", "empty"): ("120x30", "80x24"),
    ("paste", "decoded"): ("120x30", "80x24", "60x16"),
    ("add_station", "matches"): ("120x30", "80x24", "60x16"),
    ("add_station", "added"): ("120x30", "80x24"),
    ("help", "top"): ("120x30", "80x24", "60x16"),
    ("help", "end"): ("80x24",),
    ("theme_cycle", "*"): ("120x30",),
    ("theme_picker", "preview"): ("120x30", "80x24"),
    ("settings", "open"): ("120x30", "80x24", "60x16"),
    ("settings", "german"): ("120x30", "80x24", "60x16"),
    ("copy_keys", "copied"): ("120x30",),
    ("resize", "*"): ("120x30",),
}


def wanted(journey: str, label: str, size: str, everything: bool) -> bool:
    if everything:
        return True
    return any(size in PLAN.get(key, ()) for key in ((journey, label), (journey, "*")))


def export_svgs(out: Path, sizes: list[str], journeys: list[str], everything: bool) -> list[Path]:
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "tests" / "uat"))
    from harness import SIZES, Run, run_journey  # type: ignore[import-not-found]
    from journeys import JOURNEYS  # type: ignore[import-not-found]

    written: list[Path] = []
    for spec in JOURNEYS:
        if journeys and spec.name not in journeys:
            continue
        for size in spec.sizes:
            if sizes and size not in sizes:
                continue
            labels = [label for (name, label), at in PLAN.items() if name == spec.name and size in at]
            if not everything and not labels:
                continue

            def take(run: Run, label: str, spec_name: str = spec.name, size: str = size) -> None:
                if not wanted(spec_name, label, size, everything):
                    return
                svg = COMMENT.sub("", run.app.export_screenshot(title="wxbrief"))
                stem = f"{spec_name}-{label}" if ENDS_WITH_SIZE.search(label) else f"{spec_name}-{label}-{size}"
                path = out / f"{stem}.svg"
                path.write_text(svg, encoding="utf-8", newline="\n")
                written.append(path)

            with tempfile.TemporaryDirectory() as work:
                asyncio.run(run_journey(spec.run, SIZES[size], Path(work), *spec.flags, on_shot=take))
            print(f"{spec.name} at {size}: done")
    return written


def export_notices(out: Path, sizes: list[str]) -> list[Path]:
    """The too-small notice at two sizes below the smallest the app draws (the journeys cannot run there)."""
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "tests" / "uat"))
    from harness import demo_app  # type: ignore[import-not-found]

    async def shoot(size: tuple[int, int]) -> str:
        app = demo_app()
        async with app.run_test(size=size) as pilot:
            await pilot.pause(0.4)
            return str(app.export_screenshot(title="wxbrief"))

    written: list[Path] = []
    for name in ("50x14", "40x12"):
        if sizes and name not in sizes:
            continue
        width, height = (int(part) for part in name.split("x"))
        path = out / f"too_small-notice-{name}.svg"
        path.write_text(COMMENT.sub("", asyncio.run(shoot((width, height)))), encoding="utf-8", newline="\n")
        written.append(path)
        print(f"too_small notice at {name}: done")
    return written


def to_png(svgs: list[Path]) -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is not installed: the SVGs are written, no PNGs (pip install playwright)")
        return 0
    count = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        for svg in svgs:
            box = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg.read_text(encoding="utf-8"))
            if box is None:
                continue
            page.set_viewport_size({"width": int(float(box[1])) + 1, "height": int(float(box[2])) + 1})
            page.goto(svg.resolve().as_uri())
            clip = {"x": 0, "y": 0, "width": float(box[1]), "height": float(box[2])}
            page.screenshot(path=str(svg.with_suffix(".png")), clip=clip)
            count += 1
        browser.close()
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out", type=Path, help="directory for the pictures (created if needed; outside the repo)")
    parser.add_argument("--all", action="store_true", help="every state at every size the journey runs at")
    parser.add_argument("--sizes", nargs="*", default=[], help="only these sizes, e.g. 120x30 80x24")
    parser.add_argument("--journeys", nargs="*", default=[], help="only these journeys")
    parser.add_argument("--no-png", action="store_true", help="write SVGs only")
    parser.add_argument("--png-only", action="store_true", help="convert the SVGs already in OUT_DIR")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    if args.png_only:
        svgs = sorted(args.out.glob("*.svg"))
    else:
        svgs = export_svgs(args.out, args.sizes, args.journeys, args.all)
        if not args.journeys:
            svgs += export_notices(args.out, args.sizes)
    print(f"{len(svgs)} SVG files in {args.out}")
    if not args.no_png:
        print(f"{to_png(svgs)} PNG files written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
