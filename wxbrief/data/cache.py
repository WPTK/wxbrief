"""On-disk cache of the last successful fetches, so a launch is instant and works offline."""

from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import platformdirs

CACHE_DIR_ENV = "WXBRIEF_CACHE_DIR"


def default_cache_dir() -> Path:
    """``$WXBRIEF_CACHE_DIR`` when set (made absolute, so a later chdir cannot move it), else the platform folder."""
    override = os.environ.get(CACHE_DIR_ENV, "").strip()
    if override:
        try:
            return Path(override).expanduser().resolve()
        except (RuntimeError, OSError):  # an unknown ``~user`` has no home folder to expand to: use the default
            pass
    return Path(platformdirs.user_cache_dir("wxbrief"))


TEMP_MAX_AGE = 3600.0  # seconds; a younger temp file may belong to a write still in progress in another process


def sweep_temp_files(directory: Path, prefix: str, max_age: float = TEMP_MAX_AGE) -> None:
    """Delete the ``<prefix>*.tmp`` files a killed process left in ``directory``. Never raises."""
    cutoff = time.time() - max_age
    try:
        for path in directory.glob(f"{prefix}*.tmp"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                continue
    except OSError:
        return


class DiskCache:
    """JSON documents under one directory. Reads never raise (missing or damaged is ``None``); writes are atomic."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or default_cache_dir()

    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def write(self, key: str, payload: Any, saved_at: datetime | None = None) -> bool:
        """Store ``payload`` (JSON-able) under ``key``; ``False`` when the disk refuses."""
        stamp = (saved_at or datetime.now(UTC)).isoformat()
        document = {"saved_at": stamp, "payload": payload}
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(dir=self.directory, prefix=f".{key}.", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(document, handle, separators=(",", ":"))
                os.replace(tmp_name, self._path(key))
            except BaseException:
                Path(tmp_name).unlink(missing_ok=True)
                raise
        except (OSError, TypeError, ValueError, RecursionError):
            return False
        return True

    def clean(self, keys: Iterable[str]) -> None:
        """Remove temp files left by a process killed mid-write while writing ``keys`` (the folder may be shared)."""
        for key in keys:
            sweep_temp_files(self.directory, f".{key}.")

    def read(self, key: str) -> tuple[datetime, Any] | None:
        """The stored payload and when it was saved (always timezone-aware), or ``None``; a naive time is damaged."""
        try:
            document = json.loads(self._path(key).read_text(encoding="utf-8"))
            saved_at = datetime.fromisoformat(document["saved_at"])
            payload = document["payload"]
        except (OSError, ValueError, KeyError, TypeError, RecursionError):  # the last: JSON nested too deep
            return None
        return (saved_at, payload) if saved_at.tzinfo is not None else None
