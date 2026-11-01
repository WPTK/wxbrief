"""Async client for the aviationweather.gov data API."""

from __future__ import annotations

import asyncio
import json
import math
import re
import time
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
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
TIMEOUT_SECONDS = 10.0  # httpx's limit on each connect, read and write
DEADLINE_SECONDS = 30.0  # the limit on one whole request, however slowly the server drips its body
MAX_IDS_PER_REQUEST = 400
DEFAULT_RETRY_AFTER = 60.0
MAX_RETRY_AFTER = 3600.0
MAX_BODY_BYTES = 8 * 1024 * 1024  # a full 400-station METAR batch is well under 1 MB
MAX_AGE_CAP = 3600.0  # a Cache-Control max-age longer than this is not allowed to freeze a briefing
CACHED_REQUESTS = 8  # request results kept for revalidation; the oldest is dropped first


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
    """Any other unexpected status (a 4xx that is not 429), or a body that is not a JSON list."""


class TransportError(AwcError):
    """Timeout, DNS, connection or TLS failure."""


def _retry_after(response: httpx.Response) -> float:
    """Seconds from a ``Retry-After`` header (a number or an HTTP date), at most an hour; a default when unusable."""
    value = response.headers.get("Retry-After", "").strip()
    try:
        seconds = float(value)
    except ValueError:
        try:
            seconds = (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()
        except (TypeError, ValueError):
            return DEFAULT_RETRY_AFTER
    if not math.isfinite(seconds):
        return DEFAULT_RETRY_AFTER
    return min(MAX_RETRY_AFTER, max(0.0, seconds))


_MAX_AGE = re.compile(r"(?:^|,)\s*max-age\s*=\s*\"?(\d+)", re.IGNORECASE)
_NO_REUSE = re.compile(r"(?:^|,)\s*(?:no-store|no-cache)\s*(?:,|$)", re.IGNORECASE)


def _max_age(response: httpx.Response) -> float:
    """Seconds the server says the response stays fresh (``Cache-Control: max-age``), 0 when it says nothing usable."""
    control = response.headers.get("Cache-Control", "")
    if _NO_REUSE.search(control):
        return 0.0
    found = _MAX_AGE.search(control)
    return min(MAX_AGE_CAP, float(found.group(1))) if found else 0.0


@dataclass(slots=True)
class _Stored:
    """The last 200 for one request: its rows, the validators to send next time and when it stops being fresh."""

    rows: list[Any]
    etag: str | None
    last_modified: str | None
    fresh_until: float


async def _read_limited(response: httpx.Response) -> bytes:
    """The decoded body, or ``ClientError`` as soon as it passes ``MAX_BODY_BYTES`` (nothing more is read)."""
    declared = response.headers.get("Content-Length", "")
    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise ClientError(f"response is larger than {MAX_BODY_BYTES // (1024 * 1024)} MB")
    parts: list[bytes] = []
    size = 0
    async for part in response.aiter_bytes():
        size += len(part)
        if size > MAX_BODY_BYTES:
            raise ClientError(f"response is larger than {MAX_BODY_BYTES // (1024 * 1024)} MB")
        parts.append(part)
    return b"".join(parts)


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
        deadline: float = DEADLINE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._deadline = deadline
        self._clock = clock
        self._stored: OrderedDict[tuple[str, tuple[tuple[str, str], ...]], _Stored] = OrderedDict()
        self._owns_client = client is None
        self._base_url = base_url.rstrip("/")
        if client is None:
            try:
                client = httpx.AsyncClient(timeout=timeout, headers={"User-Agent": USER_AGENT})
            except Exception as exc:  # what httpx raises here depends on the environment (proxy and CA variables)
                raise TransportError(f"cannot set up the HTTP client: {type(exc).__name__}: {exc}") from exc
        self._client = client

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _get(self, endpoint: str, params: dict[str, str]) -> list[Any]:
        """One request. A response still fresh by ``Cache-Control: max-age`` is reused without a request; a stale one
        is revalidated with ``If-None-Match`` / ``If-Modified-Since`` and a 304 reuses it."""
        key = (endpoint, tuple(sorted(params.items())))
        stored = self._stored.get(key)
        headers: dict[str, str] = {}
        if stored is not None:
            if self._clock() < stored.fresh_until:
                return stored.rows
            if stored.etag:
                headers["If-None-Match"] = stored.etag
            if stored.last_modified:
                headers["If-Modified-Since"] = stored.last_modified
        try:
            async with asyncio.timeout(self._deadline):  # httpx's timeout restarts on every read
                async with self._client.stream(
                    "GET", f"{self._base_url}/{endpoint}", params=params, headers=headers
                ) as response:
                    status = response.status_code
                    content = await _read_limited(response) if status == 200 else b""
        except httpx.HTTPError as exc:
            raise TransportError(f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__) from exc
        except TimeoutError as exc:
            raise TransportError(f"no complete response within {self._deadline:g} s") from exc
        if status == 304 and stored is not None:
            stored.fresh_until = self._clock() + _max_age(response)
            return stored.rows
        if status == 204:
            self._stored.pop(key, None)
            return []
        if status == 429:
            raise RateLimited(_retry_after(response))
        if status >= 500:
            raise ServerError(status)
        if status != 200:
            raise ClientError(f"unexpected status {status}")
        try:
            body = json.loads(content)
        except (ValueError, RecursionError) as exc:
            raise ClientError("response is not JSON") from exc
        if not isinstance(body, list):
            raise ClientError("response is not a list")
        etag, modified = response.headers.get("ETag"), response.headers.get("Last-Modified")
        age = _max_age(response)
        if etag or modified or age:
            self._stored[key] = _Stored(body, etag, modified, self._clock() + age)
            self._stored.move_to_end(key)
            while len(self._stored) > CACHED_REQUESTS:
                self._stored.popitem(last=False)
        else:
            self._stored.pop(key, None)
        return body

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

