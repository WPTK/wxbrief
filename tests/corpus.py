"""Access to the saved report corpus under ``tests/fixtures``."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent / "fixtures"
REPORTS = FIXTURES / "reports"
AWC = FIXTURES / "awc"


TAF_PREFIX = "taf-"  # TAF fixtures live in ``taf-<region>`` folders next to the METAR ones


def report_files() -> list[Path]:
    """Every saved raw METAR/SPECI, sorted so test ids are stable."""
    return sorted(p for p in REPORTS.glob("*/*.txt") if not p.parent.name.startswith(TAF_PREFIX))


def taf_files() -> list[Path]:
    """Every saved raw TAF, sorted so test ids are stable."""
    return sorted(REPORTS.glob(f"{TAF_PREFIX}*/*.txt"))


def golden_files(*, taf: bool) -> set[str]:
    """Names (without ``.golden.json``) of every golden of the METAR or the TAF corpus."""
    return {
        p.name.removesuffix(".golden.json")
        for p in REPORTS.glob("*/*.golden.json")
        if p.parent.name.startswith(TAF_PREFIX) == taf
    }


def read_raw(path: Path) -> str:
    """The report text of a fixture without its trailing newline."""
    return path.read_text(encoding="utf-8").strip()


def reference_for(path: Path) -> datetime:
    """The reference moment encoded in a fixture name: ``KDEN_202610131453[_note].txt`` -> 2026-10-13 14:53 UTC."""
    stamp = path.stem.split("_")[1]
    return datetime.strptime(stamp, "%Y%m%d%H%M").replace(tzinfo=UTC)


def golden_path(path: Path) -> Path:
    return path.with_suffix(".golden.json")


def awc_taf_rows() -> list[dict[str, Any]]:
    """All saved AWC TAF responses, without duplicates."""
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for batch in sorted(AWC.glob("taf_*.json")):
        for row in json.loads(batch.read_text(encoding="utf-8")):
            key = (row["icaoId"], row["rawTAF"])
            if key not in seen:
                seen.add(key)
                rows.append(row)
    return rows


def issue_time(row: dict[str, Any]) -> datetime:
    """The issue time of an AWC TAF row: the reference for resolving the day-of-month groups."""
    return datetime.fromisoformat(row["issueTime"].replace("Z", "+00:00"))


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
