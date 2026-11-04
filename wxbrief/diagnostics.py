"""What to leave behind when something goes wrong: a crash log with its path on screen, and ``wxbrief --diagnose``."""

from __future__ import annotations

import os
import platform
import shutil
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path

import platformdirs

from wxbrief import __version__
from wxbrief.config import default_config_path
from wxbrief.data.cache import default_cache_dir

LOG_DIR_ENV = "WXBRIEF_LOG_DIR"
ISSUES_URL = "https://github.com/WPTK/wxbrief/issues"
_KEEP_BYTES = 200_000  # the log is cut back to its newest part when it grows past this


def default_log_dir() -> Path:
    """``$WXBRIEF_LOG_DIR`` when set, else the platform's log folder."""
    override = os.environ.get(LOG_DIR_ENV, "").strip()
    if override:
        try:
            return Path(override).expanduser().resolve()
        except (RuntimeError, OSError):
            pass
    return Path(platformdirs.user_log_dir("wxbrief"))


def log_path() -> Path:
    return default_log_dir() / "wxbrief.log"


def write_crash_log(error: BaseException | None) -> Path | None:
    """Append the traceback of ``error`` (or of the exception being handled) to the log; the path, or ``None`` when
    the log cannot be written (a read-only disk must not turn one failure into two)."""
    path = log_path()
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%SZ")
    if error is None:
        body = traceback.format_exc()
    else:
        body = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    entry = f"--- {stamp} wxbrief {__version__} on {platform.platform()}, Python {platform.python_version()}\n{body}\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_bytes() if path.exists() else b""
        kept = existing[-_KEEP_BYTES:].decode("utf-8", errors="ignore")
        path.write_text(kept + entry, encoding="utf-8")
    except OSError:
        return None
    return path


def crash_message(error: BaseException | None, path: Path | None) -> str:
    """The plain words printed instead of a traceback. English on purpose: a crash may be in the catalogs."""
    name = type(error).__name__ if error is not None else "an error"
    where = f"Details are saved in {path}." if path is not None else "The log could not be written."
    return (
        f"wxbrief stopped because of an unexpected error ({name}). {where}\n"
        f"Please report it at {ISSUES_URL} and include the output of `wxbrief --diagnose`.\n"
    )


def _writable(folder: Path) -> str:
    probe = folder
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return "writable" if os.access(probe, os.W_OK) else "not writable"


def diagnose_text(config_path: Path | None = None) -> str:
    """Version, platform, terminal capabilities and the paths wxbrief uses, as plain lines for a bug report."""
    from rich.console import Console

    size = shutil.get_terminal_size(fallback=(0, 0))
    console = Console()
    config = config_path or default_config_path()
    cache = default_cache_dir()
    log = log_path()
    env = os.environ
    rows = [
        ("wxbrief", __version__),
        ("Python", f"{platform.python_version()} ({platform.python_implementation()})"),
        ("Platform", platform.platform()),
        ("Executable", "frozen build" if getattr(sys, "frozen", False) else sys.executable),
        ("Terminal", ""),
        ("  stdin is a terminal", str(sys.stdin.isatty() if sys.stdin else False).lower()),
        ("  stdout is a terminal", str(sys.stdout.isatty() if sys.stdout else False).lower()),
        ("  size", f"{size.columns}x{size.lines}" if size.columns else "unknown"),
        ("  colour system", console.color_system or "none"),
        ("  TERM", env.get("TERM", "(unset)")),
        ("  COLORTERM", env.get("COLORTERM", "(unset)")),
        ("  NO_COLOR", "set" if env.get("NO_COLOR") else "(unset)"),
        ("  stdout encoding", getattr(sys.stdout, "encoding", None) or "unknown"),
        ("  Windows Terminal", "yes" if env.get("WT_SESSION") else "no"),
        ("Paths", ""),
        ("  config", f"{config} ({'found' if config.exists() else 'not created yet'})"),
        ("  cache", f"{cache} ({_writable(cache)})"),
        ("  log", f"{log} ({'found' if log.exists() else 'none yet'})"),
    ]
    return "\n".join(f"{name}: {value}" if value else f"{name}:" for name, value in rows) + "\n"
