"""Golden decodes of the saved TAF corpus.

Every ``tests/fixtures/reports/taf-<region>/<ICAO>_<yyyymmddhhmm>[_handwritten-note].txt`` has a ``.golden.json``
next to it holding ``jsonout.to_dict`` of the decode. The timestamp in the name is the issue time, the reference that
resolves the day-of-month groups. Run ``pytest --update-goldens`` after an intended decoder change, then review the
diff against the raw text.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from corpus import awc_taf_rows, golden_files, golden_path, read_raw, reference_for, taf_files

from wxbrief.decode.model import ChangeType, Modifier, ReportType
from wxbrief.decode.taf import parse_taf
from wxbrief.render.jsonout import to_dict

FILES = taf_files()

# Notes the decoder does not read, kept as unknown tokens with a warning (the same two as in the AWC cross-check).
UNDECODED_NOTES = {
    "KRIV": ["WND", "230V330"],
    "NZSP": ["WND21008KT", "AFT", "3122", "ALL", "WINDS", "GRID"],
}


def _id(path: Path) -> str:
    return f"{path.parent.name}/{path.stem}"


@pytest.mark.parametrize("path", FILES, ids=_id)
def test_golden(path: Path, update_goldens: bool) -> None:
    decoded = to_dict(parse_taf(read_raw(path), reference_for(path)))
    golden = golden_path(path)
    if update_goldens:
        golden.write_bytes((json.dumps(decoded, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
        return
    assert golden.exists(), f"missing golden for {path.name}; run pytest --update-goldens and review it"
    assert json.loads(golden.read_text(encoding="utf-8")) == decoded


@pytest.mark.parametrize("path", FILES, ids=_id)
def test_corpus_tafs_decode_cleanly(path: Path) -> None:
    taf = parse_taf(read_raw(path), reference_for(path))
    assert taf.report_type is ReportType.TAF
    station = path.stem.split("_")[0]
    assert taf.station == station
    # The legacy forms are accepted with their own warning; nothing else may be left unread, bar the named notes.
    legacy = ["legacy_format"] * sum(w.code == "legacy_format" for w in taf.warnings)
    assert bool(legacy) == ("legacy" in path.stem), path.name
    unread = [w.text for w in taf.warnings if w.code == "unknown_token"]
    assert unread == UNDECODED_NOTES.get(station, []), f"{path.name}: {taf.warnings}"
    assert len(taf.warnings) == len(legacy) + len(unread), f"{path.name}: {taf.warnings}"


def test_every_golden_has_a_report() -> None:
    assert golden_files(taf=True) == {p.stem for p in FILES}


def test_live_fixtures_are_real_awc_tafs() -> None:
    """A fixture not marked hand-written must be a forecast the AWC API actually returned."""
    real = {row["rawTAF"].strip() for row in awc_taf_rows()}
    for path in FILES:
        if "handwritten" not in path.stem:
            assert read_raw(path) in real, f"{path.name} is not in the saved AWC batches; rename it as handwritten"


def test_fixture_names_are_well_formed() -> None:
    for path in FILES:
        icao, stamp, *note = path.stem.split("_")
        assert len(icao) == 4 and icao.isalnum() and icao.isupper(), path.name
        assert len(stamp) == 12 and stamp.isdigit(), path.name
        if note:
            assert note[0].startswith("handwritten-"), path.name
        reference_for(path)  # parses


def test_the_corpus_covers_every_kind_of_forecast_group() -> None:
    """The fixtures are chosen to exercise each form; losing one silently would weaken the goldens."""
    tafs = [parse_taf(read_raw(path), reference_for(path)) for path in FILES]
    changes = {period.change for taf in tafs for period in taf.changes}
    assert changes == set(ChangeType) - {ChangeType.BASE}
    modifiers = {m for taf in tafs for m in taf.modifiers}
    assert {Modifier.AMD, Modifier.COR, Modifier.CNL, Modifier.NIL} <= modifiers
    assert any(taf.legacy for taf in tafs)
    assert any(taf.temperatures for taf in tafs)
    assert any(period.elements.wind_shear for taf in tafs for period in taf.periods)
    assert any(period.elements.icing for taf in tafs for period in taf.periods)
    assert any(period.elements.turbulence for taf in tafs for period in taf.periods)
    assert any(period.elements.altimeter for taf in tafs for period in taf.periods)
