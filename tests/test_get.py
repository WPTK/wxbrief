"""``wxbrief get`` with the network replaced by the saved batches."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import respx

from wxbrief.__main__ import main
from wxbrief.data.awc import BASE_URL

FIXTURES = Path(__file__).parent / "fixtures" / "awc"


@pytest.fixture
def awc() -> Iterator[respx.MockRouter]:
    metar = (FIXTURES / "metar_kden_egll.json").read_bytes()
    taf = (FIXTURES / "taf_kden_egll.json").read_bytes()
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE_URL}/metar").mock(return_value=httpx.Response(200, content=metar))
        router.get(f"{BASE_URL}/taf").mock(return_value=httpx.Response(200, content=taf))
        yield router


def test_get_plain_prints_decodes_and_raw_taf(awc: respx.MockRouter, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["get", "KDEN", "egll", "--plain"]) == 0
    out = capsys.readouterr().out
    assert "Station:" in out and "KDEN" in out and "EGLL" in out
    assert out.count("TAF (raw):") == 2


def test_get_resolves_iata_codes(awc: respx.MockRouter, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["get", "LHR", "--plain"]) == 0
    assert "EGLL" in capsys.readouterr().out
    assert awc.calls[0].request.url.params["ids"] == "EGLL"


def test_get_json(awc: respx.MockRouter, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["get", "KDEN", "ZZZZ", "--json"]) == 0
    document = json.loads(capsys.readouterr().out)
    assert document["KDEN"]["metar"]["raw"].startswith(("METAR KDEN", "SPECI KDEN"))
    assert document["ZZZZ"] == {"metar": None, "taf_raw": None}


def test_get_total_failure_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    with respx.mock() as router:
        router.get(f"{BASE_URL}/metar").mock(return_value=httpx.Response(500))
        router.get(f"{BASE_URL}/taf").mock(side_effect=httpx.ReadTimeout("slow"))
        assert main(["get", "KDEN"]) == 1
    err = capsys.readouterr().err
    assert "METAR: server error 500" in err and "TAF:" in err


def test_get_partial_failure_prints_what_arrived_and_exits_3(capsys: pytest.CaptureFixture[str]) -> None:
    metar = (FIXTURES / "metar_kden_egll.json").read_bytes()
    with respx.mock() as router:
        router.get(f"{BASE_URL}/metar").mock(return_value=httpx.Response(200, content=metar))
        router.get(f"{BASE_URL}/taf").mock(return_value=httpx.Response(429))
        assert main(["get", "KDEN", "--plain"]) == 3
    captured = capsys.readouterr()
    assert "KDEN" in captured.out and "TAF: rate limited" in captured.err


def test_get_exits_1_when_no_station_has_a_report(capsys: pytest.CaptureFixture[str]) -> None:
    with respx.mock() as router:
        router.get(f"{BASE_URL}/metar").mock(return_value=httpx.Response(204))
        router.get(f"{BASE_URL}/taf").mock(return_value=httpx.Response(204))
        assert main(["get", "ZZZZ"]) == 1
    assert "no METAR" in capsys.readouterr().out


def test_get_discord_is_not_available_yet(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["get", "KDEN", "--discord"]) == 2
    assert "S2b" in capsys.readouterr().err
