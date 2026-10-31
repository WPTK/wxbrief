"""The journeys run offline on the bundled demo reports: any network access fails the test."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from wxbrief import clipboard


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
