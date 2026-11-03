"""Differential check of the METAR decoder against two independent open-source decoders.

Skipped unless ``avwx-engine`` and ``metar-taf-parser-mivek`` are importable. They are deliberately not project
dependencies: install them in a scratch venv outside the repo (see tests/fuzz/requirements-redteam.txt) and run
``python -m pytest tests/fuzz/test_rt_differential.py`` with that venv's interpreter and ``PYTHONPATH`` set to the repo.

Only fields on which the three decoders must agree are compared (temperature, dew point, wind, cloud layers). Known
disagreements that are the other decoder's fault (avwx treats VV000 as no ceiling; mivek rejects a ``COR`` ahead of
the station) are not compared.
"""

from __future__ import annotations

import re
import warnings
from datetime import UTC, datetime

import pytest
from grammar import Draw, metar
from hypothesis import HealthCheck, given, settings

avwx = pytest.importorskip("avwx")
mivek = pytest.importorskip("metar_taf_parser.parser.parser")

from wxbrief.decode.metar import parse_metar  # noqa: E402

REF = datetime(2026, 10, 29, 23, 59, tzinfo=UTC)
DIFF = settings(
    max_examples=400, deadline=None, derandomize=True, database=None, suppress_health_check=list(HealthCheck)
)


@DIFF
@given(metar())
def test_wxbrief_agrees_with_mivek_on_temperature_wind_and_cloud(draw: Draw) -> None:
    ours = parse_metar(draw.text, REF)
    theirs = mivek.MetarParser().parse(re.sub(r"^(METAR|SPECI) ", "", draw.text))
    assert theirs.temperature == ours.temperature.value
    assert theirs.dew_point == ours.dewpoint.value
    if ours.wind.speed.value:
        assert theirs.wind.speed == ours.wind.speed.value
        assert theirs.wind.gust == (ours.wind.gust.value if ours.wind.gust else None)
    clouds = [(c.quantity.name, c.height) for c in theirs.clouds if c.quantity.name in ("FEW", "SCT", "BKN", "OVC")]
    layers = [(c.cover.name, int(c.base.feet)) for c in ours.sky if c.cover.name in ("FEW", "SCT", "BKN", "OVC")]
    assert clouds == layers


@DIFF
@given(metar())
def test_wxbrief_agrees_with_avwx_on_temperature_and_wind(draw: Draw) -> None:
    ours = parse_metar(draw.text, REF)
    parsed = avwx.Metar(draw.facts["station"])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        parsed.parse(draw.text, issued=REF)
    data = parsed.data
    assert data.temperature.value == ours.temperature.value
    assert data.dewpoint.value == ours.dewpoint.value
    if ours.wind.speed.value:
        assert data.wind_speed.value == ours.wind.speed.value
        assert (data.wind_gust.value if data.wind_gust else None) == (ours.wind.gust.value if ours.wind.gust else None)
