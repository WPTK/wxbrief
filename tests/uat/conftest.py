"""The journeys run offline on the bundled demo reports: any network access fails the test."""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

from wxbrief import clipboard


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "uat_live: long real-time journey; skipped unless WXBRIEF_UAT_LIVE=1")
    config.addinivalue_line("markers", "J13b_single_reset: the nightly live set (one dropped TAF request)")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    # The known-bad run (WXBRIEF_UAT_KNOWNBAD=1) picks its live tests by itself; everything else needs WXBRIEF_UAT_LIVE=1.
    if os.environ.get("WXBRIEF_UAT_LIVE") == "1" or os.environ.get("WXBRIEF_UAT_KNOWNBAD") == "1":
        return
    skip = pytest.mark.skip(reason="long live journey: set WXBRIEF_UAT_LIVE=1")
    for item in items:
        if item.get_closest_marker("uat_live"):
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async def refuse(self: object, request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"network access in a test: {request.url}")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", refuse)
    monkeypatch.setenv("WXBRIEF_CACHE_DIR", str(tmp_path / "cache"))


@pytest.fixture
def copied(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    store: list[str] = []
    monkeypatch.setattr(clipboard, "_pyperclip_copy", store.append)
    return store


from journey_kit import session  # noqa: E402, F401  (the fixture of the real-input journeys)
