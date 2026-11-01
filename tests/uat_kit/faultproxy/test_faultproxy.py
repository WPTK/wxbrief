"""faultproxy self-tests: an ordinary httpx client reaches the fake through the proxy with only the two variables."""

from __future__ import annotations

import json
import shutil
import ssl
from pathlib import Path

import httpx
import pytest

from uat_kit.faultproxy.server import FaultProxy, load_awc_payloads, parse_behavior

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "awc"
pytestmark = pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl is needed to make the test CA")

URL = "https://aviationweather.gov/api/data"


@pytest.fixture
def fp(tmp_path: Path):
    with FaultProxy(load_awc_payloads(FIXTURES), directory=tmp_path / "pki") as proxy:
        yield proxy


def client(fp: FaultProxy, **kw: object) -> httpx.Client:
    ctx = ssl.create_default_context(cafile=str(fp.ca.ca_pem))
    return httpx.Client(proxy=fp.proxy_url, verify=ctx, headers={"User-Agent": "faultproxy-test/1"}, timeout=10, **kw)


def test_ok_filters_by_id_and_logs_the_request(fp: FaultProxy) -> None:
    with client(fp) as c:
        r = c.get(f"{URL}/metar", params={"ids": "KDEN", "format": "json"})
    assert r.status_code == 200
    assert {row["icaoId"] for row in r.json()} == {"KDEN"}
    (entry,) = fp.requests("metar")
    assert entry["user_agent"] == "faultproxy-test/1" and entry["query"]["ids"] == "KDEN" and entry["status"] == 200


def test_stationinfo_is_served(fp: FaultProxy) -> None:
    with client(fp) as c:
        rows = c.get(f"{URL}/stationinfo", params={"ids": "EGLL"}).json()
    assert [r["icaoId"] for r in rows] == ["EGLL"]


@pytest.mark.parametrize(
    ("spec", "status"),
    [("5xx", 503), ("502", 502), ("429:30", 429), ("204", 204), ("empty200", 200), ("badjson", 200), ("304", 304)],
)
def test_fault_statuses(fp: FaultProxy, spec: str, status: int) -> None:
    fp.set("taf", spec)
    with client(fp) as c:
        r = c.get(f"{URL}/taf", params={"ids": "KDEN"})
    assert r.status_code == status
    if spec == "429:30":
        assert r.headers["Retry-After"] == "30"
    if spec == "empty200":
        assert r.content == b""
    if spec == "badjson":
        with pytest.raises(json.JSONDecodeError):
            r.json()


def test_reset_and_drop_raise_transport_errors(fp: FaultProxy) -> None:
    fp.set("metar", "reset", count=1)
    fp.set("metar", "drop:40", count=1)
    with client(fp) as c:
        for _ in range(2):
            with pytest.raises(httpx.TransportError):
                c.get(f"{URL}/metar", params={"ids": "KDEN"})
        assert c.get(f"{URL}/metar", params={"ids": "KDEN"}).status_code == 200


def test_count_script_and_products_are_independent(fp: FaultProxy) -> None:
    fp.set("taf", "5xx", count=2)
    fp.script("metar", ["ok", "429:5"])
    with client(fp) as c:
        taf = [c.get(f"{URL}/taf", params={"ids": "KDEN"}).status_code for _ in range(3)]
        metar = [c.get(f"{URL}/metar", params={"ids": "KDEN"}).status_code for _ in range(3)]
    assert taf == [503, 503, 200]
    assert metar == [200, 429, 200]


def test_conditional_request_gets_304_and_the_log_shows_the_validator(fp: FaultProxy) -> None:
    fp.conditional = True
    with client(fp) as c:
        first = c.get(f"{URL}/metar", params={"ids": "KDEN"})
        second = c.get(f"{URL}/metar", params={"ids": "KDEN"}, headers={"If-None-Match": first.headers["ETag"]})
    assert second.status_code == 304
    assert fp.requests("metar")[1]["if_none_match"] == first.headers["ETag"]


def test_control_channel_sets_rules_and_returns_the_log(fp: FaultProxy) -> None:
    with httpx.Client(base_url=fp.control_url) as ctl, client(fp) as c:
        assert ctl.post("/rule", json={"product": "taf", "behavior": "5xx", "count": 1}).json() == {"ok": True}
        assert c.get(f"{URL}/taf", params={"ids": "KDEN"}).status_code == 503
        assert c.get(f"{URL}/taf", params={"ids": "KDEN"}).status_code == 200
        assert [e["status"] for e in ctl.get("/log").json() if e["kind"] == "request"] == [503, 200]
        assert ctl.post("/rule", json={"product": "taf", "behavior": "nonsense"}).status_code == 400
        ctl.delete("/log")
        assert ctl.get("/log").json() == []


def test_other_hosts_are_refused_so_nothing_reaches_the_real_network(fp: FaultProxy) -> None:
    with client(fp) as c, pytest.raises(httpx.ProxyError):
        c.get("https://example.com/")
    assert any(e.get("refused") for e in fp.log)


def test_parse_behavior_shorthands() -> None:
    assert parse_behavior("slow:250").ms == 250
    assert parse_behavior({"mode": "5xx", "status": 500}).status == 500
    with pytest.raises(ValueError):
        parse_behavior("wat")
