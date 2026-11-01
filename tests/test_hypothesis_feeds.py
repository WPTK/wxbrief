"""Property tests on the feed parsers: whatever the server (or a damaged cache file) sends, parsing returns records.

The decoders have their own property tests in test_fuzz.py. These cover the JSON layer in front of them: arbitrary
JSON, and real rows with one field replaced by arbitrary JSON, never raise and only ever yield well-formed records.
"""

from __future__ import annotations

import json
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from wxbrief.data.models import AwcMetar, AwcStation, AwcTaf, parse_metars, parse_stations, parse_tafs

AWC = Path(__file__).parent / "fixtures" / "awc"
JSON_VALUES = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=True) | st.text(max_size=30),
    lambda children: st.lists(children, max_size=5) | st.dictionaries(st.text(max_size=12), children, max_size=6),
    max_leaves=25,
)
LIMITS = settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])


def rows(prefix: str) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    for path in sorted(AWC.glob(f"{prefix}*.json")):
        found += [r for r in json.loads(path.read_text(encoding="utf-8")) if isinstance(r, dict)]
    return found


METAR_ROWS, TAF_ROWS = rows("metar_"), rows("taf_")


@LIMITS
@given(JSON_VALUES)
def test_arbitrary_json_never_breaks_a_parser(payload: object) -> None:
    assert all(isinstance(m, AwcMetar) for m in parse_metars(payload))
    assert all(isinstance(t, AwcTaf) for t in parse_tafs(payload))
    assert all(isinstance(s, AwcStation) for s in parse_stations(payload))


@LIMITS
@given(st.data())
def test_a_real_row_with_one_damaged_field_never_breaks_a_parser(data: st.DataObject) -> None:
    for source, parse, kind in ((METAR_ROWS, parse_metars, AwcMetar), (TAF_ROWS, parse_tafs, AwcTaf)):
        row = dict(data.draw(st.sampled_from(source)))
        field = data.draw(st.sampled_from(sorted(row)))
        row[field] = data.draw(JSON_VALUES)
        assert all(isinstance(r, kind) for r in parse([row]))


@LIMITS
@given(st.lists(JSON_VALUES, max_size=8))
def test_a_list_of_junk_rows_is_skipped_not_fatal(junk: list[object]) -> None:
    assert len(parse_metars([*junk, METAR_ROWS[0]])) >= len(parse_metars([METAR_ROWS[0]]))
