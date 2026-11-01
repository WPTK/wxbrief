"""Extra real-terminal checks on top of the basic journey: code pages, font size, colour depth in the light profile, gestures.

    python run_matrix.py {wt,conhost,vscode} --wxbrief PATH --tool-exe PATH --out DIR \
        [--scenarios codepage,font,colors,gestures] [--medium-spawn] [--require-medium]

Each scenario writes ``DIR/result-<terminal>-<scenario>.json`` (the same format as ``run_spike.py``), PNGs and screen text.
Hard assertions are things the product promises (it draws, a click sticks, it does not crash, ``q`` exits, ASCII glyphs draw
only ASCII, the light profile really is light). Behaviour the README does not state (right click, wheel, drag...) is
recorded as ``INFO`` data: the observed selection before and after, whether the screen changed.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import sys
import time
import traceback
from collections.abc import Callable
from pathlib import Path

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_spike as rs
import winterm as w

SEL_RE = re.compile(r"\b(\d+)/10\b")
BAD_RE = re.compile(r"Traceback|UnicodeEncodeError|UnicodeDecodeError|Exception:|Error:")


def sel_of(text: str) -> int | None:
    m = SEL_RE.search(text)
    return int(m.group(1)) if m else None


def app_running(t: rs.Term) -> bool:
    name = t.wxbrief.name.lower()
    return any((p.info["name"] or "").lower() == name for p in psutil.process_iter(["name"]))


def start_app(t: rs.Term, rep: rs.Report, *, expect_frame: bool = True) -> str:
    """Launch, place, prove the profile, wait for the first complete frame. Returns the first frame text."""
    t.launch()
    t.prepare_window()
    t.prove_profile()
    last = {"text": ""}

    def drawn() -> str:
        last["text"] = t.read()
        return last["text"] if re.search(rs.START_RE, last["text"]) and re.search(rs.INITIAL_RE, last["text"]) else ""

    try:
        text = str(w.wait_for(drawn, 90, "the wxbrief list screen"))
    except TimeoutError:
        t.save_text("00-last-read", last["text"])
        t.shot("00-not-drawn", printwindow=True)
        rep.check("app drawn", False, f"last screen: {last['text'][-400:]!r}", critical=expect_frame)
        return last["text"]
    t.save_text("01-start", text)
    t.shot("01-start")
    rep.check("app drawn", True, f"{len(text.splitlines())} lines")
    return text


def finish(t: rs.Term, rep: rs.Report) -> None:
    """q exits cleanly; the window or the prompt returns."""
    w.focus(t.hwnd)
    w.send_text("q")
    time.sleep(0.5)
    try:
        t.quit_check()
        rep.check("q exits the app", True)
    except TimeoutError as exc:
        rep.check("q exits the app", False, str(exc))


# ---------------------------------------------------------------------------------------------------------------------
# scenarios


def sc_codepage(args: argparse.Namespace, make: Callable[..., rs.Term], rep: rs.Report, pages: list[int]) -> None:
    for cp in pages:
        for variant, app_args in (("", "--demo --no-config"), ("-ascii", "--demo --no-config --glyphs ascii")):
            if variant and cp != 437:
                continue
            rep.note(f"cp{cp}{variant}", "begin")
            t = make(tag_suffix=f"cp{cp}{variant}", codepage=cp, app_args=app_args)
            try:
                text = start_app(t, rep, expect_frame=False)
                non_ascii = sorted({c for c in text if ord(c) > 126})
                bad = BAD_RE.findall(text)
                rep.check(f"cp{cp}{variant}: no traceback or encoding error on screen", not bad, str(bad[:3]))
                rep.note(
                    f"cp{cp}{variant} glyphs",
                    f"non-ASCII chars on screen: {len(non_ascii)} {''.join(non_ascii)[:40]!r}",
                )
                rep.check(f"cp{cp}{variant}: app alive", app_running(t) or not t.window_gone())
                if variant:
                    rep.check("--glyphs ascii draws only ASCII", not non_ascii, f"found {non_ascii[:10]}")
                if re.search(rs.START_RE, text):
                    t.save_text("02-text", text)
                    finish(t, rep)
            except rs.Abort:
                pass
            finally:
                with contextlib.suppress(Exception):
                    t.shot("99-end")
                with contextlib.suppress(Exception):
                    t.teardown()


def sc_font(args: argparse.Namespace, make: Callable[..., rs.Term], rep: rs.Report) -> None:
    cells: dict[int, tuple[float, float, int]] = {}
    for pt in (8, 12, 20):
        t = make(tag_suffix=f"font{pt}", font_pt=pt, probe=False)
        try:
            text = start_app(t, rep)
            rect = t.rect_of("Stations (10)")
            ctrl = t._uia.control_rect()  # type: ignore[attr-defined]
            if rect:
                cw = (rect[2] - rect[0]) / len("Stations (10)")
                ch = float(rect[3] - rect[1])
                cols, rows = int((ctrl[2] - ctrl[0]) / cw), int((ctrl[3] - ctrl[1]) / ch)
                cells[pt] = (cw, ch, cols)
                rep.note(f"font {pt}pt", f"cell {cw:.1f}x{ch:.1f}px, about {cols}x{rows} cells in {ctrl}")
            rep.check(
                f"font {pt}pt: layout recalculated and app usable",
                "Stations" in text and "too small" not in text.lower(),
            )
            finish(t, rep)
        except rs.Abort:
            pass
        finally:
            with contextlib.suppress(Exception):
                t.shot("99-end")
            with contextlib.suppress(Exception):
                t.teardown()
    if len(cells) == 3:
        rep.check(
            "cell size grows with font size and the column count shrinks",
            cells[8][1] < cells[12][1] < cells[20][1] and cells[8][2] > cells[12][2] > cells[20][2],
            json.dumps({k: [round(x, 1) for x in v] for k, v in cells.items()}),
        )
    else:
        rep.check("cell size measured at 8, 12 and 20 pt", False, f"got {sorted(cells)}")


def sc_colors(args: argparse.Namespace, make: Callable[..., rs.Term], rep: rs.Report) -> None:
    for name, env, hard_bg in (
        ("nocolor", {"NO_COLOR": "1"}, True),
        ("c16", {"TEXTUAL_COLOR_SYSTEM": "standard", "COLORTERM": ""}, False),
    ):
        t = make(tag_suffix=f"light-{name}", env_extra=env, scheme="light")
        try:
            start_app(t, rep)
            time.sleep(1.0)
            png = t.out / f"{t.tag}-02-colors-window.png"
            left, top, right, bottom = w.window_info(t.hwnd).rect
            sw, sh = w.screen_size()
            w.screenshot_screen(png, (max(left, 0), max(top, 0), min(right, sw), min(bottom, sh)))
            info = w.analyze_png(png)
            rep.note(f"{name} pixels", json.dumps(info))
            rep.info[f"pixels_{name}"] = info
            if (
                hard_bg
            ):  # NO_COLOR: every cell is default fg on default bg, so the app area is the terminal's own light colours
                rep.check(f"{name}: app area uses the light default background", info["bg_luminance"] > 0.7, info["bg"])
            else:
                rep.note(
                    f"{name} app background",
                    f"{info['bg']} luminance {info['bg_luminance']} (the app may paint its own)",
                )
            rep.check(
                f"{name}: default text reads against the background (>= 4.5:1)",
                info["contrast"] >= 4.5,
                f"{info['text']} on {info['bg']} = {info['contrast']}:1",
            )
            finish(t, rep)
        except rs.Abort:
            pass
        finally:
            with contextlib.suppress(Exception):
                t.teardown()


def sc_gestures(args: argparse.Namespace, make: Callable[..., rs.Term], rep: rs.Report) -> None:
    t = make(tag_suffix="gestures")
    try:
        text = start_app(t, rep)
        n = {"i": 0}
        cur = {"text": text}

        def row_center(label: str) -> tuple[int, int]:
            rect = None
            for _ in range(3):
                rect = t.rect_of(label)
                if rect:
                    break
                time.sleep(0.7)
            assert rect, f"no pixel rect for {label!r}"
            return (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2

        def after(name: str, before: str) -> str:
            n["i"] += 1
            time.sleep(1.0)
            t.after_keys()
            now = t.read()
            tag = f"g{n['i']:02d}-{name}"
            t.save_text(tag, now)
            t.shot(tag)
            changed = now != before
            rep.note(
                f"{name}: observed",
                f"selection {sel_of(before)} -> {sel_of(now)}; screen changed={changed}; bad_text={BAD_RE.findall(now)[:2]}",
            )
            alive = (not t.window_gone() or isinstance(t, rs.VSCode)) and app_running(t)
            rep.check(f"{name}: app and window still alive, no traceback", alive and not BAD_RE.search(now))
            cur["text"] = now
            return now

        def back_to_list() -> None:
            w.focus(t.hwnd)
            w.tap(w.VK_ESCAPE)
            time.sleep(0.8)

        # hover: motion only
        x, y = row_center("UUEE")
        before = cur["text"]
        w.focus(t.hwnd)
        w.hover_at(x, y)
        now = after("hover", before)
        rep.check("hover alone does not change the selection", sel_of(now) == sel_of(before))

        # left click on a row: documented, selection sticks
        before = cur["text"]
        w.click_at(x, y)
        now = after("click", before)
        rep.check("click on a row selects it (4/10)", sel_of(now) == 4)

        # double click: station_list.on_click opens the detail / moves focus to the detail pane
        kx, ky = row_center("KDEN")
        before = cur["text"]
        w.double_click_at(x, y)
        now = after("double-click", before)
        rep.check("double click keeps the row selected (4/10)", sel_of(now) == 4)
        rep.check("double click opens the detail (screen changes: focus moves to the detail pane)", now != before)
        back_to_list()
        cur["text"] = t.read()

        # right and middle click: README silent
        before = cur["text"]
        w.click_at(x, y, button="right")
        now = after("right-click", before)
        if now != before:
            back_to_list()
        before = t.read()
        w.click_at(kx, ky, button="middle")
        now = after("middle-click", before)

        # wheel over the list
        before = t.read()
        w.focus(t.hwnd)
        w.wheel_at(x, y, -5)
        now = after("wheel-down-5", before)
        before = now
        w.wheel_at(x, y, 5)
        now = after("wheel-up-5", before)

        # drag from one row to another
        before = t.read()
        w.drag_between(kx, ky, x, y)
        now = after("drag", before)

        # click on empty space: well below the rows, above the key bar
        left, _top, right, bottom = w.window_info(t.hwnd).rect
        ex, ey = left + (right - left) * 3 // 4, bottom - 80
        before = t.read()
        w.click_at(ex, ey)
        now = after("click-empty", before)
        rep.note("click-empty point", f"({ex},{ey})")

        # still responsive to the keyboard after all of it
        w.focus(t.hwnd)
        w.send_text("2")
        time.sleep(1.0)
        now = t.read()
        rep.check(
            "keyboard still works after the gestures (screen redraws, app alive)",
            bool(re.search(rs.START_RE, now)) and app_running(t),
        )
        finish(t, rep)
    except rs.Abort:
        pass
    except AssertionError as exc:
        rep.check("gesture setup", False, str(exc))
    finally:
        with contextlib.suppress(Exception):
            t.shot("99-end")
        with contextlib.suppress(Exception):
            t.teardown()


# ---------------------------------------------------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("terminal", choices=sorted(rs.TERMS))
    ap.add_argument("--wxbrief", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--tool-exe", type=Path)
    ap.add_argument("--scenarios", default="codepage,font,colors,gestures")
    ap.add_argument("--scheme", choices=["dark", "light"], default="dark")
    ap.add_argument("--medium-spawn", action="store_true")
    ap.add_argument("--require-medium", action="store_true")
    ap.add_argument("--profile", choices=["cmd", "powershell"], default="cmd")
    ap.add_argument("--tag", default="")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    wanted = [s for s in args.scenarios.split(",") if s]
    failed = False
    for sc in wanted:
        if sc == "font" and args.terminal != "wt":
            continue  # font size is a Windows Terminal setting; conhost and VS Code have their own paths (not in scope)
        if sc == "codepage" and args.terminal == "vscode":
            continue  # xterm.js decodes UTF-8 whatever the console code page says; nothing to vary
        rep = rs.Report(f"{args.terminal}{('-' + args.tag) if args.tag else ''}-{sc}", args.out)
        rep.info = rs.diagnostics(args.out)
        w.log(f"=== scenario {sc} on {args.terminal}")

        def make(*, rep: rs.Report = rep, scheme: str | None = None, **kw: object) -> rs.Term:
            return rs.TERMS[args.terminal](
                rep,
                args.wxbrief.resolve(),
                args.out,
                args.tool_exe.resolve() if args.tool_exe else None,
                False,
                scheme or args.scheme,
                medium_spawn=args.medium_spawn,
                require_medium=args.require_medium,
                profile=args.profile,
                **kw,  # type: ignore[arg-type]
            )

        try:
            if sc == "codepage":
                sc_codepage(args, make, rep, [437, 1252, 65001] if args.terminal == "conhost" else [437])
            elif sc == "font":
                sc_font(args, make, rep)
            elif sc == "colors":
                sc_colors(args, make, rep)
            elif sc == "gestures":
                sc_gestures(args, make, rep)
            else:
                rep.check(f"known scenario {sc}", False)
        except Exception:
            rep.check("unexpected error", False, traceback.format_exc()[-1500:])
        finally:
            rep.write()
        failed |= not rep.passed
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
