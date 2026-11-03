"""Shared builders for the UX audit tests: an app loaded with saved AWC rows on an injected clock, polling off."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from test_app_smoke import NOW, make_app

from wxbrief.app import WxBriefApp
from wxbrief.data.models import parse_metars, parse_tafs
from wxbrief.data.poll import Product
from wxbrief.ui.screens.briefing import BriefingScreen

FIXTURES = Path(__file__).parent.parent / "fixtures" / "awc"


def rows(name: str) -> list[dict[str, Any]]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def station_ids(name: str, count: int) -> list[str]:
    seen: list[str] = []
    for row in rows(name):
        if row["icaoId"] not in seen:
            seen.append(row["icaoId"])
    return seen[:count]


def load(app: WxBriefApp, metars: list[dict[str, Any]], tafs: list[dict[str, Any]] | None = None) -> None:
    app.state.apply(Product.METAR, parse_metars(metars))
    if tafs is not None:
        app.state.apply(Product.TAF, parse_tafs(tafs))
    app.briefing.refresh_view()


def briefing(app: WxBriefApp) -> BriefingScreen:
    assert isinstance(app.screen, BriefingScreen)
    return app.screen


__all__ = ["NOW", "UTC", "briefing", "datetime", "load", "make_app", "rows", "station_ids"]


def screen_lines(app: WxBriefApp) -> list[str]:
    """The characters on screen, one string per row (styles dropped)."""
    strips = app.screen._compositor.render_strips()
    return ["".join(segment.text for segment in strip) for strip in strips]
