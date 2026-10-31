"""Access to the saved report corpus under ``tests/fixtures``."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent / "fixtures"
REPORTS = FIXTURES / "reports"
AWC = FIXTURES / "awc"


def report_files() -> list[Path]:
    """Every saved raw report, sorted so test ids are stable."""
    return sorted(REPORTS.glob("*/*.txt"))


def read_raw(path: Path) -> str:
    """The report text of a fixture without its trailing newline."""
    return path.read_text(encoding="utf-8").strip()


def reference_for(path: Path) -> datetime:
    """The reference moment encoded in a fixture name: ``KDEN_202610131453[_note].txt`` -> 2026-10-13 14:53 UTC."""
    stamp = path.stem.split("_")[1]
    return datetime.strptime(stamp, "%Y%m%d%H%M").replace(tzinfo=UTC)


def golden_path(path: Path) -> Path:
    return path.with_suffix(".golden.json")


def awc_rows() -> list[dict[str, Any]]:
    """All saved AWC METAR responses, without duplicates (a station can appear in two batches)."""
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for batch in sorted(AWC.glob("metar_*.json")):
        for row in json.loads(batch.read_text(encoding="utf-8")):
            key = (row["icaoId"], row["rawOb"])
            if key not in seen:
                seen.add(key)
                rows.append(row)
    return rows
