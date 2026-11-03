"""Red-team tests for the AWC Data API client: 204 with no body, 429, empty or damaged 200 bodies.

Two layers: respx (no network, no openssl) for every odd header and body, and the repo's fake AWC (FaultProxy) so the
same statuses are exercised over a real TLS socket. No path may let ``json.JSONDecodeError`` (or anything that is not an
``AwcError``) escape the client.
"""

from __future__ import annotations

import json
import shutil
import ssl
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path

import httpx
import pytest
import respx
from uat_kit.faultproxy.server import FaultProxy, load_awc_payloads

from wxbrief.data import awc
from wxbrief.data.awc import BASE_URL, AwcClient, AwcError, ClientError, RateLimited, _retry_after

METAR_URL = f"{BASE_URL}/metar"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "awc"


@pytest.fixture(autouse=True)
def _no_retry_pause(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(awc, "RETRY_DELAY_SECONDS", 0.0)


async def fetch(response: httpx.Response) -> object:
    with respx.mock:
        respx.get(METAR_URL).mock(return_value=response)
        async with AwcClient(retry_delay=0) as client:
            try:
                return await client.metars(["KDEN"])
            except AwcError as exc:
                return exc


# --- respx layer -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(204),
        httpx.Response(204, content=b"junk"),
        httpx.Response(204, headers={"Content-Type": "application/json", "Content-Length": "0"}),
        httpx.Response(200, content=b"\xef\xbb\xbf[]"),
        httpx.Response(200, content=b"[]"),
    ],
)
async def test_no_data_is_an_empty_list(response: httpx.Response) -> None:
    assert await fetch(response) == []


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b""),
        httpx.Response(200, content=b"  \n"),
        httpx.Response(200, content=b"null"),
        httpx.Response(200, content=b"{}"),
        httpx.Response(200, content=b"<html>Service Unavailable</html>"),
        httpx.Response(200, content=b'[{"icaoId":"KDEN","rawOb":"KDEN 01'),
        httpx.Response(200, content=b"[" * 100_000),
        httpx.Response(200, content=b"[1" + b"0" * 10_000 + b"]"),
        httpx.Response(200, content=b'[{"icaoId":"KDEN","rawOb":"\xe9"}]'),
        httpx.Response(400, content=b"No data"),
        httpx.Response(404),
        httpx.Response(301, headers={"Location": "/elsewhere"}),
    ],
)
async def test_damaged_answers_raise_awc_error_never_a_json_error(response: httpx.Response) -> None:
    result = await fetch(response)
    assert isinstance(result, ClientError), result


@pytest.mark.parametrize(
    ("header", "seconds"),
    [
        (None, 60.0),
        ("", 60.0),
        ("0", 0.0),
        ("-5", 60.0),
        ("nan", 60.0),
        ("inf", 60.0),
        ("1e999", 60.0),
        ("abc", 60.0),
        ("30, 60", 60.0),
        ("  45  ", 45.0),
        ("7200", 3600.0),
        ("5.5", 60.0),
        ("0x10", 60.0),
    ],
)
async def test_429_retry_after_is_bounded_and_never_raises(header: str | None, seconds: float) -> None:
    headers = {} if header is None else {"Retry-After": header}
    result = await fetch(httpx.Response(429, headers=headers, content=b"[]"))
    assert isinstance(result, RateLimited) and result.retry_after == seconds


async def test_429_retry_after_http_date_in_the_future() -> None:
    when = datetime.now(UTC) + timedelta(seconds=120)
    result = await fetch(httpx.Response(429, headers={"Retry-After": format_datetime(when, usegmt=True)}))
    assert isinstance(result, RateLimited) and 100 <= result.retry_after <= 121


@pytest.mark.parametrize("stamp", ["Wed, 21 Oct 2015 07:28:00 GMT", "Wed, 21 Oct 2026 07:28:00 -0000", "not a date"])
def test_retry_after_http_date_in_the_past_or_naive_is_not_negative(stamp: str) -> None:
    value = _retry_after(httpx.Response(429, headers={"Retry-After": stamp}))
    assert 0.0 <= value <= 3600.0


@pytest.mark.parametrize("header", ["1e3", "1_0", "+5", "5.", ".5"])
def test_rt03_retry_after_is_delta_seconds_or_an_http_date_only(header: str) -> None:
    """RFC 9110: delta-seconds is 1*DIGIT. float() also takes exponents, underscores and signs."""
    assert _retry_after(httpx.Response(429, headers={"Retry-After": header})) == awc.DEFAULT_RETRY_AFTER


# --- the repo's fake AWC over real TLS -------------------------------------------------------------------------------

needs_openssl = pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl is needed to make the test CA")


@pytest.fixture
def fake(tmp_path: Path):
    with FaultProxy(load_awc_payloads(FIXTURES), directory=tmp_path / "pki") as proxy:
        yield proxy


async def through_fake(fake: FaultProxy, spec: str, call: str = "metars") -> object:
    context = ssl.create_default_context(cafile=str(fake.ca.ca_pem))
    async with httpx.AsyncClient(proxy=fake.proxy_url, verify=context, timeout=10) as http:
        client = AwcClient(client=http, retry_delay=0)
        fake.set("metar" if call == "metars" else "taf", spec)
        try:
            return await getattr(client, call)(["KDEN"])
        except AwcError as exc:
            return exc


@needs_openssl
@pytest.mark.parametrize("call", ["metars", "tafs"])
async def test_fake_204_with_no_body_is_an_empty_list(fake: FaultProxy, call: str) -> None:
    assert await through_fake(fake, "204", call) == []


@needs_openssl
@pytest.mark.parametrize("call", ["metars", "tafs"])
async def test_fake_429_raises_rate_limited_with_the_server_wait(fake: FaultProxy, call: str) -> None:
    result = await through_fake(fake, "429:42", call)
    assert isinstance(result, RateLimited) and result.retry_after == 42.0


@needs_openssl
@pytest.mark.parametrize("spec", ["empty200", "badjson", "5xx", "502", "drop:20"])
async def test_fake_damaged_answers_are_awc_errors(fake: FaultProxy, spec: str) -> None:
    result = await through_fake(fake, spec)
    assert isinstance(result, AwcError), (spec, result)
    assert not isinstance(result, json.JSONDecodeError)
