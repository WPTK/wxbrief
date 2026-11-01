"""Drive a program in a real Terminal.app or iTerm2 window with real input.

Keys and clicks are posted to the window server by ``cliclick`` (no tmux send-keys, no pty writes); the window is found
with Quartz; screenshots are ``screencapture -l``; the screen text is read back through the terminal itself
(AppleScript ``contents`` for Terminal.app, the ``iterm2`` Python API for iTerm2).

Usage::

    with MacTerminal(["python", "-m", "myapp"], 110, 36, app="Terminal") as t:
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
    bounds: tuple[float, float, float, float], size: tuple[int, int], col: int, row: int
) -> tuple[int, int]:
    """Screen point at the centre of 0-based cell (col, row) of a window; ``size`` is (cols, rows)."""
    x, y, w, h = bounds
    cols, rows = size
    return round(x + (col + 0.5) * w / cols), round(y + TITLE_BAR + (row + 0.5) * (h - TITLE_BAR) / rows)


def _sh(cmd: list[str], timeout: float = 30) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout:g} s: {cmd[0]}"
    return p.returncode, (p.stdout + p.stderr).strip()


def _osa(script: str, timeout: float = 30) -> tuple[int, str]:
    return _sh(["osascript", "-e", script], timeout)


class MacTerminal:
    """``argv`` running in a real ``app`` ("Terminal" or "iTerm2") window of about ``cols`` x ``rows`` cells."""

    def __init__(
        self,
        argv: list[str],
        cols: int = 110,
        rows: int = 36,
        *,
        app: str = "Terminal",
        env: dict[str, str] | None = None,
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
        _sh(["pkill", "-x", self._spec["process"]])
        time.sleep(1)
        # inner.sh runs the program as a child, publishes the window size (for geometry) and the exit code.
        lines = ["#!/bin/bash", f"cd {shlex.quote(str(self.dir))}", "export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8"]
        for k, v in (env or {}).items():
            lines.append(f"export {k}={shlex.quote(v.replace('{dir}', str(self.dir)))}")
        lines += [
            "( while [ ! -e exitcode ]; do stty size < /dev/tty > size.tmp 2>/dev/null && mv size.tmp size; sleep 0.3; done ) &",
            " ".join(shlex.quote(a.replace("{dir}", str(self.dir))) for a in argv),
            "echo $? > exitcode",
            "sleep 3600",
        ]
        inner = self.dir / "inner.sh"
        inner.write_text("\n".join(lines) + "\n")
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
            self._fit(cols, rows)
        except BaseException:
            self.close()
            raise

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

    def _window(self) -> tuple[int, tuple[float, float, float, float]]:
        import Quartz

        best: tuple[float, int, tuple[float, float, float, float]] | None = None
        for w in Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID):
            if w.get("kCGWindowOwnerName") == self._spec["owner"] and w.get("kCGWindowLayer") == 0:
                b = w["kCGWindowBounds"]
                area = b["Width"] * b["Height"]
                if area > 20000 and (best is None or area > best[0]):
                    best = (area, int(w["kCGWindowNumber"]), (b["X"], b["Y"], b["Width"], b["Height"]))
        if best is None:
            raise AssertionError(f"no on-screen {self.app} window")
        return best[1], best[2]

    def _fit(self, cols: int, rows: int) -> None:
        """Set the window bounds until the terminal reports ``cols`` x ``rows`` (cell size is measured, not assumed)."""
        for _ in range(5):
            cur = self._wait_size()
            if cur == (cols, rows):
                self.cols, self.rows = cols, rows
                return
            _, (_, _, w, h) = self._window()
            cw, ch = w / cur[0], (h - TITLE_BAR) / cur[1]
            x, y = ORIGIN
            nw, nh = round((cols + 0.4) * cw), round((rows + 0.4) * ch + TITLE_BAR)
            target = "front window" if self.app == "Terminal" else "current window"
            _osa(f"tell {self._spec['scripting']} to set bounds of {target} to {{{x}, {y}, {x + nw}, {y + nh}}}")
            time.sleep(1)
        raise AssertionError(f"{self.app}: could not reach {cols}x{rows}, the terminal reports {self._size()}")

    # -- input ------------------------------------------------------------------------------------------------------

    def _activate(self) -> None:
        _osa(f"tell {self._spec['scripting']} to activate")
        time.sleep(0.5)

    def send_keys(self, *keys: str) -> None:
        """Each argument is a named key (``"enter"``, ``"escape"``, ``"down"``) or literal text typed as is."""
        self._activate()
        for key in keys:
            named = KEYS.get(key.lower())
            rc, out = _sh(["cliclick", f"kp:{named}"] if named else ["cliclick", f"t:{key}"])
            if rc != 0:
                raise AssertionError(f"cliclick failed for key {key!r}: {out}")
            time.sleep(0.15)

    def click(self, col: int, row: int) -> None:
        """Move the pointer to the middle of cell (col, row), press and release the left button."""
        self._activate()
        size = self._wait_size()
        _, bounds = self._window()
        x, y = cell_center(bounds, size, col, row)
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
        lines = [line.rstrip() for line in out.replace("\r", "\n").split("\n")]
        if len(lines) > self.rows:  # Terminal.app returns scrollback above the screen
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
        wid, _ = self._window()
        png = stem.with_suffix(".png")
        rc, out = _sh(["screencapture", "-x", "-o", "-l", str(wid), str(png)])
        if rc != 0:
            raise AssertionError(f"screencapture failed: {out}")
        return png

    # -- lifetime ---------------------------------------------------------------------------------------------------

    @property
    def exit_code(self) -> int | None:
        try:
            return int((self.dir / "exitcode").read_text().strip())
        except (OSError, ValueError):
            return None

    def alive(self) -> bool:
        return self.exit_code is None

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
        (self.dir / "exitcode").touch()  # stops the size watcher
        _osa(f"tell {self._spec['scripting']} to quit", 10)
        time.sleep(1)
        _sh(["pkill", "-x", self._spec["process"]])
        if self.out_dir != self.dir:
            shutil.rmtree(self.dir, ignore_errors=True)

    def __enter__(self) -> MacTerminal:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
