"""Async client for the aviationweather.gov data API."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Self

import httpx

from wxbrief import __version__
from wxbrief.data.models import (
    AwcMetar,
    AwcStation,
    AwcTaf,
    parse_metars,
    parse_stations,
    parse_tafs,
)

BASE_URL = "https://aviationweather.gov/api/data"
USER_AGENT = f"wxbrief/{__version__} (+https://github.com/WPTK/wxbrief)"
TIMEOUT_SECONDS = 10.0
MAX_IDS_PER_REQUEST = 400
DEFAULT_RETRY_AFTER = 60.0


class AwcError(Exception):
    """Base class for every failure talking to the AWC API."""


class RateLimited(AwcError):
    """HTTP 429. ``retry_after`` is the wait in seconds the server asked for (a default when it did not say)."""

    def __init__(self, retry_after: float) -> None:
        super().__init__(f"rate limited, retry after {retry_after:g} s")
        self.retry_after = retry_after


class ServerError(AwcError):
    """HTTP 5xx."""

    def __init__(self, status: int) -> None:
        super().__init__(f"server error {status}")
        self.status = status


class ClientError(AwcError):
    """Any other unexpected status (a 4xx that is not 429) or a body that is not JSON."""


class TransportError(AwcError):
    """Timeout, DNS, connection or TLS failure."""


def _retry_after(response: httpx.Response) -> float:
    try:
        return max(0.0, float(response.headers.get("Retry-After", "")))
    except ValueError:
        return DEFAULT_RETRY_AFTER


def _chunks(ids: Sequence[str], size: int) -> list[list[str]]:
    unique = list(dict.fromkeys(i.strip().upper() for i in ids if i.strip()))
    return [unique[start : start + size] for start in range(0, len(unique), size)]


def request_count(ids: Sequence[str]) -> int:
    """How many HTTP requests a fetch of ``ids`` takes (one per chunk of ``MAX_IDS_PER_REQUEST``)."""
    return len(_chunks(ids, MAX_IDS_PER_REQUEST))


class AwcClient:
    """Thin typed wrapper over ``/metar``, ``/taf`` and ``/stationinfo``.

    Large id lists are split into requests of at most ``MAX_IDS_PER_REQUEST`` ids, sent one after another.
    """

    def __init__(
        self,
        *,
        base_url: str = BASE_URL,
        client: httpx.AsyncClient | None = None,
        timeout: float = TIMEOUT_SECONDS,
    ) -> None:
        self._owns_client = client is None
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=timeout, headers={"User-Agent": USER_AGENT})

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _get(self, endpoint: str, params: dict[str, str]) -> list[Any]:
        try:
            response = await self._client.get(f"{self._base_url}/{endpoint}", params=params)
        except httpx.HTTPError as exc:
            raise TransportError(f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__) from exc
        status = response.status_code
        if status == 204:
            return []
        if status == 429:
            raise RateLimited(_retry_after(response))
        if status >= 500:
            raise ServerError(status)
        if status != 200:
            raise ClientError(f"unexpected status {status}")
        try:
            body = response.json()
        except ValueError as exc:
            raise ClientError("response is not JSON") from exc
        return body if isinstance(body, list) else []

    async def _fetch(self, endpoint: str, ids: Sequence[str], extra: dict[str, str]) -> list[Any]:
        rows: list[Any] = []
        for chunk in _chunks(ids, MAX_IDS_PER_REQUEST):
            rows.extend(await self._get(endpoint, {"ids": ",".join(chunk), "format": "json", **extra}))
        return rows

    async def metars(self, ids: Sequence[str], hours: int = 2) -> list[AwcMetar]:
        """METAR and SPECI reports from the last ``hours`` hours, newest first as the API returns them."""
        return parse_metars(await self._fetch("metar", ids, {"hours": str(hours)}))

    async def tafs(self, ids: Sequence[str]) -> list[AwcTaf]:
        """The current TAF for each station that has one."""
        return parse_tafs(await self._fetch("taf", ids, {}))

    async def stations(self, ids: Sequence[str]) -> list[AwcStation]:
        """Station metadata."""
        return parse_stations(await self._fetch("stationinfo", ids, {}))

