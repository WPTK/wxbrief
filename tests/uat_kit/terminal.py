"""uat_kit: drive any terminal program through a real pseudo-terminal and read the screen back. No project imports.

The pilot-driven UAT in ``tests/uat`` feeds Textual key events and never touches the byte stream a terminal sends and
receives. This harness does: the program runs as a child of a pseudo-terminal (ConPTY through pywinpty on Windows, the
stdlib ``pty`` elsewhere), keys and mouse reports are written as the bytes a terminal emits (SGR mouse reports, pointer
motion before every click), and everything the program prints is fed to a pyte terminal emulator, so tests assert on
the rendered screen, not on app state.

Usage::

    from uat_kit import Terminal
    with Terminal(["myapp", "--config", "{dir}/c.toml"], cols=120, rows=30, env={"MYAPP_CACHE": "{dir}/cache"}) as t:
        t.wait_for_text("Stations", 30)       # polls the emulated screen; on timeout fails with a screen dump
        t.send_keys("down", "enter", "q")      # named keys or literal text, as the bytes a terminal sends
        t.click(10, 5); t.click_text("ETHB")   # SGR motion, press, release at 0-based cells
        t.resize(60, 16); t.settle(); print(t.screen_text()); t.wait_exit()

Safety: every child is killed by PID (with its process tree) when the terminal closes, and by an ``atexit`` hook; all
waits have a deadline; the environment is isolated (a scratch dir for config, cache and cwd, a dead proxy so no network
request can succeed). Pass ``env`` to add variables and ``env_remove`` to drop some.
"""

from __future__ import annotations

import atexit
import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psutil

try:
    import pyte
except ImportError:  # pragma: no cover - reported as a skip reason
    pyte = None  # type: ignore[assignment]

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    try:
        from winpty import PtyProcess
    except ImportError:  # pragma: no cover
        PtyProcess = None
else:
    import fcntl
    import pty as _pty
    import signal
    import struct
    import termios

ESC = "\x1b"
DEFAULT_TIMEOUT = 20.0

KEYS = {
    "enter": "\r",
    "escape": ESC,
    "esc": ESC,
    "tab": "\t",
    "shift+tab": f"{ESC}[Z",
    "up": f"{ESC}[A",
    "down": f"{ESC}[B",
    "right": f"{ESC}[C",
    "left": f"{ESC}[D",
    "home": f"{ESC}[H",
    "end": f"{ESC}[F",
    "pageup": f"{ESC}[5~",
    "pagedown": f"{ESC}[6~",
    "space": " ",
}


def unavailable_reason() -> str | None:
    """Why the real-terminal layer cannot run here, or None when it can."""
    if pyte is None:
        return "pyte is not installed (pip install -e '.[dev]')"
    if IS_WINDOWS and PtyProcess is None:
        return "pywinpty is not installed or has no ConPTY (pip install -e '.[dev]')"
    return None


@dataclass(frozen=True)
class Screen:
    """A snapshot of the emulated screen."""

    lines: tuple[str, ...]

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    def __contains__(self, item: str) -> bool:
        return item in self.text

    def find(self, needle: str) -> tuple[int, int] | None:
        """(column, row), both 0-based, of the first place ``needle`` appears, or None."""
        for row, line in enumerate(self.lines):
            col = line.find(needle)
            if col >= 0:
                return col, row
        return None

    def rows_with(self, needle: str) -> list[int]:
        return [row for row, line in enumerate(self.lines) if needle in line]


class Terminal:
    """The program running in a pseudo-terminal of ``cols`` x ``rows`` cells."""

    def __init__(
        self,
        argv: list[str],
        cols: int = 120,
        rows: int = 30,
        *,
        env: dict[str, str] | None = None,
        env_remove: tuple[str, ...] = (),
        cwd: Path | None = None,
        isolate: bool = True,
    ) -> None:
        reason = unavailable_reason()
        if reason:
            raise RuntimeError(reason)
        self.cols, self.rows = cols, rows
        self._dir = Path(tempfile.mkdtemp(prefix="uat-kit-"))
        self._lock = threading.Condition()
        self._screen = pyte.Screen(cols, rows)
        self._stream = pyte.Stream(self._screen)
        self._raw = bytearray()
        self._eof = False
        self._closed = False
        self.exit_code: int | None = None
        self.dir = self._dir  # a scratch directory the caller may use for config files; removed on close
        self._extra_env = {
            k: v.replace("{dir}", str(self._dir)) for k, v in (env or {}).items()
        }  # "{dir}" = scratch dir
        self._env_remove, self._isolate = env_remove, isolate
        self._cwd = cwd or self._dir
        self._start(argv)
        _LIVE.add(self)
        self._thread = threading.Thread(target=self._pump, name="pty-reader", daemon=True)
        self._thread.start()

    # -- process ----------------------------------------------------------------------------------------------------

    def _env(self) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith("PYTEST") and k not in self._env_remove}
        env.update(TERM="xterm-256color", COLORTERM="truecolor", PYTHONUNBUFFERED="1")
        if not self._isolate:
            env.update(self._extra_env)
            return env
        dead = "http://127.0.0.1:9"  # nothing listens on the discard port: a request fails at once
        env.update(
            XDG_CONFIG_HOME=str(self._dir / "xdg-config"),
            XDG_CACHE_HOME=str(self._dir / "xdg-cache"),
            XDG_DATA_HOME=str(self._dir / "xdg-data"),
            HTTP_PROXY=dead,
            HTTPS_PROXY=dead,
            ALL_PROXY=dead,
            http_proxy=dead,
            https_proxy=dead,
            all_proxy=dead,
            NO_PROXY="",
            no_proxy="",
        )
        if IS_WINDOWS:
            env.update(APPDATA=str(self._dir / "appdata"), LOCALAPPDATA=str(self._dir / "localappdata"))
        env.update(self._extra_env)
        return env

    def _start(self, argv: list[str]) -> None:
        argv = [a.replace("{dir}", str(self._dir)) for a in argv]
        env = self._env()
        self._proc: Any
        if IS_WINDOWS:
            self._proc = PtyProcess.spawn(argv, cwd=str(self._cwd), env=env, dimensions=(self.rows, self.cols))
            self.pid: int = self._proc.pid
        else:
            master, slave = _pty.openpty()
            self._master = master
            self._set_winsize()

            def adopt() -> None:  # runs in the child: the slave becomes its controlling terminal
                os.setsid()
                fcntl.ioctl(0, termios.TIOCSCTTY, 0)

            self._popen = subprocess.Popen(
                argv, stdin=slave, stdout=slave, stderr=slave, cwd=self._cwd, env=env, preexec_fn=adopt, close_fds=True
            )
            os.close(slave)
            self.pid = self._popen.pid

    def _set_winsize(self) -> None:
        fcntl.ioctl(self._master, termios.TIOCSWINSZ, struct.pack("HHHH", self.rows, self.cols, 0, 0))

    def _pump(self) -> None:
        while True:
            try:
                chunk = self._proc.read(65536) if IS_WINDOWS else os.read(self._master, 65536)
            except (EOFError, OSError):
                break
            if not chunk:
                if IS_WINDOWS and self._proc.isalive():
                    time.sleep(0.01)
                    continue
                break
            data = chunk.decode("utf-8", "replace") if isinstance(chunk, bytes) else chunk
            with self._lock:
                self._raw.extend(data.encode("utf-8", "replace"))
                self._stream.feed(data)
                self._lock.notify_all()
        with self._lock:
            self._eof = True
            self._lock.notify_all()

    def alive(self) -> bool:
        try:
            p = psutil.Process(self.pid)
            return p.is_running() and p.status() != psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            return False

    def wait_exit(self, timeout: float = DEFAULT_TIMEOUT) -> int | None:
        """Wait for the program to end on its own; its exit code, or None on timeout."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if IS_WINDOWS:
                if not self._proc.isalive():
                    self.exit_code = self._proc.exitstatus
                    return self.exit_code
            else:
                code = self._popen.poll()
                if code is not None:
                    self.exit_code = code
                    return code
            time.sleep(0.05)
        return None

    def kill(self) -> None:
        """End the child and everything it started, by PID."""
        try:
            parent = psutil.Process(self.pid)
            procs = [*parent.children(recursive=True), parent]
        except psutil.NoSuchProcess:
            return
        for p in procs:
            with contextlib.suppress(psutil.NoSuchProcess):
                p.kill()
        psutil.wait_procs(procs, timeout=5)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.kill()
        if IS_WINDOWS:
            with contextlib.suppress(Exception):
                self._proc.close(force=True)
        else:
            with contextlib.suppress(Exception):
                self._popen.wait(timeout=5)
            with contextlib.suppress(OSError):
                os.close(self._master)
        self._thread.join(timeout=5)
        _LIVE.discard(self)
        shutil.rmtree(self._dir, ignore_errors=True)

    def __enter__(self) -> Terminal:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- input ------------------------------------------------------------------------------------------------------

    def send_raw(self, data: str) -> None:
        if IS_WINDOWS:
            self._proc.write(data)
        else:
            os.write(self._master, data.encode("utf-8"))

    def send_keys(self, *keys: str) -> None:
        """Each argument is a named key (``"enter"``, ``"escape"``, ``"down"``) or literal text typed as is."""
        for key in keys:
            self.send_raw(KEYS.get(key.lower(), key))
            time.sleep(0.08)  # a person is never faster; lets the app handle one key before the next

    def mouse(self, kind: str, col: int, row: int) -> None:
        """One SGR (1006) mouse report at 0-based cell (col, row): ``move``, ``press``, ``release``, wheel."""
        code, final = {
            "move": (35, "M"),  # any-motion with no button held: a terminal sends this before every click
            "press": (0, "M"),
            "release": (0, "m"),
            "wheel_up": (64, "M"),
            "wheel_down": (65, "M"),
        }[kind]
        self.send_raw(f"{ESC}[<{code};{col + 1};{row + 1}{final}")

    def click(self, col: int, row: int) -> None:
        """Move the pointer in, press and release the left button, as a real terminal reports a click."""
        for kind, c in (("move", max(col - 4, 0)), ("move", max(col - 1, 0)), ("move", col)):
            self.mouse(kind, c, row)
            time.sleep(0.03)
        self.mouse("press", col, row)
        time.sleep(0.06)
        self.mouse("release", col, row)
        time.sleep(0.06)

    def click_text(self, needle: str) -> tuple[int, int]:
        """Click in the middle of the first place ``needle`` is on screen; returns the cell."""
        found = self.screen().find(needle)
        if found is None:
            raise AssertionError(f"{needle!r} is not on screen:\n{self.screen_text()}")
        col, row = found[0] + len(needle) // 2, found[1]
        self.click(col, row)
        return col, row

    def focus(self, gained: bool = True) -> None:
        self.send_raw(f"{ESC}[{'I' if gained else 'O'}")

    def resize(self, cols: int, rows: int) -> None:
        with self._lock:
            self.cols, self.rows = cols, rows
            self._screen.resize(rows, cols)
        if IS_WINDOWS:
            self._proc.setwinsize(rows, cols)
        else:
            self._set_winsize()
            os.killpg(os.getpgid(self.pid), signal.SIGWINCH)

    # -- output -----------------------------------------------------------------------------------------------------

    def screen(self) -> Screen:
        with self._lock:
            return Screen(tuple(line.rstrip() for line in self._screen.display))

    def screen_text(self) -> str:
        return self.screen().text

    def wait_for(self, predicate: Callable[[Screen], bool], timeout: float = DEFAULT_TIMEOUT, what: str = "") -> Screen:
        """Block until ``predicate(screen)`` is true; on timeout fail with the screen as it was."""
        deadline = time.monotonic() + timeout
        with self._lock:
            while True:
                snap = Screen(tuple(line.rstrip() for line in self._screen.display))
                if predicate(snap):
                    return snap
                remaining = deadline - time.monotonic()
                if remaining <= 0 or self._eof:
                    break
                self._lock.wait(min(remaining, 0.1))
        label = what or getattr(predicate, "__name__", "condition")
        state = "still running" if self.alive() else "the program has exited"
        raise AssertionError(f"timed out after {timeout:g} s waiting for {label} ({state}). Screen:\n{snap.text}")

    def wait_for_text(self, text: str, timeout: float = DEFAULT_TIMEOUT) -> Screen:
        return self.wait_for(lambda s: text in s, timeout, f"{text!r} on screen")

    def settle(self, quiet: float = 0.4, timeout: float = 10.0) -> Screen:
        """Wait until the output has been quiet for ``quiet`` seconds (the program is idle), then the screen."""
        deadline = time.monotonic() + timeout
        with self._lock:
            last = len(self._raw)
            stamp = time.monotonic()
            while time.monotonic() < deadline:
                self._lock.wait(0.05)
                if len(self._raw) != last:
                    last, stamp = len(self._raw), time.monotonic()
                elif time.monotonic() - stamp >= quiet:
                    break
        return self.screen()

    def hold(self, seconds: float) -> None:
        """Let real time pass (for a stability check, where the point is that time passes)."""
        time.sleep(seconds)


_LIVE: set[Terminal] = set()


def _reap() -> None:
    for term in list(_LIVE):
        term.close()


atexit.register(_reap)
