"""Golden decodes of the saved report corpus.

Every ``tests/fixtures/reports/<region>/<ICAO>_<yyyymmddhhmm>[_handwritten-note].txt`` has a ``.golden.json`` next to
it holding ``jsonout.to_dict`` of the decode. The timestamp in the name is the reference date used to resolve the
day-of-month group. Run ``pytest --update-goldens`` after an intended decoder change, then review the diff.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from corpus import awc_rows, golden_path, read_raw, reference_for, report_files

from wxbrief.decode.metar import parse_metar
from wxbrief.render.jsonout import to_dict

FILES = report_files()


def _id(path: Path) -> str:
    return f"{path.parent.name}/{path.stem}"


@pytest.mark.parametrize("path", FILES, ids=_id)
def test_golden(path: Path, update_goldens: bool) -> None:
    decoded = to_dict(parse_metar(read_raw(path), reference_for(path)))
    golden = golden_path(path)
    if update_goldens:
        golden.write_bytes((json.dumps(decoded, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
        return
    assert golden.exists(), f"missing golden for {path.name}; run pytest --update-goldens and review it"
    assert json.loads(golden.read_text(encoding="utf-8")) == decoded


def test_every_golden_has_a_report() -> None:
    goldens = {p.name.removesuffix(".golden.json") for p in (FILES[0].parents[1]).glob("*/*.golden.json")}
    reports = {p.stem for p in FILES}
    assert goldens == reports


def test_live_fixtures_are_real_awc_reports() -> None:
    """A fixture not marked hand-written must be a report the AWC API actually returned."""
    real = {row["rawOb"] for row in awc_rows()}
    for path in FILES:
        if "handwritten" not in path.stem:
            assert read_raw(path) in real, f"{path.name} is not in the saved AWC batches; rename it as handwritten"


def test_fixtures_cover_the_required_regions() -> None:
    regions = {path.parent.name for path in FILES}
    assert {"us", "uk", "france"} <= regions


def test_fixture_names_are_well_formed() -> None:
    for path in FILES:
        icao, stamp, *note = path.stem.split("_")
        assert len(icao) == 4 and icao.isalnum() and icao.isupper(), path.name
        assert len(stamp) == 12 and stamp.isdigit(), path.name
        if note:
            assert note[0].startswith("handwritten-"), path.name
        reference_for(path)  # parses
