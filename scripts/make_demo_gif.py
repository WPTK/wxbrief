"""Record the README demo, ``docs/img/demo.gif``, from the bundled ``--demo`` reports.

Usage::

    python scripts/make_demo_gif.py

The real app runs headless on its fixed demo clock (no network, config or cache). After each scripted key the screen is
read from Textual's compositor and drawn cell by cell with Pillow, so every frame is the interface itself. Needs a
monospaced TrueType font: Cascadia Code, Consolas, DejaVu Sans Mono or Menlo, whichever is installed.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

os.environ.pop("NO_COLOR", None)  # the demo shows colour, whatever the shell sets; before Rich reads the environment

from PIL import Image, ImageDraw, ImageFont
from rich.color import Color
from rich.style import Style

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from svgcolour import chromatic_colours  # noqa: E402

from wxbrief.__main__ import build_tui_parser, tui_options  # noqa: E402
from wxbrief.app import WxBriefApp  # noqa: E402

OUT = ROOT / "docs" / "img" / "demo.gif"
SIZE = (120, 30)
FONT_SIZE = 15
FONTS = (
    "C:/Windows/Fonts/CaskaydiaCoveNerdFontMono-Regular.ttf",
    "C:/Windows/Fonts/consola.ttf",
    "C:/Windows/Fonts/CascadiaMono.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/System/Library/Fonts/Menlo.ttc",
)
# (key, seconds the frame stays up); None is the opening frame
SCRIPT = [
    (None, 2.0),
    ("down", 1.5),
    ("down", 1.5),
    ("2", 2.0),
    ("3", 2.5),
    ("down", 1.5),
    ("3", 1.0),
    ("v", 2.5),
    ("t", 1.5),
    ("t", 1.5),
]


def load_font() -> ImageFont.FreeTypeFont:
    for path in FONTS:
        if Path(path).exists():
            return ImageFont.truetype(path, FONT_SIZE)
    sys.exit("no monospaced TrueType font found; edit FONTS")


def rgb(color: Color | None, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    if color is None or color.is_default:
        return fallback
    return tuple(color.get_truecolor())  # type: ignore[return-value]


def draw_frame(app: WxBriefApp, font: ImageFont.FreeTypeFont) -> Image.Image:
    cols, rows = app.size
    cell_w = round(font.getlength("M"))
    ascent, descent = font.getmetrics()
    cell_h = ascent + descent + 2
    image = Image.new("RGB", (cols * cell_w, rows * cell_h), (0, 0, 0))
    draw = ImageDraw.Draw(image)
    lines = app.screen._compositor.render_strips()
    for y, strip in enumerate(lines[:rows]):
        x = 0
        for segment in strip:
            style = segment.style or Style()
            fg, bg = rgb(style.color, (204, 204, 204)), rgb(style.bgcolor, (0, 0, 0))
            if style.reverse:
                fg, bg = bg, fg
            for ch in segment.text:
                draw.rectangle((x * cell_w, y * cell_h, (x + 1) * cell_w - 1, (y + 1) * cell_h - 1), fill=bg)
                if ch != " ":
                    draw.text((x * cell_w, y * cell_h), ch, font=font, fill=fg, stroke_width=0)
                    if style.bold:
                        draw.text((x * cell_w + 1, y * cell_h), ch, font=font, fill=fg)
                x += 1
    return image


async def record() -> tuple[list[Image.Image], list[int]]:
    font = load_font()
    args = build_tui_parser().parse_args(["--demo", "--no-config", "--glyphs", "unicode", "--theme", "textual-dark"])
    app = WxBriefApp(tui_options(args))
    frames: list[Image.Image] = []
    durations: list[int] = []
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause(0.3)
        for key, seconds in SCRIPT:
            if key:
                await pilot.press(key)
                await pilot.pause(0.3)
            frames.append(draw_frame(app, font))
            durations.append(int(seconds * 1000))
    return frames, durations


def require_colour(frames: list[Image.Image]) -> None:
    """Fail when the frames have no chromatic colour, as happens when NO_COLOR reaches the app."""
    colours = {c for f in frames for _, c in f.getcolors(maxcolors=1 << 24) or []}
    as_svg = " ".join(f'fill="#{r:02x}{g:02x}{b:02x}"' for r, g, b in colours)
    if len(chromatic_colours(as_svg)) < 3:
        sys.exit("the frames have no chromatic colour: they were captured without colour (is NO_COLOR set?)")


def main() -> None:
    frames, durations = asyncio.run(record())
    require_colour(frames)
    montage = Image.new("RGB", (frames[0].width, frames[0].height * len(frames)))
    for i, f in enumerate(frames):
        montage.paste(f, (0, i * f.height))
    shared = montage.quantize(colors=128, method=Image.Quantize.MEDIANCUT)
    paletted = [f.quantize(palette=shared, dither=Image.Dither.NONE) for f in frames]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    paletted[0].save(OUT, save_all=True, append_images=paletted[1:], duration=durations, loop=0, optimize=True)
    kb = OUT.stat().st_size // 1024
    print(f"wrote {OUT.relative_to(ROOT)}: {len(frames)} frames, {sum(durations) / 1000:.0f} s, {kb} KB")


if __name__ == "__main__":
    main()
