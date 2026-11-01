"""The proxy, the TLS origin and the control channel (stdlib asyncio only).

Layout::

    client --CONNECT host:443--> proxy (127.0.0.1:P) --raw bytes--> TLS origin (127.0.0.1:O, cert for ``host``)
    test   --HTTP--> control (127.0.0.1:C)

The proxy only tunnels the host it was given and answers 502 to any other, so it can never reach the real network.

Control channel (plain HTTP, JSON):
    GET  /state              current rules, script, counters
    GET  /log                the request log (list of dicts)
    DELETE /log              clear the log and the per-product counters
    POST /rule               {"product": "taf", "behavior": "5xx", "count": 3}   next 3 taf requests (no count = forever)
    POST /script             {"metar": ["ok", "ok"], "taf": ["ok", "5xx", "5xx"]}   per product, by request index
    POST /reset              back to ``ok`` everywhere, log kept

A behaviour is a dict or a shorthand string (see ``parse_behavior``): ``ok``, ``5xx`` / ``503``, ``429:30``
(Retry-After 30), ``reset``, ``slow:2000`` (ms), ``empty200``, ``empty_list``, ``204``, ``badjson``, ``304``,
``304noetag``, ``drop:120`` (close after 120 body bytes).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import socket
import ssl
import struct
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .certs import TestCA


@dataclass
class Behavior:
    mode: str = "ok"
    status: int = 503
    retry_after: float | None = None
    ms: int = 0
    nbytes: int = 0
    etag: bool = True

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def parse_behavior(spec: str | dict[str, Any] | Behavior) -> Behavior:
    if isinstance(spec, Behavior):
        return spec
    if isinstance(spec, dict):
        spec = dict(spec)
        b = parse_behavior(spec.pop("mode", "ok"))
        for k, v in spec.items():
            setattr(b, k, v)
        return b
    head, _, arg = str(spec).partition(":")
    head = head.lower()
    if head.isdigit() and int(head) >= 500:
        return Behavior("5xx", status=int(head))
    if head == "5xx":
        return Behavior("5xx", status=int(arg) if arg else 503)
    if head == "429":
        return Behavior("429", retry_after=float(arg) if arg else 30.0)
    if head == "slow":
        return Behavior("slow", ms=int(arg or 1000))
    if head == "drop":
        return Behavior("drop", nbytes=int(arg or 50))
    if head == "304noetag":
        return Behavior("304", etag=False)
    if head in {"ok", "reset", "empty200", "empty_list", "204", "badjson", "304"}:
        return Behavior(head)
    raise ValueError(f"unknown behaviour {spec!r}")


@dataclass
class _Rule:
    behavior: Behavior
    remaining: int | None  # None = forever


@dataclass
class _State:
    rules: dict[str, list[_Rule]] = field(default_factory=dict)
    script: dict[str, list[Behavior]] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)


Payloads = dict[str, Any]  # product -> list of rows, or callable(ids: list[str]) -> list of rows


def product_of(path: str, prefix: str) -> str | None:
    if not path.startswith(prefix + "/"):
        return None
    return path[len(prefix) + 1 :].strip("/") or None


async def _read_request(reader: asyncio.StreamReader) -> tuple[str, str, dict[str, str]] | None:
    try:
        head = await reader.readuntil(b"\r\n\r\n")
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError, ssl.SSLError):
        return None
    lines = head.decode("latin-1").split("\r\n")
    parts = lines[0].split(" ")
    if len(parts) < 2:
        return None
    headers = {}
    for line in lines[1:]:
        if ":" in line:
            k, _, v = line.partition(":")
            headers[k.strip().lower()] = v.strip()
    return parts[0], parts[1], headers


def _reset_socket(writer: asyncio.StreamWriter) -> None:
    """Close with RST (SO_LINGER 0) so the client sees a connection reset, not a clean EOF."""
    sock = writer.get_extra_info("socket")
    with contextlib.suppress(Exception):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    with contextlib.suppress(Exception):
        writer.transport.abort()


class FaultProxy:
    """Start with ``with FaultProxy(...) as fp:``; then ``fp.env()`` gives the variables for the program under test."""

    def __init__(
        self,
        payloads: Payloads | None = None,
        *,
        host: str = "aviationweather.gov",
        path_prefix: str = "/api/data",
        directory: Path | None = None,
        id_param: str = "ids",
        id_field: str = "icaoId",
        proxy_port: int = 0,
        control_port: int = 0,
        conditional: bool = False,
        clock: Callable[[], float] = time.time,
    ) -> None:
        import tempfile

        self.host = host
        self.prefix = path_prefix
        self.payloads: Payloads = payloads or {}
        self.id_param, self.id_field = id_param, id_field
        self.conditional = conditional  # answer 304 to a matching If-None-Match, as a real CDN does
        self.dir = Path(directory) if directory else Path(tempfile.mkdtemp(prefix="faultproxy-"))
        self.ca = TestCA(self.dir, [host])
        self.state = _State()
        self.log: list[dict[str, Any]] = []
        self._clock = clock
        self._want = (proxy_port, control_port)
        self._conn_seq = 0
        self.proxy_port = self.control_port = self.origin_port = 0
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()
        self._stop: asyncio.Event | None = None
        self._error: BaseException | None = None

    # -- lifecycle -------------------------------------------------------------------------------------------------

    def __enter__(self) -> FaultProxy:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._thread_main, name="faultproxy", daemon=True)
        self._thread.start()
        if not self._ready.wait(15) or self._error:
            raise RuntimeError(f"faultproxy did not start: {self._error!r}")

    def stop(self) -> None:
        if self._loop and self._stop:
            self._loop.call_soon_threadsafe(self._stop.set)
        if self._thread:
            self._thread.join(10)

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._main())
        except BaseException as exc:
            self._error = exc
            self._ready.set()

    async def _main(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(self.ca.leaf_pem, self.ca.leaf_key)
        origin = await asyncio.start_server(self._origin, "127.0.0.1", 0, ssl=ctx)
        proxy = await asyncio.start_server(self._proxy, "127.0.0.1", self._want[0])
        control = await asyncio.start_server(self._control, "127.0.0.1", self._want[1])
        self.origin_port = origin.sockets[0].getsockname()[1]
        self.proxy_port = proxy.sockets[0].getsockname()[1]
        self.control_port = control.sockets[0].getsockname()[1]
        self._ready.set()
        await self._stop.wait()
        for server in (origin, proxy, control):
            server.close()

    # -- what a test uses ------------------------------------------------------------------------------------------

    @property
    def proxy_url(self) -> str:
        return f"http://127.0.0.1:{self.proxy_port}"

    @property
    def control_url(self) -> str:
        return f"http://127.0.0.1:{self.control_port}"

    def env(self) -> dict[str, str]:
        """Variables that route an unmodified program through the proxy and make it trust the test CA."""
        p = self.proxy_url
        return {
            "HTTPS_PROXY": p,
            "https_proxy": p,
            "HTTP_PROXY": p,
            "http_proxy": p,
            "NO_PROXY": "",
            "no_proxy": "",
            "SSL_CERT_FILE": str(self.ca.ca_pem),
        }

    def set(self, product: str, behavior: str | dict[str, Any] | Behavior, count: int | None = None) -> None:
        self.state.rules.setdefault(product, []).append(_Rule(parse_behavior(behavior), count))

    def script(self, product: str, steps: list[str | dict[str, Any]]) -> None:
        self.state.script[product] = [parse_behavior(s) for s in steps]

    def reset(self) -> None:
        self.state.rules.clear()
        self.state.script.clear()

    def clear_log(self) -> None:
        self.log.clear()
        self.state.counts.clear()

    def requests(self, product: str | None = None) -> list[dict[str, Any]]:
        return [r for r in self.log if r.get("kind") == "request" and (product is None or r["product"] == product)]

    # -- behaviour selection ---------------------------------------------------------------------------------------

    def _choose(self, product: str) -> Behavior:
        index = self.state.counts.get(product, 0)
        self.state.counts[product] = index + 1
        rules = self.state.rules.get(product, [])
        if rules:
            rule = rules[0]
            if rule.remaining is None:
                return rule.behavior
            rule.remaining -= 1
            if rule.remaining <= 0:
                rules.pop(0)
            return rule.behavior
        steps = self.state.script.get(product)
        if steps and index < len(steps):
            return steps[index]
        return Behavior("ok")

    def _rows(self, product: str, query: dict[str, list[str]]) -> list[Any] | None:
        src = self.payloads.get(product)
        if src is None:
            return None
        ids = [i for v in query.get(self.id_param, []) for i in v.split(",") if i]
        if callable(src):
            return list(src(ids))
        rows = list(src)
        if ids:
            wanted = {i.upper() for i in ids}
            rows = [r for r in rows if str(r.get(self.id_field, "")).upper() in wanted]
        return rows

    # -- the TLS origin --------------------------------------------------------------------------------------------

    async def _origin(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._conn_seq += 1
        conn = self._conn_seq
        try:
            while True:
                req = await _read_request(reader)
                if req is None:
                    return
                method, target, headers = req
                url = urlsplit(target)
                query = parse_qs(url.query)
                product = product_of(url.path, self.prefix)
                behavior = self._choose(product) if product else Behavior("ok")
                entry = {
                    "kind": "request",
                    "t": self._clock(),
                    "iso": datetime.now(UTC).isoformat(timespec="milliseconds"),
                    "conn": conn,
                    "method": method,
                    "path": url.path,
                    "query": {k: v[0] for k, v in query.items()},
                    "product": product,
                    "user_agent": headers.get("user-agent"),
                    "if_none_match": headers.get("if-none-match"),
                    "if_modified_since": headers.get("if-modified-since"),
                    "connection": headers.get("connection"),
                    "behavior": behavior.mode,
                    "status": None,
                }
                self.log.append(entry)
                keep = headers.get("connection", "").lower() != "close"
                if not await self._respond(writer, entry, product, query, behavior, headers) or not keep:
                    return
        except (ConnectionError, ssl.SSLError, asyncio.CancelledError):
            pass
        finally:
            with contextlib.suppress(Exception):
                writer.close()

    async def _respond(
        self,
        writer: asyncio.StreamWriter,
        entry: dict[str, Any],
        product: str | None,
        query: dict[str, list[str]],
        b: Behavior,
        headers: dict[str, str],
    ) -> bool:
        """Write one response. False when the connection must not be reused."""
        rows = self._rows(product, query) if product else None
        if product is None or rows is None:
            return await self._send(writer, entry, 404, b'{"error":"not found"}')
        if b.mode == "reset":
            entry["status"] = "reset"
            _reset_socket(writer)
            return False
        if b.mode == "slow":
            await asyncio.sleep(b.ms / 1000)
        if b.mode == "5xx":
            return await self._send(writer, entry, b.status, b'{"error":"injected"}')
        if b.mode == "429":
            extra = {"Retry-After": f"{b.retry_after:g}"} if b.retry_after is not None else {}
            return await self._send(writer, entry, 429, b'{"error":"rate limited"}', extra)
        if b.mode == "204":
            return await self._send(writer, entry, 204, b"")
        if b.mode == "empty200":
            return await self._send(writer, entry, 200, b"")
        if b.mode == "empty_list":
            return await self._send(writer, entry, 200, b"[]")
        if b.mode == "badjson":
            return await self._send(writer, entry, 200, b'[{"icaoId": "KDEN", "rawOb": ')
        body = json.dumps(rows, separators=(",", ":")).encode()
        etag = '"' + hashlib.sha1(body).hexdigest()[:16] + '"'
        extra = {"ETag": etag} if b.etag else {}
        if b.mode == "304":
            return await self._send(writer, entry, 304, b"", extra)
        if b.mode == "drop":
            writer.write(self._head(200, len(body), extra) + body[: b.nbytes])
            await writer.drain()
            entry["status"] = 200
            entry["dropped_after"] = b.nbytes
            _reset_socket(writer)
            return False
        if self.conditional and b.etag and headers.get("if-none-match") == etag:
            return await self._send(writer, entry, 304, b"", extra)
        return await self._send(writer, entry, 200, body, extra)

    @staticmethod
    def _head(status: int, length: int | None, extra: dict[str, str] | None = None) -> bytes:
        reasons = {200: "OK", 204: "No Content", 304: "Not Modified", 404: "Not Found", 429: "Too Many Requests"}
        lines = [
            f"HTTP/1.1 {status} {reasons.get(status, 'Error')}",
            "Content-Type: application/json",
            "Server: faultproxy",
        ]
        if length is not None:
            lines.append(f"Content-Length: {length}")
        lines += [f"{k}: {v}" for k, v in (extra or {}).items()]
        return ("\r\n".join(lines) + "\r\n\r\n").encode()

    async def _send(
        self,
        writer: asyncio.StreamWriter,
        entry: dict[str, Any],
        status: int,
        body: bytes,
        extra: dict[str, str] | None = None,
    ) -> bool:
        entry["status"] = status
        if status in (204, 304):
            writer.write(self._head(status, None, extra))
        else:
            writer.write(self._head(status, len(body), extra) + body)
        await writer.drain()
        return True

    # -- the CONNECT proxy -----------------------------------------------------------------------------------------

    async def _proxy(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        up_writer: asyncio.StreamWriter | None = None
        try:
            req = await _read_request(reader)
            if req is None:
                return
            method, target, headers = req
            host, _, _port = target.partition(":")
            entry = {
                "kind": "connect",
                "t": self._clock(),
                "iso": datetime.now(UTC).isoformat(timespec="milliseconds"),
                "method": method,
                "target": target,
                "user_agent": headers.get("user-agent"),
            }
            self.log.append(entry)
            if method != "CONNECT" or host.lower() != self.host.lower():
                entry["refused"] = True
                writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                await writer.drain()
                return
            up_reader, up_writer = await asyncio.open_connection("127.0.0.1", self.origin_port)
            writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
            await writer.drain()

            async def pump(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
                try:
                    while chunk := await src.read(65536):
                        dst.write(chunk)
                        await dst.drain()
                except (ConnectionError, asyncio.CancelledError):
                    pass
                finally:
                    with contextlib.suppress(Exception):
                        dst.close()

            await asyncio.gather(pump(reader, up_writer), pump(up_reader, writer))
        except (ConnectionError, OSError):
            pass
        finally:
            for w in (writer, up_writer):
                if w is not None:
                    with contextlib.suppress(Exception):
                        w.close()

    # -- the control channel ---------------------------------------------------------------------------------------

    async def _control(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            req = await _read_request(reader)
            if req is None:
                return
            method, target, headers = req
            n = int(headers.get("content-length", "0") or 0)
            raw = await reader.readexactly(n) if n else b""
            path = urlsplit(target).path
            status, out = 200, {"ok": True}
            try:
                data = json.loads(raw) if raw else {}
                if method == "GET" and path == "/log":
                    out = self.log
                elif method == "GET" and path == "/state":
                    out = {
                        "rules": {
                            p: [{"behavior": r.behavior.to_dict(), "remaining": r.remaining} for r in rs]
                            for p, rs in self.state.rules.items()
                        },
                        "script": {p: [b.mode for b in bs] for p, bs in self.state.script.items()},
                        "counts": self.state.counts,
                    }
                elif method == "DELETE" and path == "/log":
                    self.clear_log()
                elif method == "POST" and path == "/rule":
                    self.set(data["product"], data.get("behavior", data), data.get("count"))
                elif method == "POST" and path == "/script":
                    for product, steps in data.items():
                        self.script(product, steps)
                elif method == "POST" and path == "/reset":
                    self.reset()
                else:
                    status, out = 404, {"error": "unknown control path"}
            except (KeyError, ValueError) as exc:
                status, out = 400, {"error": str(exc)}
            body = json.dumps(out).encode()
            writer.write(
                f"HTTP/1.1 {status} X\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n"
                f"Connection: close\r\n\r\n".encode()
                + body
            )
            await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            with contextlib.suppress(Exception):
                writer.close()


def load_awc_payloads(
    fixture_dir: Path, metar: str = "metar_kden_egll.json", taf: str = "taf_kden_egll.json"
) -> Payloads:
    """AWC-shaped payloads from recorded batches; ``stationinfo`` is derived from the METAR rows."""
    metars = json.loads((fixture_dir / metar).read_text(encoding="utf-8"))
    tafs = json.loads((fixture_dir / taf).read_text(encoding="utf-8"))
    seen: dict[str, dict[str, Any]] = {}
    for row in metars:
        seen.setdefault(
            row["icaoId"],
            {
                "icaoId": row["icaoId"],
                "lat": row.get("lat"),
                "lon": row.get("lon"),
                "elev": row.get("elev"),
                "site": row.get("name"),
                "state": "",
                "country": (row.get("name") or "").rsplit(", ", 1)[-1],
            },
        )
    return {"metar": metars, "taf": tafs, "stationinfo": list(seen.values())}
