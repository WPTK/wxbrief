"""Drive a program in a real Terminal.app or iTerm2 window with real input.

Keys and clicks are posted to the window server by ``cliclick`` (no tmux send-keys, no pty writes); the window is found
with Quartz; screenshots are ``screencapture -l``; the screen text is read back through the terminal itself
(AppleScript ``contents`` for Terminal.app, the ``iterm2`` Python API for iTerm2).

One terminal window is started once and can run several programs one after another (``run``): launching iTerm2 twice
in one job is the part that is least proven on the hosted runners.

Usage::

    with MacTerminal(110, 36, app="Terminal") as t:
        t.run(["python", "-m", "myapp"])
        t.wait_for_text("Ready", 30)
        t.send_keys("2", "enter")
        t.click_text("Stations")
        t.screenshot("after-click")
        t.resize(90, 30)
        t.send_keys("q"); t.wait_exit()
"""

from __future__ import annotations

import contextlib
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from uat_kit.terminal import Screen

TITLE_BAR = 28.0  # points; measured on macos-15 and macos-26 (eyewall S4), Terminal.app and iTerm2
PAD = (4.0, 2.0)  # left and top padding inside the window, in points (a guess; a click lands mid-cell, so +-3 is fine)
ORIGIN = (40, 60)  # window top-left in screen points
HERE = Path(__file__).resolve().parent
APPS = {
    "Terminal": {"scripting": 'application "Terminal"', "owner": "Terminal", "process": "Terminal"},
    "iTerm2": {"scripting": 'application id "com.googlecode.iterm2"', "owner": "iTerm2", "process": "iTerm2"},
}
KEYS = {
    "enter": "enter",
    "return": "return",
    "escape": "esc",
    "esc": "esc",
    "tab": "tab",
    "space": "space",
    "up": "arrow-up",
    "down": "arrow-down",
    "left": "arrow-left",
    "right": "arrow-right",
    "home": "home",
    "end": "end",
    "pageup": "page-up",
    "pagedown": "page-down",
}
Bounds = tuple[float, float, float, float]


def unavailable_reason() -> str | None:
    """Why real-terminal driving cannot run here, or None when it can."""
    if sys.platform != "darwin":
        return "needs macOS"
    if shutil.which("cliclick") is None:
        return "cliclick is not installed (brew install cliclick)"
    try:
        import Quartz  # noqa: F401
    except ImportError:
        return "pyobjc-framework-Quartz is not installed"
    return None


def cell_center(
    bounds: Bounds, size: tuple[int, int], col: int, row: int, cell: tuple[float, float] | None = None
) -> tuple[int, int]:
    """Screen point at the centre of 0-based cell (col, row) of a window; ``size`` is (cols, rows).

    With a measured ``cell`` (width, height in points) the grid starts at the window padding. Without one, the window
    is divided evenly, which overshoots on the right when the window has a scroller (Terminal.app).
    """
    x, y, w, h = bounds
    cols, rows = size
    if cell is not None:
        return round(x + PAD[0] + (col + 0.5) * cell[0]), round(y + TITLE_BAR + PAD[1] + (row + 0.5) * cell[1])
    return round(x + (col + 0.5) * w / cols), round(y + TITLE_BAR + (row + 0.5) * (h - TITLE_BAR) / rows)


def cell_size(samples: list[tuple[float, float, int, int]]) -> tuple[float, float] | None:
    """Cell width and height from (window width, window height, cols, rows) samples taken at different sizes."""
    if len(samples) < 2:
        return None
    lo_c, hi_c = min(samples, key=lambda s: s[2]), max(samples, key=lambda s: s[2])
    lo_r, hi_r = min(samples, key=lambda s: s[3]), max(samples, key=lambda s: s[3])
    if hi_c[2] - lo_c[2] < 3 or hi_r[3] - lo_r[3] < 3:
        return None
    return (hi_c[0] - lo_c[0]) / (hi_c[2] - lo_c[2]), (hi_r[1] - lo_r[1]) / (hi_r[3] - lo_r[3])


def _sh(cmd: list[str], timeout: float = 30) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout:g} s: {cmd[0]}"
    return p.returncode, (p.stdout + p.stderr).strip()


def _osa(script: str, timeout: float = 30) -> tuple[int, str]:
    return _sh(["osascript", "-e", script], timeout)


class MacTerminal:
    """A real ``app`` ("Terminal" or "iTerm2") window of about ``cols`` x ``rows`` cells, running programs one at a time."""

    def __init__(
        self,
        cols: int = 110,
        rows: int = 36,
        *,
        app: str = "Terminal",
        out_dir: Path | None = None,
    ) -> None:
        reason = unavailable_reason()
        if reason:
            raise RuntimeError(reason)
        if app not in APPS:
            raise ValueError(f"app must be one of {sorted(APPS)}")
        self.app, self.cols, self.rows = app, cols, rows
        self._spec = APPS[app]
        self.dir = Path(tempfile.mkdtemp(prefix="uat-macos-"))
        self.out_dir = out_dir or self.dir
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._closed = False
        self._shots = 0
        self._runs = 0
        self._samples: list[tuple[float, float, int, int]] = []
        _sh(["pkill", "-x", self._spec["process"]])
        time.sleep(1)
        # inner.sh publishes the window size (for geometry) and runs each queued script in the foreground, one by one,
        # recording its exit code. The window stays open between programs.
        inner = self.dir / "inner.sh"
        inner.write_text(
            "\n".join(
                [
                    "#!/bin/bash",
                    f"cd {shlex.quote(str(self.dir))}",
                    "export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8",
                    "( while [ ! -e stop ]; do stty size < /dev/tty > size.tmp 2>/dev/null && mv size.tmp size; sleep 0.3; done ) &",
                    "n=1",
                    "while [ ! -e stop ]; do",
                    '  if [ -e "run.$n" ]; then bash "run.$n"; echo $? > "done.$n"; n=$((n + 1)); else sleep 0.2; fi',
                    "done",
                    "",
                ]
            )
        )
        inner.chmod(0o755)
        x, y = ORIGIN
        bounds = f"{{{x}, {y}, {x + 860}, {y + 600}}}"
        if app == "Terminal":
            script = f'tell application "Terminal"\nactivate\ndo script "{inner}"\nset bounds of front window to {bounds}\nend tell'
        else:
            # iTerm2 opens a window on launch; reuse it (closing it first sends input to a new empty window).
            _sh(["open", "-a", "iTerm"])
            time.sleep(8)
            _sh([sys.executable, str(HERE / "scripts" / "dismiss_dialogs.py"), "1"], timeout=120)
            script = (
                f"tell {self._spec['scripting']}\nactivate\n"
                "if (count of windows) is 0 then create window with default profile\n"
                f'tell current session of current window to write text "exec /bin/bash {inner}"\n'
                f"set bounds of current window to {bounds}\nend tell"
            )
        rc, out = _osa(script, 40)
        if rc != 0:
            self.close()
            raise RuntimeError(f"could not start {app} (osascript rc={rc}): {out}")
        try:
            self._wait_size()
            self._fit(cols - 30, rows - 10)  # a second, very different size: the cell size is the slope between the two
            self._fit(cols, rows)
            self._focus()
        except BaseException:
            self.close()
            raise

    def run(self, argv: list[str], env: dict[str, str] | None = None) -> None:
        """Start ``argv`` in the window (after clearing it). ``{dir}`` in an argument or value is the scratch directory."""
        if self.alive():
            raise RuntimeError("the previous program is still running")
        self._runs += 1
        lines = ["printf '\\033[3J\\033[H\\033[2J'"]
        for k, v in (env or {}).items():
            lines.append(f"export {k}={shlex.quote(v.replace('{dir}', str(self.dir)))}")
        lines.append(" ".join(shlex.quote(a.replace("{dir}", str(self.dir))) for a in argv))
        tmp = self.dir / f"run.{self._runs}.tmp"
        tmp.write_text("\n".join(lines) + "\n")
        tmp.rename(self.dir / f"run.{self._runs}")

    # -- geometry ---------------------------------------------------------------------------------------------------

    def _size(self) -> tuple[int, int] | None:
        try:
            rows, cols = (int(v) for v in (self.dir / "size").read_text().split())
        except (OSError, ValueError):
            return None
        return cols, rows

    def _wait_size(self, timeout: float = 40.0) -> tuple[int, int]:
        """Wait until the terminal reports a size that has stopped changing."""
        deadline = time.monotonic() + timeout
        last, stable = None, 0
        while time.monotonic() < deadline:
            cur = self._size()
            stable = stable + 1 if cur is not None and cur == last else 0
            last = cur
            if stable >= 3 and last is not None:
                return last
            time.sleep(0.5)
        raise AssertionError(f"{self.app}: the terminal did not report a stable size in {timeout:g} s")

    def _window(self, timeout: float = 15.0) -> tuple[int, Bounds]:
        import Quartz

        deadline = time.monotonic() + timeout
        while True:
            best: tuple[float, int, Bounds] | None = None
            seen = []
            for w in Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID):
                b = w["kCGWindowBounds"]
                seen.append(
                    f"{w.get('kCGWindowOwnerName')}/layer {w.get('kCGWindowLayer')}/{b['Width']:g}x{b['Height']:g}"
                )
                if w.get("kCGWindowOwnerName") == self._spec["owner"] and w.get("kCGWindowLayer") == 0:
                    area = b["Width"] * b["Height"]
                    if area > 20000 and (best is None or area > best[0]):
                        best = (area, int(w["kCGWindowNumber"]), (b["X"], b["Y"], b["Width"], b["Height"]))
            if best is not None:
                return best[1], best[2]
            if time.monotonic() >= deadline:
                raise AssertionError(
                    f"no on-screen {self.app} window after {timeout:g} s; on screen: {'; '.join(seen)}"
                )
            time.sleep(0.5)

    def _measure(self) -> tuple[tuple[int, int], Bounds]:
        """The settled size and window bounds. A pair is kept (for the cell size) only if both held still for a moment."""
        size = self._wait_size()
        _, bounds = self._window()
        time.sleep(0.7)
        if self._size() == size and self._window()[1] == bounds:
            self._samples.append((bounds[2], bounds[3], size[0], size[1]))
        return size, bounds

    def _fit(self, cols: int, rows: int) -> None:
        """Set the window bounds until the terminal reports ``cols`` x ``rows``; the window is the cell grid plus padding.

        The extra width/height (in cells) is searched: grown while the terminal reports too few cells, shrunk while
        too many, so a scroller or padding of unknown size cannot leave it one cell off.
        """
        mw = mh = 0.4
        for _ in range(12):
            cur, (_, _, w, h) = self._measure()
            with (self.out_dir / "fit.log").open("a") as f:
                f.write(f"want {(cols, rows)} reported {cur} window {(w, h)} margins {(mw, mh)}\n")
            if cur == (cols, rows):
                self.cols, self.rows = cols, rows
                return
            cw, ch = w / cur[0], (h - TITLE_BAR) / cur[1]
            mw += 0.3 if cur[0] < cols else -0.3 if cur[0] > cols else 0
            mh += 0.3 if cur[1] < rows else -0.3 if cur[1] > rows else 0
            nw, nh = round((cols + mw) * cw), round((rows + mh) * ch + TITLE_BAR)
            x, y = ORIGIN
            target = "front window" if self.app == "Terminal" else "current window"
            _osa(f"tell {self._spec['scripting']} to set bounds of {target} to {{{x}, {y}, {x + nw}, {y + nh}}}")
            time.sleep(1)
        raise AssertionError(f"{self.app}: could not reach {cols}x{rows}, the terminal reports {self._size()}")

    # -- input ------------------------------------------------------------------------------------------------------

    def _focus(self) -> None:
        """Click the title bar: activating an iTerm2 window does not make it the key window, so the first keys were lost."""
        _, (x, y, w, _) = self._window()
        _sh(["cliclick", f"c:{round(x + w / 2)},{round(y + TITLE_BAR / 2)}"])
        time.sleep(0.5)

    def _activate(self) -> None:
        _osa(f"tell {self._spec['scripting']} to activate")
        time.sleep(0.5)

    def send_keys(self, *keys: str) -> None:
        """Each argument is a named key (``"enter"``, ``"escape"``, ``"down"``) or literal text typed as is."""
        self._activate()
        for key in keys:
            named = KEYS.get(key.lower())
            if key.lower() == "ctrl+c":
                cmd = ["cliclick", "kd:ctrl", "t:c", "ku:ctrl"]
            else:
                cmd = ["cliclick", f"kp:{named}"] if named else ["cliclick", f"t:{key}"]
            rc, out = _sh(cmd)
            if rc != 0:
                raise AssertionError(f"cliclick failed for key {key!r}: {out}")
            time.sleep(0.15)

    def click(self, col: int, row: int) -> None:
        """Move the pointer to the middle of cell (col, row), press and release the left button."""
        self._activate()
        size, bounds = self._measure()
        cell = cell_size(self._samples)
        x, y = cell_center(bounds, size, col, row, cell)
        with (self.out_dir / "clicks.log").open("a") as f:
            f.write(f"cell ({col},{row}) -> point ({x},{y}) window {bounds} size {size} cell {cell}\n")
        rc, out = _sh(["cliclick", f"m:{x},{y}", "w:150", f"c:{x},{y}"])
        if rc != 0:
            raise AssertionError(f"cliclick failed for click at {(x, y)}: {out}")
        time.sleep(0.3)

    def click_text(self, needle: str) -> tuple[int, int]:
        """Click in the middle of the first place ``needle`` is on screen; returns the cell."""
        found = self.screen().find(needle)
        if found is None:
            raise AssertionError(f"{needle!r} is not on screen:\n{self.screen_text()}")
        col, row = found[0] + len(needle) // 2, found[1]
        self.click(col, row)
        return col, row

    def resize(self, cols: int, rows: int) -> None:
        """Resize the real window until the terminal reports the new size."""
        self._fit(cols, rows)

    # -- output -----------------------------------------------------------------------------------------------------

    def screen(self) -> Screen:
        if self.app == "Terminal":
            rc, out = _osa('tell application "Terminal" to get contents of selected tab of front window')
        else:
            rc, out = _sh([sys.executable, str(HERE / "scripts" / "iterm_readback.py")], 30)
        if rc != 0:
            raise AssertionError(f"{self.app} read-back failed (rc={rc}): {out}")
        # Terminal.app keeps cells right of the current width after a resize, and returns scrollback above the screen.
        lines = [line[: self.cols].rstrip() for line in out.replace("\r", "\n").split("\n")]
        if len(lines) > self.rows:
            lines = lines[-self.rows :]
        return Screen(tuple((lines + [""] * self.rows)[: self.rows]))

    def screen_text(self) -> str:
        return self.screen().text

    def wait_for(self, predicate: Callable[[Screen], bool], timeout: float = 20.0, what: str = "") -> Screen:
        """Poll until ``predicate(screen)`` is true; on timeout fail with the screen as it was."""
        deadline = time.monotonic() + timeout
        while True:
            snap = self.screen()
            if predicate(snap):
                return snap
            if time.monotonic() >= deadline:
                break
            time.sleep(0.4)
        label = what or getattr(predicate, "__name__", "condition")
        state = "still running" if self.alive() else "the program has exited"
        raise AssertionError(f"timed out after {timeout:g} s waiting for {label} ({state}). Screen:\n{snap.text}")

    def wait_for_text(self, text: str, timeout: float = 20.0) -> Screen:
        return self.wait_for(lambda s: text in s, timeout, f"{text!r} on screen")

    def settle(self, quiet: float = 0.8, timeout: float = 10.0) -> Screen:
        """Wait until the screen has not changed for ``quiet`` seconds, then return it."""
        deadline = time.monotonic() + timeout
        last, stamp = self.screen(), time.monotonic()
        while time.monotonic() < deadline:
            time.sleep(0.2)
            now = self.screen()
            if now != last:
                last, stamp = now, time.monotonic()
            elif time.monotonic() - stamp >= quiet:
                break
        return last

    def screenshot(self, name: str) -> Path:
        """Save a PNG of the terminal window (``screencapture -l``) and the screen text next to it."""
        self._shots += 1
        stem = self.out_dir / f"{self._shots:02d}_{name}"
        with contextlib.suppress(AssertionError):
            stem.with_suffix(".txt").write_text(self.screen_text())
        png = stem.with_suffix(".png")
        out = ""
        for _ in range(3):
            wid, _ = self._window()
            rc, out = _sh(["screencapture", "-x", "-o", "-l", str(wid), str(png)])
            if rc == 0:
                return png
            time.sleep(1)
        # Evidence must not fail a step: record the error and take the whole screen instead.
        with (self.out_dir / "screenshot_errors.txt").open("a") as f:
            f.write(f"{png.name}: screencapture -l failed 3 times: {out}\n")
        _sh(["screencapture", "-x", str(png)])
        return png

    # -- lifetime ---------------------------------------------------------------------------------------------------

    @property
    def exit_code(self) -> int | None:
        """The exit code of the current program, or None while it runs (or when none was started)."""
        try:
            return int((self.dir / f"done.{self._runs}").read_text().strip())
        except (OSError, ValueError):
            return None

    def alive(self) -> bool:
        """True while the current program runs."""
        return self._runs > 0 and not (self.dir / f"done.{self._runs}").exists()

    def wait_exit(self, timeout: float = 20.0) -> int:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            code = self.exit_code
            if code is not None:
                return code
            time.sleep(0.2)
        raise AssertionError(f"the program is still running after {timeout:g} s. Screen:\n{self.screen_text()}")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        (self.dir / "stop").touch()  # stops the size watcher and the run loop
        _osa(f"tell {self._spec['scripting']} to quit", 10)
        time.sleep(1)
        _sh(["pkill", "-x", self._spec["process"]])
        if self.out_dir != self.dir:
            shutil.rmtree(self.dir, ignore_errors=True)

    def __enter__(self) -> MacTerminal:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
