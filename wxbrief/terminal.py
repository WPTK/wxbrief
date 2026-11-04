"""Leaving the terminal as it was found.

Textual switches the alternate screen, mouse tracking, focus reporting and bracketed paste on and writes the matching
"off" codes when the app ends normally. That write is queued on a writer thread: a signal that ends the process, or a
console that drops the last codes (focus reporting on Windows), skips it. ``restore`` is the same set of "off" codes
written straight to the terminal, safe to send twice and to a terminal that never had a mode on.
"""

from __future__ import annotations

import contextlib
import os
import signal
import sys
import threading
from collections.abc import Iterator
from types import FrameType
from typing import TYPE_CHECKING, TextIO

if TYPE_CHECKING:
    from wxbrief.app import WxBriefApp

RESET = (
    "\x1b[<u"  # kitty keyboard protocol off, before leaving the alternate screen
    "\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1005l\x1b[?1006l\x1b[?1015l\x1b[?1016l"  # every mouse mode
    "\x1b[?1004l"  # focus reporting
    "\x1b[?2004l"  # bracketed paste
    "\x1b[?2048l"  # in-band window resize
    "\x1b[?7h"  # line wrap back on
    "\x1b[?1049l"  # alternate screen
    "\x1b[?25h"  # cursor visible
)


def restore(stream: TextIO | None = None) -> None:
    """Write the codes that switch every mode the app turned on back off. Never raises: there may be no terminal."""
    out = stream if stream is not None else sys.__stdout__
    with contextlib.suppress(Exception):
        if out is not None and out.isatty():
            out.write(RESET)
            out.flush()


EXIT_GRACE = 3.0  # seconds the app gets to close after a signal before the process is ended anyway

_SIGNALS = tuple(
    getattr(signal, name) for name in ("SIGTERM", "SIGHUP", "SIGBREAK") if hasattr(signal, name)
)  # SIGHUP does not exist on Windows; SIGBREAK is Ctrl-Break and the console closing there


@contextlib.contextmanager
def restore_on_exit(app: WxBriefApp) -> Iterator[None]:
    """Around ``app.run()``: a terminating signal asks the app to exit, and the terminal is restored however it ends.

    Python's default for SIGTERM and SIGHUP ends the process on the spot, with the modes still on. The handler restores
    the terminal first (the process may not get another turn), then lets the app close the usual way.
    """
    previous: dict[int, object] = {}

    def on_signal(number: int, frame: FrameType | None) -> None:
        restore()
        loop = getattr(app, "_loop", None)
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(app.exit, None, 128 + number)
            watchdog = threading.Timer(EXIT_GRACE, os._exit, (128 + number,))
            watchdog.daemon = True
            watchdog.start()
        else:  # not running yet: nothing to close
            raise SystemExit(128 + number)

    for number in _SIGNALS:
        with contextlib.suppress(ValueError, OSError):  # not the main thread, or a signal this system lacks
            previous[number] = signal.signal(number, on_signal)
    try:
        yield
    finally:
        for number, handler in previous.items():
            with contextlib.suppress(ValueError, OSError, TypeError):
                signal.signal(number, handler)  # type: ignore[arg-type]
        restore()


__all__: list[str] = ["RESET", "restore", "restore_on_exit"]
