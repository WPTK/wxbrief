"""Screenshots of the briefing screen in three themes, compared with pytest-textual-snapshot.

The app runs on an injected clock with polling off and the saved KDEN and EGLL reports, so the picture depends only on
the theme. Regenerate with ``pytest tests/test_snapshots.py --snapshot-update`` and look at the diff.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from test_app_smoke import METARS, TAFS, _no_network, make_app  # noqa: F401

from wxbrief.data.models import parse_metars, parse_tafs
from wxbrief.data.poll import Product

_EXPORT_COMMENT = re.compile(r"[ \t]*<!-- Generated with Rich [^>]*-->\r?\n")


@pytest.fixture(autouse=True)
def _plain_screenshots(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the exporter's credit comment out of the stored SVGs, and make the picture independent of NO_COLOR."""
    from textual import _doc

    original = _doc.take_svg_screenshot
    monkeypatch.setattr(_doc, "take_svg_screenshot", lambda *a, **k: _EXPORT_COMMENT.sub("", original(*a, **k)))
    monkeypatch.delenv("NO_COLOR", raising=False)


@pytest.mark.parametrize("theme", ["textual-dark", "paper-chart", "phosphor-green"])
def test_briefing_screen(snap_compare: Any, tmp_path: Path, theme: str) -> None:
    app = make_app(tmp_path, ["KDEN", "EGLL"])
    app.theme = theme

    async def load(pilot: Any) -> None:
        app.state.apply(Product.METAR, parse_metars(METARS))
        app.state.apply(Product.TAF, parse_tafs(TAFS))
        app.briefing.refresh_view()
        await pilot.pause()

    assert snap_compare(app, terminal_size=(120, 36), run_before=load)
