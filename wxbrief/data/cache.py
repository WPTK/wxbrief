"""On-disk cache of the last successful fetches, so a launch is instant and works offline."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import platformdirs

CACHE_DIR_ENV = "WXBRIEF_CACHE_DIR"


def default_cache_dir() -> Path:
    """``$WXBRIEF_CACHE_DIR`` when set (made absolute, so a later chdir cannot move it), else the platform folder."""
    override = os.environ.get(CACHE_DIR_ENV, "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path(platformdirs.user_cache_dir("wxbrief"))


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
        except (OSError, TypeError, ValueError):
            return False
        return True

    def read(self, key: str) -> tuple[datetime, Any] | None:
        """The stored payload and when it was saved, or ``None``."""
        try:
            document = json.loads(self._path(key).read_text(encoding="utf-8"))
            return datetime.fromisoformat(document["saved_at"]), document["payload"]
        except (OSError, ValueError, KeyError, TypeError):
            return None
