"""AwcClient against a mocked aviationweather.gov (respx)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from wxbrief import __version__
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
