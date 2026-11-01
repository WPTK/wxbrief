"""AwcClient against a mocked aviationweather.gov (respx)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
import respx

from wxbrief import __version__
from wxbrief.data import awc
from wxbrief.data.awc import (
    BASE_URL,
    USER_AGENT,
    AwcClient,
    ClientError,
    RateLimited,
    ServerError,
    TransportError,
)
from wxbrief.data.models import latest_by_station, parse_metars, parse_visibility


@pytest.fixture(autouse=True)
def _no_retry_pause(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(awc, "RETRY_DELAY_SECONDS", 0.0)


FIXTURES = Path(__file__).parent / "fixtures" / "awc"
METAR_URL = f"{BASE_URL}/metar"


def _payload(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


@respx.mock
async def test_metars_200_parses_rows_and_sends_params_and_user_agent() -> None:
    route = respx.get(METAR_URL).mock(return_value=httpx.Response(200, content=_payload("metar_kden_egll.json")))
    async with AwcClient() as client:
        rows = await client.metars(["kden", "EGLL", "KDEN"])
    request = route.calls.last.request
    assert request.url.params["ids"] == "KDEN,EGLL"
    assert request.url.params["format"] == "json"
    assert request.url.params["hours"] == "2"
    assert request.headers["User-Agent"] == USER_AGENT == f"wxbrief/{__version__} (+https://github.com/WPTK/wxbrief)"
    assert {row.icao for row in rows} == {"KDEN", "EGLL"}
    newest = latest_by_station(rows)
    assert newest["EGLL"].raw.startswith("METAR EGLL")
    assert newest["EGLL"].visibility_sm == 6.0 and newest["EGLL"].visibility_is_minimum


@respx.mock
async def test_tafs_200() -> None:
    respx.get(f"{BASE_URL}/taf").mock(return_value=httpx.Response(200, content=_payload("taf_kden_egll.json")))
    async with AwcClient() as client:
        rows = await client.tafs(["KDEN", "EGLL"])
    assert {row.icao for row in rows} == {"KDEN", "EGLL"}
    assert all(row.raw.startswith("TAF") and row.issued for row in rows)


@respx.mock
async def test_stations_200() -> None:
    body = [{"icaoId": "KDEN", "iataId": "DEN", "site": "Denver Intl", "lat": 39.8, "lon": -104.6, "siteType": ["METAR"]}]
    respx.get(f"{BASE_URL}/stationinfo").mock(return_value=httpx.Response(200, json=body))
    async with AwcClient() as client:
        rows = await client.stations(["KDEN"])
    assert rows[0].name == "Denver Intl" and rows[0].site_types == ("METAR",)


@respx.mock
async def test_204_is_an_empty_list() -> None:
    respx.get(METAR_URL).mock(return_value=httpx.Response(204))
    async with AwcClient() as client:
        assert await client.metars(["ZZZZ"]) == []


@respx.mock
@pytest.mark.parametrize(
    ("headers", "expected"), [({"Retry-After": "42"}, 42.0), ({}, 60.0), ({"Retry-After": "soon"}, 60.0)]
)
async def test_429_raises_rate_limited_with_retry_after(headers: dict[str, str], expected: float) -> None:
    respx.get(METAR_URL).mock(return_value=httpx.Response(429, headers=headers))
    async with AwcClient() as client:
        with pytest.raises(RateLimited) as caught:
            await client.metars(["KDEN"])
    assert caught.value.retry_after == expected


@respx.mock
async def test_500_raises_server_error() -> None:
    respx.get(METAR_URL).mock(return_value=httpx.Response(503))
    async with AwcClient() as client:
        with pytest.raises(ServerError) as caught:
            await client.metars(["KDEN"])
    assert caught.value.status == 503


@respx.mock
async def test_timeout_raises_transport_error() -> None:
    respx.get(METAR_URL).mock(side_effect=httpx.ReadTimeout("slow"))
    async with AwcClient() as client:
        with pytest.raises(TransportError):
            await client.metars(["KDEN"])


@respx.mock
async def test_connect_error_raises_transport_error() -> None:
    respx.get(METAR_URL).mock(side_effect=httpx.ConnectError(""))
    async with AwcClient() as client:
        with pytest.raises(TransportError):
            await client.metars(["KDEN"])


@respx.mock
@pytest.mark.parametrize("response", [httpx.Response(404), httpx.Response(200, content=b"<html>")])
async def test_other_failures_are_client_errors(response: httpx.Response) -> None:
    respx.get(METAR_URL).mock(return_value=response)
    async with AwcClient() as client:
        with pytest.raises(ClientError):
            await client.metars(["KDEN"])


@respx.mock
async def test_ids_are_chunked_at_400() -> None:
    route = respx.get(METAR_URL).mock(return_value=httpx.Response(200, json=[]))
    ids = [f"K{n:03d}" for n in range(850)]
    async with AwcClient() as client:
        await client.metars(ids)
    sizes = [len(call.request.url.params["ids"].split(",")) for call in route.calls]
    assert sizes == [400, 400, 50]


@respx.mock
async def test_a_failure_in_a_later_chunk_propagates() -> None:
    respx.get(METAR_URL).mock(
        side_effect=[httpx.Response(200, json=[]), httpx.Response(429, headers={"Retry-After": "5"})]
    )
    async with AwcClient() as client:
        with pytest.raises(RateLimited):
            await client.metars([f"K{n:03d}" for n in range(401)])


def test_parsing_is_tolerant() -> None:
    rows = parse_metars(
        [
            {"icaoId": "KABC", "rawOb": "METAR KABC 010000Z VRB03KT", "wdir": "VRB", "wspd": "x", "obsTime": "bad"},
            {"icaoId": "KDEF"},  # no raw report: dropped
            "junk",
            None,
        ]
    )
    assert len(rows) == 1
    assert rows[0].wind_variable and rows[0].wind_direction is None and rows[0].wind_speed_kt is None
    assert rows[0].observed is None
    assert parse_metars({"not": "a list"}) == []
    assert parse_visibility("10+") == (10.0, True)
    assert parse_visibility(0.25) == (0.25, False)
    assert parse_visibility("garbage") == (None, False)
    assert json.loads(json.dumps(rows[0].source))["icaoId"] == "KABC"


def test_non_finite_numbers_cannot_crash_parsing() -> None:
    payload = json.loads(
        '[{"icaoId": "KABC", "rawOb": "METAR KABC", "wdir": NaN, "wspd": 1e400, "obsTime": 1e400, '
        '"temp": Infinity, "visib": NaN}]'
    )
    rows = parse_metars([*payload, {"icaoId": "KDEF", "rawOb": "METAR KDEF", "wspd": 10**400}])
    assert [r.icao for r in rows] == ["KABC", "KDEF"]
    assert all(r.wind_direction is None and r.wind_speed_kt is None and r.temperature_c is None for r in rows)
    assert rows[0].observed is None and rows[0].visibility_sm is None


@respx.mock
@pytest.mark.parametrize("body", [{"error": "Invalid ids"}, "text", 5, None])
async def test_a_200_body_that_is_not_a_list_is_a_client_error(body: object) -> None:
    respx.get(METAR_URL).mock(return_value=httpx.Response(200, json=body))
    async with AwcClient() as client:
        with pytest.raises(ClientError):
            await client.metars(["KDEN"])


@respx.mock
async def test_retry_after_accepts_an_http_date_and_is_capped_at_an_hour() -> None:
    from datetime import UTC, datetime, timedelta
    from email.utils import format_datetime

    when = format_datetime(datetime.now(UTC) + timedelta(seconds=300), usegmt=True)
    for header, low, high in ((when, 280, 301), ("999999999", 3600, 3600), ("7200", 3600, 3600), ("inf", 60, 60), ("nan", 60, 60)):
        respx.get(METAR_URL).mock(return_value=httpx.Response(429, headers={"Retry-After": header}))
        async with AwcClient() as client:
            with pytest.raises(RateLimited) as caught:
                await client.metars(["KDEN"])
        assert low <= caught.value.retry_after <= high, header


async def test_a_dripping_body_hits_the_total_deadline() -> None:
    import asyncio

    async def drip() -> object:
        yield b"["
        await asyncio.sleep(5)
        yield b"]"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=drip())

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    async with AwcClient(client=http, deadline=0.2) as client:
        with pytest.raises(TransportError):
            await client.metars(["KDEN"])


@respx.mock
async def test_a_repeat_request_is_revalidated_and_a_304_reuses_the_rows() -> None:
    body = _payload("metar_kden_egll.json")
    route = respx.get(METAR_URL).mock(
        side_effect=[
            httpx.Response(200, content=body, headers={"ETag": '"v1"', "Last-Modified": "Sat, 31 Oct 2026 12:00:00 GMT"}),
            httpx.Response(304, headers={"ETag": '"v1b"'}),
            httpx.Response(304),
        ]
    )
    async with AwcClient() as client:
        first = await client.metars(["KDEN", "EGLL"])
        second = await client.metars(["KDEN", "EGLL"])
        await client.metars(["KDEN", "EGLL"])
    assert route.call_count == 3
    assert "If-None-Match" not in route.calls[0].request.headers
    sent = route.calls[1].request.headers
    assert sent["If-None-Match"] == '"v1"' and sent["If-Modified-Since"] == "Sat, 31 Oct 2026 12:00:00 GMT"
    assert [m.raw for m in second] == [m.raw for m in first] and first
    # the 304 replaced the ETag and nothing else: the Last-Modified from the 200 is still sent
    third = route.calls[2].request.headers
    assert third["If-None-Match"] == '"v1b"' and third["If-Modified-Since"] == "Sat, 31 Oct 2026 12:00:00 GMT"


@respx.mock
@pytest.mark.parametrize("control", ["max-age=600", "public, max-age=3600", "max-age=1", "no-store", ""])
async def test_max_age_never_skips_a_request(control: str) -> None:
    """A max-age shorter or longer than the 10-minute poll must not make a poll show an old report as current."""
    headers = {"ETag": '"v1"'} | ({"Cache-Control": control} if control else {})
    route = respx.get(METAR_URL).mock(return_value=httpx.Response(200, content=b"[]", headers=headers))
    async with AwcClient() as client:
        await client.metars(["KDEN"])
        await client.metars(["KDEN"])
    assert route.call_count == 2


@respx.mock
async def test_a_changed_report_replaces_the_stored_rows_and_nothing_old_is_returned() -> None:
    old, new = _payload("metar_kden_egll.json"), b"[]"
    respx.get(METAR_URL).mock(
        side_effect=[httpx.Response(200, content=old, headers={"ETag": '"a"'}), httpx.Response(200, content=new, headers={"ETag": '"b"'})]
    )
    async with AwcClient() as client:
        assert await client.metars(["KDEN", "EGLL"])
        assert await client.metars(["KDEN", "EGLL"]) == []


@respx.mock
async def test_errors_and_204_are_not_masked_by_the_stored_response() -> None:
    route = respx.get(METAR_URL).mock(
        side_effect=[
            httpx.Response(200, content=_payload("metar_kden_egll.json"), headers={"ETag": '"a"'}),
            httpx.Response(500),
            httpx.Response(500),  # the retry
            httpx.ConnectError("offline"),
            httpx.ConnectError("offline"),  # the retry
            httpx.Response(204),
            httpx.Response(200, content=b"[]"),
        ]
    )
    async with AwcClient() as client:
        await client.metars(["KDEN"])
        with pytest.raises(ServerError):
            await client.metars(["KDEN"])
        with pytest.raises(TransportError):
            await client.metars(["KDEN"])
        assert await client.metars(["KDEN"]) == []
        assert await client.metars(["KDEN"]) == []
    assert "If-None-Match" not in route.calls[6].request.headers  # the 204 dropped the validators


@respx.mock
async def test_the_stored_requests_are_bounded() -> None:
    from wxbrief.data.awc import CACHED_REQUESTS

    respx.get(METAR_URL).mock(return_value=httpx.Response(200, content=b"[]", headers={"ETag": '"a"'}))
    async with AwcClient() as client:
        for index in range(CACHED_REQUESTS + 2):
            await client.metars([f"K{index:03d}"])
        assert len(client._stored) == CACHED_REQUESTS


@respx.mock
async def test_a_429_after_a_stored_response_still_raises_with_retry_after() -> None:
    respx.get(METAR_URL).mock(
        side_effect=[
            httpx.Response(200, content=b"[]", headers={"ETag": '"a"'}),
            httpx.Response(429, headers={"Retry-After": "90"}),
        ]
    )
    async with AwcClient() as client:
        await client.metars(["KDEN"])
        with pytest.raises(RateLimited) as caught:
            await client.metars(["KDEN"])
    assert caught.value.retry_after == 90.0


@respx.mock
@pytest.mark.parametrize("error", [httpx.ReadTimeout("slow"), httpx.ConnectError("refused")])
async def test_one_transient_error_is_retried_once(error: httpx.TransportError) -> None:
    route = respx.get(METAR_URL).mock(
        side_effect=[error, httpx.Response(200, content=_payload("metar_kden_egll.json"))]
    )
    async with AwcClient() as client:
        assert await client.metars(["KDEN", "EGLL"])
    assert route.call_count == 2


@respx.mock
async def test_the_retry_asks_for_a_fresh_connection() -> None:
    route = respx.get(METAR_URL).mock(
        side_effect=[httpx.RemoteProtocolError("closed"), httpx.Response(200, content=b"[]")]
    )
    async with AwcClient() as client:
        assert await client.metars(["KDEN"]) == []
    first, second = (call.request for call in route.calls)
    assert "Connection" not in first.headers or first.headers["Connection"] != "close"
    assert second.headers["Connection"] == "close"


@respx.mock
async def test_two_transient_errors_raise_transport_error_after_two_calls() -> None:
    route = respx.get(METAR_URL).mock(side_effect=httpx.ReadTimeout("slow"))
    async with AwcClient() as client:
        with pytest.raises(TransportError):
            await asyncio.wait_for(client.metars(["KDEN"]), 5)
    assert route.call_count == 2


@respx.mock
async def test_a_5xx_is_retried_once() -> None:
    route = respx.get(METAR_URL).mock(side_effect=[httpx.Response(502), httpx.Response(200, content=b"[]")])
    async with AwcClient() as client:
        assert await client.metars(["KDEN"]) == []
    assert route.call_count == 2


@respx.mock
async def test_a_429_is_not_retried() -> None:
    route = respx.get(METAR_URL).mock(return_value=httpx.Response(429, headers={"Retry-After": "30"}))
    async with AwcClient() as client:
        with pytest.raises(RateLimited):
            await client.metars(["KDEN"])
    assert route.call_count == 1


async def test_a_dripping_body_is_not_retried_past_the_deadline() -> None:
    calls = 0

    async def drip() -> object:
        yield b"["
        await asyncio.sleep(5)
        yield b"]"

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=drip())

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    loop = asyncio.get_running_loop()
    start = loop.time()
    async with AwcClient(client=http, deadline=0.3) as client:
        with pytest.raises(TransportError):
            await client.metars(["KDEN"])
    assert loop.time() - start < 1.5
    assert calls == 1


async def test_a_second_request_survives_a_connection_the_server_closed() -> None:
    """A server that closes the socket after each response (as an idle-timeout would) must not fail the next
    request on the same client."""
    served = 0

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        nonlocal served
        await reader.readuntil(b"\r\n\r\n")
        served += 1
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2\r\n\r\n[]")
        await writer.drain()
        writer.close()  # without a Connection: close header, so the client keeps the pooled connection

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    http = httpx.AsyncClient(
        limits=httpx.Limits(keepalive_expiry=60), timeout=5, headers={"User-Agent": USER_AGENT}
    )
    try:
        async with AwcClient(base_url=f"http://127.0.0.1:{port}", client=http) as client:
            assert await client.metars(["KDEN"]) == []
            await asyncio.sleep(0.1)
            assert await client.metars(["KDEN"]) == []
    finally:
        await http.aclose()
        server.close()
        await server.wait_closed()
    assert served == 2
