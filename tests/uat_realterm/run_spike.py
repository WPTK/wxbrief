"""Drive the wxbrief 0.3.0 release exe in a REAL Windows terminal and read the screen back.

    python run_spike.py {wt,conhost,vscode} --wxbrief PATH --out DIR [--tool-exe PATH]

For one terminal this launches ``wxbrief --demo``, focuses the window, sends keys (``2``, ``v``, ``v``), clicks a station
row by cell->pixel math (motion, press, release), reads the screen text back (UIA TextPattern for Windows Terminal and
conhost, select-all + copy to the clipboard for VS Code), saves PNGs and text, presses ``q`` and checks the exit, then
tears down by PID. Exit code 0 only if every assertion passed. Results go to ``DIR/result-<terminal>.json``.

Assertions (the demo opens on KDEN, 1/10): after clicking the UUEE row the status bar says ``4/10`` and the detail pane
header names UUEE (Moscow/Sheremetyevo); ``q`` ends the app (the window closes, or in VS Code the prompt comes back).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import platform
import re
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parent))
import winterm as w

START_RE = r"Stations \(10\)"
INITIAL_RE = r"\b1/10\b"
TARGET_ROW = "UUEE"
AFTER_CLICK = [r"\b4/10\b", r"UUEE\s+Moscow"]
VK_BACKTICK = 0xC0
VK_A, VK_C, VK_X, VK_M = ord("A"), ord("C"), ord("X"), ord("M")


class Abort(Exception):
    """A step the rest of the run depends on failed."""


class Report:
    def __init__(self, terminal: str, out: Path) -> None:
        self.terminal, self.out = terminal, out
        self.steps: list[dict[str, Any]] = []
        self.info: dict[str, Any] = {}
        self.t0 = time.monotonic()

    def check(self, name: str, ok: bool, detail: str = "", *, critical: bool = False) -> bool:
        self.steps.append({"step": name, "ok": ok, "detail": detail, "t": round(time.monotonic() - self.t0, 1)})
        w.log(f"{'PASS' if ok else 'FAIL'} {name} {detail}")
        if critical and not ok:
            raise Abort(name)
        return ok

    def note(self, name: str, detail: str) -> None:
        self.steps.append({"step": name, "ok": None, "detail": detail, "t": round(time.monotonic() - self.t0, 1)})
        w.log(f"INFO {name} {detail}")

    @property
    def passed(self) -> bool:
        return all(s["ok"] is not False for s in self.steps) and any(s["ok"] for s in self.steps)

    def write(self) -> None:
        data = {
            "terminal": self.terminal,
            "passed": self.passed,
            "runtime_s": round(time.monotonic() - self.t0, 1),
            "info": self.info,
            "steps": self.steps,
        }
        (self.out / f"result-{self.terminal}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------------------------------------------------
# terminal adapters


class Term:
    """What differs between terminals: launch, finding the window, reading text, locating text in pixels, quitting."""

    name = "?"

    def __init__(self, rep: Report, wxbrief: Path, out: Path, tool_exe: Path | None) -> None:
        self.rep, self.wxbrief, self.out, self.tool_exe = rep, wxbrief, out, tool_exe
        self.proc: subprocess.Popen[bytes] | None = None
        self.hwnd = 0
        self.pids: set[int] = set()
        self.image_dirs: tuple[str, ...] = ()
        self.work = out / f"work-{self.name}"
        self.work.mkdir(parents=True, exist_ok=True)
        self.run_cmd = self.work / "run-wxbrief.cmd"
        self.env = dict(os.environ, WXBRIEF_CACHE_DIR=str(self.work / "cache"))
        self.env.pop("NO_COLOR", None)

    def write_run_cmd(self, prefix: str = "") -> None:
        self.run_cmd.write_text(
            f'@echo off\r\n{prefix}"{self.wxbrief}" --demo --no-config\r\nexit /b %errorlevel%\r\n', encoding="ascii"
        )

    def launch(self) -> None:
        raise NotImplementedError

    def read(self) -> str:
        raise NotImplementedError

    def rect_of(self, text: str) -> tuple[int, int, int, int] | None:
        raise NotImplementedError

    def after_keys(self) -> None:
        """Hook run after sending keys (VS Code needs to clear its selection)."""

    def tracked(self) -> set[int]:
        out = set(self.pids)
        if self.proc:
            out |= {p.pid for p in w.process_tree(self.proc.pid)}
        return out

    def find_window(self, cls: str, timeout: float = 60) -> int:
        before = {win.hwnd for win in self.baseline}

        def look() -> int:
            tree = {p.pid for p in w.process_tree(self.proc.pid)} if self.proc else set()
            cands = [win for win in w.all_windows() if win.cls == cls and win.visible and win.hwnd not in before]
            mine = [win for win in cands if win.pid in tree]
            pick = (mine or cands or [None])[0]
            return pick.hwnd if pick else 0

        return int(w.wait_for(look, timeout, f"a visible {cls} window"))

    def window_gone(self) -> bool:
        return not w.is_window(self.hwnd)

    def snapshot_baseline(self) -> None:
        self.baseline = w.all_windows()

    def shot(self, tag: str, *, printwindow: bool = False) -> None:
        base = self.out / f"{self.name}-{tag}"
        sw, sh = w.screen_size()
        if self.hwnd and w.is_window(self.hwnd):
            left, top, right, bottom = w.window_info(self.hwnd).rect
            bbox = (max(left, 0), max(top, 0), min(right, sw), min(bottom, sh))
            if bbox[2] > bbox[0] and bbox[3] > bbox[1]:
                w.screenshot_screen(base.with_name(base.name + "-window.png"), bbox)
            if printwindow:
                ok, bright = w.screenshot_printwindow(self.hwnd, base.with_name(base.name + "-printwindow.png"))
                self.rep.note(f"printwindow {tag}", f"ok={ok} mean_brightness={bright:.1f}")
        w.screenshot_screen(base.with_name(base.name + "-desktop.png"))

    def save_text(self, tag: str, text: str) -> None:
        (self.out / f"{self.name}-{tag}.txt").write_text(text, encoding="utf-8")

    def prepare_window(self) -> None:
        sw, sh = w.screen_size()
        width, height = min(sw - 20, 1280), min(sh - 60, 800)
        w.move_resize(self.hwnd, 0, 0, width, height)
        time.sleep(0.8)
        ok = w.focus(self.hwnd)
        fg = w.window_info(w.foreground()) if w.foreground() else None
        self.rep.check("focus window", ok, f"foreground={fg}", critical=True)

    def quit_check(self) -> bool:
        w.wait_for(self.window_gone, 20, "the window to close")
        return True

    def teardown(self) -> None:
        pids = self.tracked()
        if self.hwnd and w.is_window(self.hwnd):
            w.close_window(self.hwnd)
            time.sleep(1.0)
        if self.proc:
            killed = w.kill_tree(self.proc.pid)
            self.rep.note("teardown", f"killed by PID: {killed}")
        dirs = tuple(d.lower() for d in (*self.image_dirs, str(self.wxbrief.parent)))
        for p in psutil.process_iter(
            ["exe"]
        ):  # a process the tree walk missed (a hand-off): found by path, killed by PID
            with contextlib.suppress(psutil.Error):
                if (p.info["exe"] or "").lower().startswith(dirs):
                    self.rep.note("teardown", f"killed stray pid {p.pid} {p.info['exe']}")
                    p.kill()
        time.sleep(1.0)
        left = w.survivors(pids, (*self.image_dirs, str(self.wxbrief.parent)))
        self.rep.check("teardown leaves no survivors", not left, f"survivors={left}")


class Conhost(Term):
    name = "conhost"

    def launch(self) -> None:
        self.write_run_cmd("mode con: cols=120 lines=30\r\n")
        self.snapshot_baseline()
        conhost = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "conhost.exe"
        self.proc = subprocess.Popen([str(conhost), "cmd.exe", "/c", str(self.run_cmd)], env=self.env)
        self.hwnd = self.find_window("ConsoleWindowClass")
        self.rep.note("window", str(w.window_info(self.hwnd)))
        self._uia = w.UiaText(self.hwnd)

    def read(self) -> str:
        return self._uia.read()

    def rect_of(self, text: str) -> tuple[int, int, int, int] | None:
        return self._uia.find_rect(text)


class WindowsTerminal(Term):
    name = "wt"

    def launch(self) -> None:
        assert self.tool_exe
        (self.tool_exe.parent / ".portable").write_text("", encoding="ascii")  # portable mode: settings beside the exe
        self.image_dirs = (str(self.tool_exe.parent),)
        self.write_run_cmd()
        self.snapshot_baseline()
        self.proc = subprocess.Popen([str(self.tool_exe), "cmd.exe", "/c", str(self.run_cmd)], env=self.env)
        self.hwnd = self.find_window("CASCADIA_HOSTING_WINDOW_CLASS")
        self.rep.note("window", str(w.window_info(self.hwnd)))
        self._uia = w.UiaText(self.hwnd)

    def read(self) -> str:
        return self._uia.read()

    def rect_of(self, text: str) -> tuple[int, int, int, int] | None:
        return self._uia.find_rect(text)


class VSCode(Term):
    name = "vscode"
    SETTINGS = {
        "security.workspace.trust.enabled": False,
        "workbench.startupEditor": "none",
        "workbench.tips.enabled": False,
        "workbench.welcomePage.walkthroughs.openOnInstall": False,
        "telemetry.telemetryLevel": "off",
        "update.mode": "none",
        "extensions.autoUpdate": False,
        "extensions.autoCheckUpdates": False,
        "window.restoreWindows": "none",
        "window.confirmBeforeClose": "never",
        "chat.disableAIFeatures": True,
        "terminal.integrated.defaultProfile.windows": "Command Prompt",
        "terminal.integrated.gpuAcceleration": "off",
        "terminal.integrated.enablePersistentSessions": False,
        "terminal.integrated.confirmOnExit": "never",
        "editor.accessibilitySupport": "on",
    }
    KEYBINDINGS = [
        {"key": "ctrl+alt+a", "command": "workbench.action.terminal.selectAll", "when": "terminalFocus"},
        {"key": "ctrl+alt+c", "command": "workbench.action.terminal.copySelection", "when": "terminalFocus"},
        {"key": "ctrl+alt+x", "command": "workbench.action.terminal.clearSelection", "when": "terminalFocus"},
        {"key": "ctrl+alt+m", "command": "workbench.action.toggleMaximizedPanel"},
    ]

    def launch(self) -> None:
        assert self.tool_exe
        root = self.tool_exe.parent
        user = root / "data" / "user-data" / "User"
        user.mkdir(parents=True, exist_ok=True)
        (user / "settings.json").write_text(json.dumps(self.SETTINGS, indent=2), encoding="utf-8")
        (user / "keybindings.json").write_text(json.dumps(self.KEYBINDINGS, indent=2), encoding="utf-8")
        self.image_dirs = (str(root),)
        self.write_run_cmd()
        folder = self.work / "folder"
        folder.mkdir(exist_ok=True)
        self.snapshot_baseline()
        self.proc = subprocess.Popen(
            [
                str(self.tool_exe),
                "--disable-extensions",
                "--disable-workspace-trust",
                "--skip-release-notes",
                "--skip-welcome",
                "--force-renderer-accessibility",
                "--new-window",
                str(folder),
            ],
            env=self.env,
        )
        self.hwnd = self.find_window("Chrome_WidgetWin_1", timeout=90)
        self.rep.note("window", str(w.window_info(self.hwnd)))
        self._uia: w.UiaText | None = None

    def prepare_window(self) -> None:
        super().prepare_window()
        w.maximize(self.hwnd)
        time.sleep(15)  # a first start builds caches; there is no ready signal on a window with no UIA text yet
        w.focus(self.hwnd)
        self.shot("pre-terminal")
        w.chord(w.VK_CONTROL, VK_BACKTICK)  # Ctrl+` opens and focuses the integrated terminal
        time.sleep(4)
        w.chord(w.VK_CONTROL, w.VK_MENU, VK_M)  # maximise the panel so the TUI has room (60x16 minimum)
        time.sleep(2)
        self.shot("terminal-open")
        w.send_text(f'"{self.run_cmd}"\n', delay=0.02)

    def read(self) -> str:
        w.clear_clipboard()
        w.chord(w.VK_CONTROL, w.VK_MENU, VK_A)
        time.sleep(0.4)
        w.chord(w.VK_CONTROL, w.VK_MENU, VK_C)
        time.sleep(0.4)
        text = w.clipboard_text()
        w.chord(w.VK_CONTROL, w.VK_MENU, VK_X)
        return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").split("\n"))

    def rect_of(self, text: str) -> tuple[int, int, int, int] | None:
        """Row rectangle from the xterm.js accessibility tree (the screen-reader row div), cell x from the text."""
        import uiautomation as auto

        grid = self.read()
        line = next((ln for ln in grid.split("\n") if re.search(rf"{text}\s+IFR", ln)), None)
        if line is None:
            return None
        cols = max(len(ln) for ln in grid.split("\n"))
        pat = re.compile(rf"{text}\s+IFR")
        found: Any = None
        root = auto.ControlFromHandle(self.hwnd)
        queue: list[tuple[Any, int]] = [(root, 0)]
        seen = 0
        end = time.monotonic() + 60
        while queue and found is None and seen < 8000 and time.monotonic() < end:
            ctrl, depth = queue.pop(0)
            seen += 1
            with contextlib.suppress(Exception):
                if pat.search(ctrl.Name or ""):
                    found = ctrl
                    break
            if depth < 16:
                with contextlib.suppress(Exception):
                    queue.extend((c, depth + 1) for c in ctrl.GetChildren())
        self.rep.note("vscode uia search", f"nodes={seen} found={found is not None}")
        if found is None:
            return None
        r = found.BoundingRectangle
        left, top, right, bottom = int(r.left), int(r.top), int(r.right), int(r.bottom)
        idx = line.index(text)
        cell = (right - left) / cols
        return (round(left + idx * cell), top, round(left + (idx + len(text)) * cell), bottom)

    def window_gone(self) -> bool:
        return False  # VS Code stays open; the terminal returns to its prompt

    def quit_check(self) -> bool:
        def prompt_back() -> bool:
            text = self.read()
            return bool(re.search(r">\s*$", text.rstrip())) and not re.search(START_RE, text)

        w.wait_for(prompt_back, 25, "the cmd prompt to return and the TUI to be gone")
        return True


TERMS: dict[str, type[Term]] = {"conhost": Conhost, "wt": WindowsTerminal, "vscode": VSCode}


# ---------------------------------------------------------------------------------------------------------------------


def diagnostics(out: Path) -> dict[str, Any]:
    d: dict[str, Any] = {
        "python": sys.version.split()[0],
        "os": platform.platform(),
        "os_version": platform.version(),
        "screen": w.screen_size(),
        "idle_seconds": round(w.idle_seconds(), 1),
    }
    with contextlib.suppress(Exception):
        sid = w.wt.DWORD()
        w.kernel32.ProcessIdToSessionId(os.getpid(), w.ctypes.byref(sid))
        d["session_id"] = sid.value
    with contextlib.suppress(Exception):
        d["is_admin"] = bool(w.ctypes.windll.shell32.IsUserAnAdmin())
    with contextlib.suppress(Exception):
        d["dpi"] = int(w.user32.GetDpiForSystem())
    with contextlib.suppress(Exception):
        groups = subprocess.run(["whoami", "/groups"], capture_output=True, text=True, timeout=30).stdout
        d["integrity"] = ", ".join(re.findall(r"Mandatory Label\\\S+ \S+", groups))
    with contextlib.suppress(Exception):
        reg = subprocess.run(
            ["reg", "query", r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System", "/v", "EnableLUA"],
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout
        d["EnableLUA"] = reg.strip().split()[-1] if reg.strip() else "?"
    fg = w.foreground()
    d["foreground_window"] = str(w.window_info(fg)) if fg else "none"
    d["visible_top_level_windows"] = sum(1 for x in w.all_windows() if x.visible and x.title)
    with contextlib.suppress(Exception):
        d["console_cp"] = subprocess.run(
            ["cmd", "/c", "chcp"], capture_output=True, text=True, timeout=30
        ).stdout.strip()
    return d


def journey(t: Term, rep: Report) -> None:
    t.launch()
    t.prepare_window()
    text = str(w.wait_for(lambda: (s := t.read()) and re.search(START_RE, s) and s, 90, "the wxbrief list screen"))
    t.save_text("01-start", text)
    t.shot("01-start", printwindow=True)
    rep.check("app drawn", True, f"{len(text.splitlines())} lines read", critical=True)
    rep.check("initial selection is the first station", bool(re.search(INITIAL_RE, text)) and "KDEN" in text)
    uia = getattr(t, "_uia", None)
    if uia is not None:
        rep.note("uia text element", uia.describe())
    with contextlib.suppress(Exception):
        n = w.dump_uia_tree(t.hwnd, t.out / f"{t.name}-uia-tree.txt", max_depth=12, max_nodes=500)
        rep.note("uia tree", f"{n} nodes")

    def keys(label: str) -> str:
        w.focus(t.hwnd)
        sent = w.send_text(label) if label.isprintable() else 0
        rep.note(f"send {label!r}", f"{sent} input events inserted")
        time.sleep(1.2)
        t.after_keys()
        return t.read()

    after2 = keys("2")
    t.save_text("02-after-2", after2)
    t.shot("02-after-2")
    rep.note("key 2 changed the screen", str(after2 != text))

    after_v = keys("v")
    t.save_text("03-after-v", after_v)
    t.shot("03-after-v")
    rep.check(
        "v changes the layout (screen text differs)",
        after_v != after2,
        f"list title still shown={bool(re.search(START_RE, after_v))}",
    )
    back = keys("v")
    rep.check("v again returns to the list", bool(re.search(START_RE, back)))

    w.focus(t.hwnd)
    rect = None
    for _ in range(3):
        rect = t.rect_of(TARGET_ROW)
        if rect:
            break
        time.sleep(1)
    rep.check("located the row in pixels", rect is not None, f"rect of {TARGET_ROW!r} = {rect}", critical=True)
    assert rect
    cx, cy = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
    rep.note("click point", f"({cx}, {cy}) from rect {rect}; window {w.window_info(t.hwnd).rect}")
    inserted = w.click_at(cx, cy)
    rep.note("click", f"{inserted} mouse events inserted")
    time.sleep(1.5)
    t.after_keys()
    seen = ""

    def selected() -> bool:
        nonlocal seen
        seen = t.read()
        return all(re.search(p, seen) for p in AFTER_CLICK)

    try:
        w.wait_for(selected, 10, "the clicked row to be selected")
        rep.check("clicked row becomes selected (4/10 and UUEE detail header)", True)
    except TimeoutError:
        rep.check("clicked row becomes selected (4/10 and UUEE detail header)", False, "last screen saved")
    t.save_text("04-after-click", seen)
    t.shot("04-after-click", printwindow=True)

    w.focus(t.hwnd)
    w.send_text("q")
    time.sleep(0.5)
    try:
        t.quit_check()
        rep.check("q exits the app", True)
    except TimeoutError as exc:
        rep.check("q exits the app", False, str(exc))
    t.shot("05-after-q")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("terminal", choices=sorted(TERMS))
    ap.add_argument("--wxbrief", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--tool-exe", type=Path)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    rep = Report(args.terminal, args.out)
    rep.info = diagnostics(args.out)
    w.log(f"diagnostics: {json.dumps(rep.info)}")
    term = TERMS[args.terminal](
        rep, args.wxbrief.resolve(), args.out, args.tool_exe.resolve() if args.tool_exe else None
    )
    try:
        journey(term, rep)
    except Abort as exc:
        w.log(f"aborted at: {exc}")
    except Exception:
        rep.check("unexpected error", False, traceback.format_exc()[-1500:])
    finally:
        with contextlib.suppress(Exception):
            term.shot("99-before-teardown")
        with contextlib.suppress(Exception):
            term.teardown()
        rep.info["leftover_python_procs"] = len(
            [p for p in psutil.process_iter(["name"]) if p.info["name"] == "wxbrief.exe"]
        )
        rep.write()
    return 0 if rep.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
