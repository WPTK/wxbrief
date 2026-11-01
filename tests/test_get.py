"""``wxbrief get`` with the network replaced by the saved batches."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
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
    assert out.count("TAF") >= 2


def test_get_resolves_iata_codes(awc: respx.MockRouter, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["get", "LHR", "--plain"]) == 0
    assert "EGLL" in capsys.readouterr().out
    assert awc.calls[0].request.url.params["ids"] == "EGLL"


def test_get_json(awc: respx.MockRouter, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["get", "KDEN", "ZZZZ", "--json"]) == 3  # ZZZZ got nothing: not a clean run
    document = json.loads(capsys.readouterr().out)
    assert document["KDEN"]["metar"]["raw"].startswith(("METAR KDEN", "SPECI KDEN"))
    assert document["KDEN"]["taf"]["raw"].startswith("TAF KDEN")
    assert document["ZZZZ"] == {"metar": None, "taf": None, "stale": False, "errors": []}


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


def test_get_discord_prints_fenced_blocks_with_station_names(
    awc: respx.MockRouter, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["get", "EGLL", "--discord"]) == 0
    out = capsys.readouterr().out
    assert out.count("````") == 4  # one outer fence pair per report: the METAR and the TAF
    assert "LONDON/HEATHROW" in out.upper() and "TAF issued" in out


def test_get_decodes_the_taf(awc: respx.MockRouter, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["get", "EGLL", "--plain"]) == 0
    out = capsys.readouterr().out
    assert "worst flight category" in out


def _clear_kden(observed: datetime) -> bytes:
    """A clear-sky KDEN METAR observed at ``observed`` (UTC), shaped like the AWC JSON."""
    record = json.loads((FIXTURES / "metar_kden_egll.json").read_bytes())[0]
    stamp = observed.strftime("%d%H%MZ")
    record.update(
        obsTime=int(observed.timestamp()),
        rawOb=f"METAR KDEN {stamp} 00000KT 10SM CLR 10/00 A3001",
        wxString=None,
        vertVis=None,
        cover="CLR",
        clouds=[],
        visib=10,
        fltCat="VFR",
        metarType="METAR",
    )
    return json.dumps([record]).encode()


@pytest.mark.parametrize(("hour", "emoji"), [(3, "🌙"), (18, "☀️")])
def test_get_discord_clear_sky_glyph_follows_the_sun_at_the_station(
    hour: int, emoji: str, capsys: pytest.CaptureFixture[str]
) -> None:
    # Denver on 2026-10-31: 03:00Z is evening dark, 18:00Z is midday. Swapping lat and lon would call 03:00Z day.
    metar = _clear_kden(datetime(2026, 10, 31, hour, tzinfo=UTC))
    with respx.mock() as router:
        router.get(f"{BASE_URL}/metar").mock(return_value=httpx.Response(200, content=metar))
        router.get(f"{BASE_URL}/taf").mock(return_value=httpx.Response(200, content=b"[]"))
        assert main(["get", "KDEN", "--discord"]) == 0
    title = next(line for line in capsys.readouterr().out.splitlines() if "KDEN" in line and "DENVER" in line.upper())
    assert title.startswith(emoji)


def test_get_keeps_the_modifier_awc_puts_in_remarks(capsys: pytest.CaptureFixture[str]) -> None:
    rows = json.loads((FIXTURES / "taf_us_20261031.json").read_text(encoding="utf-8"))
    katl = [row for row in rows if row["icaoId"] == "KATL"]
    assert katl[0]["remarks"].strip() == "AMD" and "AMD" not in katl[0]["rawTAF"].split()[:3]
    with respx.mock() as router:
        router.get(f"{BASE_URL}/metar").mock(return_value=httpx.Response(204))
        router.get(f"{BASE_URL}/taf").mock(return_value=httpx.Response(200, json=katl))
        main(["get", "KATL", "--json"])
        document = json.loads(capsys.readouterr().out)
        assert "AMD" in json.dumps(document["KATL"]["taf"]["modifiers"])
        main(["get", "KATL", "--discord"])
    assert "AMD" in capsys.readouterr().out
