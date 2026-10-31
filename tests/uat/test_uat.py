"""The UAT suite: every journey in journeys.py at every size it names, on the real app with the demo data.

Run it all with ``pytest tests/uat``; leave out the slow ones with ``-m "not slow"``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from harness import SIZES, run_journey
from journeys import JOURNEYS, Spec

CASES = [
    pytest.param(spec, size, id=f"{spec.name}-{size}", marks=[pytest.mark.slow] if spec.slow else [])
    for spec in JOURNEYS
    for size in spec.sizes
]


@pytest.mark.parametrize(("spec", "size"), CASES)
async def test_journey(spec: Spec, size: str, tmp_path: Path) -> None:
    run = await run_journey(spec.run, SIZES[size], tmp_path, *spec.flags)
    assert run.app.return_code in (None, 0)
    assert not [n for n in run.app._notifications if n.severity == "error"], "the app raised an error toast"
