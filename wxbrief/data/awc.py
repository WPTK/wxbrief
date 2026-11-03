"""Async client for the aviationweather.gov data API."""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Self

import anysqlite
import hishel
import httpx
import stamina
import stamina.instrumentation

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
RETRY_DELAY_SECONDS = 1.0  # first backoff before a retry; it doubles each time, plus jitter of up to this much
RETRY_ATTEMPTS = 3  # tries of one request that fails in transit or with a 5xx; the poller's own backoff sits above this
MAX_RETRY_WAIT = 5.0  # the longest single backoff
DEADLINE_SECONDS = 30.0  # the limit on one whole request, however slowly the server drips its body
MAX_IDS_PER_REQUEST = 400
DEFAULT_RETRY_AFTER = 60.0
MAX_RETRY_AFTER = 3600.0
MAX_BODY_BYTES = 8 * 1024 * 1024  # a full 400-station METAR batch is well under 1 MB
CACHE_TTL_SECONDS = 3600.0  # a stored response nobody asked for in this long is dropped (it is never served unasked)


# Replaces stamina's retry hooks process-wide on purpose: the default one logs every retry, and a TUI must not print
# retry notices over its screen.
stamina.instrumentation.set_on_retry_hooks([])


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
    if value.isascii() and value.isdigit():  # RFC 9110 delta-seconds is 1*DIGIT; float() also takes "1e3", "+5", "1_0"
        seconds = float(value)
    else:
        try:
            seconds = (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()
        except (TypeError, ValueError):
            return DEFAULT_RETRY_AFTER
    if not math.isfinite(seconds):
        return DEFAULT_RETRY_AFTER
    return min(MAX_RETRY_AFTER, max(0.0, seconds))


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


_RECOMPUTED = frozenset({"content-encoding", "content-length", "transfer-encoding"})  # httpx already decoded the body


async def _one_chunk(content: bytes) -> AsyncIterator[bytes]:
    yield content


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
        retry_delay: float | None = None,
    ) -> None:
        self._deadline = deadline
        self._retry_delay = RETRY_DELAY_SECONDS if retry_delay is None else retry_delay
        self._cache: hishel.AsyncCacheProxy | None = None  # made on the first request: it needs the running loop
        self._cache_lock = asyncio.Lock()
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
        if self._cache is not None:
            await self._cache.storage.close()
            self._cache = None
        if self._owns_client:
            await self._client.aclose()

    async def _proxy(self) -> hishel.AsyncCacheProxy:
        """The RFC 9111 cache. It lives in memory only: nothing is written to disk and nothing outlives the process.
        Its size is bounded by ``CACHE_TTL_SECONDS`` alone (hishel has no entry limit)."""
        async with self._cache_lock:  # two first requests at once must not each open a database
            if self._cache is None:
                storage = hishel.AsyncSqliteStorage(
                    connection=await anysqlite.connect(":memory:"), default_ttl=CACHE_TTL_SECONDS
                )
                self._cache = hishel.AsyncCacheProxy(self._send, storage)
            return self._cache

    async def _send(self, request: hishel.Request) -> hishel.Response:
        """One real HTTP request for the cache, tried up to ``RETRY_ATTEMPTS`` times with jittered backoff when it fails
        in transit or with a 5xx. Every retry asks the server to close the connection, so it cannot reuse one that
        went stale. The body is read here, with its size limit, before the cache stores it."""
        async for attempt in stamina.retry_context(
            on=(httpx.TransportError, ServerError),
            attempts=RETRY_ATTEMPTS,
            timeout=None,  # the deadline in ``_get`` is the one limit; httpx's own restarts on every read
            wait_initial=self._retry_delay,
            wait_max=MAX_RETRY_WAIT,
            wait_jitter=self._retry_delay,
        ):
            with attempt:
                # ``no-cache`` was for our own cache; a CDN in front of the server is not told to skip its cache
                headers = {k: v for k, v in request.headers.items() if k.lower() != "cache-control"}
                if attempt.num > 1:
                    headers["Connection"] = "close"
                async with self._client.stream(request.method, request.url, headers=headers) as response:
                    status = response.status_code
                    if status >= 500:
                        raise ServerError(status)
                    content = await _read_limited(response) if status == 200 else b""
                    kept = {k: v for k, v in response.headers.items() if k.lower() not in _RECOMPUTED}
                    kept["content-length"] = str(len(content))
                    return hishel.Response(status, hishel.Headers(kept), _one_chunk(content))
        raise AssertionError("unreachable")  # pragma: no cover

    async def _get(self, endpoint: str, params: dict[str, str]) -> list[Any]:
        """One request through the cache, always revalidated: ``Cache-Control: no-cache`` makes hishel send
        ``If-None-Match`` / ``If-Modified-Since`` for a stored response and reuse its body only on a 304 from the
        server.
        Freshness (``max-age``) is never used: reusing a response without asking would show a report older than a poll
        as the current one."""
        url = str(self._client.build_request("GET", f"{self._base_url}/{endpoint}", params=params).url)
        try:
            cache = await self._proxy()
            async with asyncio.timeout(self._deadline):  # one limit for every try; httpx's own restarts on every read
                response = await cache.handle_request(
                    hishel.Request("GET", url, hishel.Headers({"Cache-Control": "no-cache"}), _one_chunk(b""))
                )
                content = await response.aread()
        except httpx.HTTPError as exc:
            raise TransportError(f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__) from exc
        except TimeoutError as exc:
            raise TransportError(f"no complete response within {self._deadline:g} s") from exc
        status = response.status_code
        if status == 204:
            return []
        if status == 429:
            raise RateLimited(_retry_after(httpx.Response(429, headers=dict(response.headers))))
        if status >= 500:
            raise ServerError(status)
        if status != 200:
            raise ClientError(f"unexpected status {status}")
        try:
            body = json.loads(content)
        except (ValueError, RecursionError) as exc:
            raise ClientError("response is not JSON") from exc
        if not isinstance(body, list) or any(isinstance(row, list) for row in body):  # rows are objects; a list nests
            raise ClientError("response is not a list of objects")
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

