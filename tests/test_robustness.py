"""Robustness fixes: state and cache hygiene, the AWC client's limits, config loading and saving, the command line's
edges, and the app's save, toast and offline paths."""

from __future__ import annotations

import io
import json
import os
import sys
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from test_app_smoke import METARS, NOW, TAFS, make_app, notes, offline_client, wait_for

from wxbrief import __main__ as cli
from wxbrief.__main__ import main
from wxbrief.config import (
    Config,
    clean_watchlist,
    config_text,
    load_config,
    parse_config,
    save_config,
    station_id,
)
from wxbrief.data import cache as cache_module
from wxbrief.data.awc import BASE_URL, AwcClient, ClientError, TransportError
from wxbrief.data.cache import DiskCache, default_cache_dir
from wxbrief.data.models import parse_metars, parse_tafs
from wxbrief.data.poll import Product
from wxbrief.i18n.keys import K
from wxbrief.state import FETCHED_KEY, AppState

FIXTURES = Path(__file__).parent / "fixtures" / "awc"
KDEN_METAR = METARS[0]["rawOb"]


def metar_rows(*icaos: str) -> list[Any]:
    return parse_metars([row for row in METARS if row["icaoId"] in icaos])


def taf_rows(*icaos: str) -> list[Any]:
    return parse_tafs([row for row in TAFS if row["icaoId"] in icaos])


# --- state -------------------------------------------------------------------------------------------------------


def test_a_taf_a_successful_fetch_no_longer_returns_is_dropped() -> None:
    state = AppState(["KDEN", "EGLL"], now=lambda: NOW)
    state.apply(Product.TAF, taf_rows("KDEN", "EGLL"))
    assert state.stations["KDEN"].taf is not None
    state.apply(Product.TAF, taf_rows("EGLL"))  # the fetch worked and KDEN is not in it
    assert state.stations["KDEN"].taf is None and state.stations["KDEN"].awc_taf is None
    assert state.stations["EGLL"].taf is not None


def test_the_cached_label_is_tracked_per_product(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path)
    first = AppState(["KDEN"], cache=cache, now=lambda: NOW)
    first.apply(Product.METAR, metar_rows("KDEN"))
    first.apply(Product.TAF, taf_rows("KDEN"))
    second = AppState(["KDEN"], cache=cache, now=lambda: NOW + timedelta(hours=1))
    second.load_cache()
    second.apply(Product.METAR, metar_rows("KDEN"))  # a fresh METAR; the forecast is still the cached one
    entry = second.stations["KDEN"]
    assert not entry.metar_cached and entry.taf_cached
    assert not entry.from_cache  # the label describes the report shown first


def test_rows_for_unlisted_stations_and_expired_tafs_are_not_written(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path)
    state = AppState(["KDEN", "EGLL"], cache=cache, now=lambda: NOW)
    state.apply(Product.METAR, metar_rows("KDEN", "EGLL"))
    state.apply(Product.TAF, taf_rows("KDEN", "EGLL"))
    state.remove("EGLL")
    state.apply(Product.METAR, metar_rows("KDEN"))
    assert [row["icaoId"] for row in cache.read("metars")[1]] == ["KDEN"]  # type: ignore[index]
    state.now = lambda: NOW + timedelta(days=3)  # long past every forecast in the batch
    state.apply(Product.METAR, [])
    state.apply(Product.TAF, taf_rows("KDEN"))
    assert cache.read("tafs")[1] == []  # type: ignore[index]


def test_a_cached_row_keeps_its_own_fetch_time(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path)
    state = AppState(["KDEN", "EGLL"], cache=cache, now=lambda: NOW)
    state.apply(Product.METAR, metar_rows("KDEN", "EGLL"))
    state.now = lambda: NOW + timedelta(minutes=10)
    state.apply(Product.METAR, metar_rows("KDEN"))  # EGLL had no new report: its row keeps the older stamp
    later = AppState(["KDEN", "EGLL"], cache=cache, now=lambda: NOW + timedelta(days=1))
    later.load_cache()
    assert later.stations["KDEN"].updated == NOW + timedelta(minutes=10)
    assert later.stations["EGLL"].updated == NOW
    assert later.stations["EGLL"].awc_metar.source[FETCHED_KEY] == NOW.isoformat()  # type: ignore[union-attr]


def test_removing_the_last_station_clears_a_stale_failure() -> None:
    state = AppState(["KDEN"], now=lambda: NOW)
    state.record_error(Product.METAR, "metar: down", offline=True)
    state.remove("KDEN")
    assert not state.errors and not state.offline


# --- the AWC client ----------------------------------------------------------------------------------------------


async def test_an_oversized_body_is_rejected_as_a_client_error() -> None:
    big = b"[" + b"0," * (5 * 1024 * 1024) + b"0]"  # about 10 MB
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=big))
    async with AwcClient(client=httpx.AsyncClient(transport=transport)) as client:
        with pytest.raises(ClientError, match="larger than"):
            await client.metars(["KDEN"])


async def test_a_declared_oversize_is_rejected_before_reading() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=b"[]", headers={"Content-Length": str(10 * 1024 * 1024)})
    )
    async with AwcClient(client=httpx.AsyncClient(transport=transport)) as client:
        with pytest.raises(ClientError, match="larger than"):
            await client.metars(["KDEN"])


async def test_a_deeply_nested_body_is_a_client_error() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"[" * 200000 + b"]" * 200000))
    async with AwcClient(client=httpx.AsyncClient(transport=transport)) as client:
        with pytest.raises(ClientError):
            await client.metars(["KDEN"])


def test_a_client_that_cannot_be_built_is_a_transport_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise ImportError("Using SOCKS proxy, but the 'socksio' package is not installed.")

    monkeypatch.setattr(httpx, "AsyncClient", refuse)
    with pytest.raises(TransportError, match="socksio"):
        AwcClient()


# --- the cache ---------------------------------------------------------------------------------------------------


def test_load_cache_removes_temp_files_a_killed_writer_left(tmp_path: Path) -> None:
    old = tmp_path / ".metars.abc123.tmp"
    recent = tmp_path / ".tafs.def456.tmp"
    keep = tmp_path / "notes.tmp"
    for path in (old, recent, keep):
        path.write_text("x", encoding="utf-8")
    long_ago = (datetime.now(UTC) - timedelta(days=1)).timestamp()
    os.utime(old, (long_ago, long_ago))
    os.utime(keep, (long_ago, long_ago))
    AppState(cache=DiskCache(tmp_path)).load_cache()
    assert not old.exists()
    assert recent.exists()  # it could be another process mid-write
    assert keep.exists()  # not ours


def test_an_unresolvable_home_in_the_cache_variable_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(self: Path) -> Path:
        raise RuntimeError("Could not determine home directory.")

    monkeypatch.setenv(cache_module.CACHE_DIR_ENV, "~nosuchuser/wx")
    monkeypatch.setattr(Path, "expanduser", refuse)
    assert "wxbrief" in default_cache_dir().parts  # the platform folder, not a crash


# --- config ------------------------------------------------------------------------------------------------------


def test_an_invalid_glyph_set_and_language_fall_back_with_a_warning() -> None:
    loaded = parse_config({"view": {"glyph_set": "wingdings", "lang": "tlh"}})
    assert loaded.config.view.glyph_set == "nerd" and loaded.config.view.lang == "en"
    assert len(loaded.warnings) == 2


def test_glyph_set_and_language_are_case_folded() -> None:
    loaded = parse_config({"view": {"glyph_set": "ASCII", "lang": "PT-br"}})
    assert (loaded.config.view.glyph_set, loaded.config.view.lang) == ("ascii", "pt")
    assert not loaded.warnings


@pytest.mark.parametrize(
    "text", ["a = " + "1" * 5000 + "\n", "a = " + "[" * 100000 + "\n"], ids=["huge-integer", "deep-nesting"]
)
def test_load_never_raises_on_what_tomllib_leaks(tmp_path: Path, text: str) -> None:
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    loaded = load_config(path)
    assert not loaded.usable and loaded.warnings


def test_save_keeps_the_mode_and_flushes_to_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    synced: list[int] = []
    real = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (synced.append(fd), real(fd))[1])
    path = tmp_path / "config.toml"
    path.write_text("", encoding="utf-8")
    if sys.platform != "win32":
        path.chmod(0o644)
    assert save_config(Config(), path)
    assert synced
    if sys.platform != "win32":
        assert path.stat().st_mode & 0o777 == 0o644


def test_save_writes_through_a_symlink(tmp_path: Path) -> None:
    real = tmp_path / "dotfiles" / "config.toml"
    real.parent.mkdir()
    real.write_text("", encoding="utf-8")
    link = tmp_path / "config.toml"
    try:
        link.symlink_to(real)
    except OSError:
        pytest.skip("symlinks are not available here")
    config = Config()
    config.stations.watchlist = ["KDEN"]
    assert save_config(config, link)
    assert link.is_symlink()
    assert tomllib.loads(real.read_text(encoding="utf-8"))["stations"]["watchlist"] == ["KDEN"]


def test_save_sweeps_old_config_temp_files(tmp_path: Path) -> None:
    stale = tmp_path / ".config.zzz.tmp"
    stale.write_text("x", encoding="utf-8")
    long_ago = (datetime.now(UTC) - timedelta(days=1)).timestamp()
    os.utime(stale, (long_ago, long_ago))
    assert save_config(Config(), tmp_path / "config.toml")
    assert not stale.exists()


def test_station_id_is_the_rule_the_watchlist_uses() -> None:
    assert station_id("kden") == "KDEN" and station_id("den") == "KDEN"
    assert station_id("KDEN,KSFO") is None and station_id("") is None
    assert clean_watchlist(["KDEN,KSFO", "den"]) == ["KDEN"]


# --- the command line ----------------------------------------------------------------------------------------------


def test_stdin_bytes_are_decoded_leniently() -> None:
    assert cli._decode_bytes(b"\xef\xbb\xbfMETAR KDEN") == "METAR KDEN"
    assert cli._decode_bytes("METAR KDEN".encode("utf-16")) == "METAR KDEN"
    assert cli._decode_bytes(b"METAR KDEN \xff") == "METAR KDEN �"
    assert cli._decode_bytes("DÁ".encode()) == "DÁ"  # 0xC3 0x81 is valid UTF-8, whatever the code page


def test_collect_texts_reads_the_bytes_under_stdin() -> None:
    stream = io.TextIOWrapper(io.BytesIO(b"\xef\xbb\xbfMETAR KDEN 131453Z 06007KT 10SM CLR 09/08 A3001 \xff\n"))
    assert cli._collect_texts([], stream) == ["METAR KDEN 131453Z 06007KT 10SM CLR 09/08 A3001 �\n"]


def test_units_before_the_subcommand_are_honoured(capsys: pytest.CaptureFixture[str]) -> None:
    report = "METAR KDEN 131453Z 06007KT 10SM CLR 09/08 A3001"
    assert main(["decode", "--plain", "--units", "metric", report]) == 0
    expected = capsys.readouterr().out
    assert main(["--units", "metric", "decode", "--plain", report]) == 0
    assert capsys.readouterr().out == expected
    assert main(["decode", "--plain", "--units", "us", report]) == 0
    assert capsys.readouterr().out != expected


def test_ctrl_c_and_a_closed_pipe_end_quietly(monkeypatch: pytest.MonkeyPatch) -> None:
    def interrupt(args: object) -> int:
        raise KeyboardInterrupt

    def closed(args: object) -> int:
        raise BrokenPipeError

    monkeypatch.setattr(cli, "run_get", interrupt)
    assert main(["get", "KDEN"]) == 130
    redirected: list[tuple[int, int]] = []
    monkeypatch.setattr(os, "dup2", lambda src, dst: redirected.append((src, dst)))  # not the capture's own stdout
    monkeypatch.setattr(cli, "run_get", closed)
    assert main(["get", "KDEN"]) == 1
    assert redirected


# --- wxbrief get ------------------------------------------------------------------------------------------------


def clear_kden(observed: datetime) -> bytes:
    record = json.loads((FIXTURES / "metar_kden_egll.json").read_bytes())[0]
    record.update(
        obsTime=int(observed.timestamp()),
        rawOb=f"METAR KDEN {observed:%d%H%MZ} 00000KT 10SM CLR 10/00 A3001",
        wxString=None,
        vertVis=None,
        cover="CLR",
        clouds=[],
        visib=10,
        fltCat="VFR",
        metarType="METAR",
    )
    return json.dumps([record]).encode()


@pytest.mark.parametrize("bad", ["KDEN,KSFO", "", "TOOLONG", "KD N"])
def test_get_rejects_what_is_not_a_station_id(bad: str, capsys: pytest.CaptureFixture[str]) -> None:
    with respx.mock(assert_all_called=False) as router:
        assert main(["get", bad]) == 2
        assert not router.calls  # nothing was sent to AWC
    assert "not a station id" in capsys.readouterr().err


def test_get_marks_a_stale_report_and_exits_clean(capsys: pytest.CaptureFixture[str]) -> None:
    old = datetime.now(UTC) - timedelta(hours=3)
    with respx.mock() as router:
        router.get(f"{BASE_URL}/metar").mock(return_value=httpx.Response(200, content=clear_kden(old)))
        router.get(f"{BASE_URL}/taf").mock(return_value=httpx.Response(200, content=b"[]"))
        assert main(["get", "KDEN", "--plain"]) == 0
        assert "freshness limit" in capsys.readouterr().out
        assert main(["get", "KDEN", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["KDEN"]["stale"] is True


def test_get_does_not_mark_a_fresh_report(capsys: pytest.CaptureFixture[str]) -> None:
    recent = datetime.now(UTC) - timedelta(minutes=10)
    with respx.mock() as router:
        router.get(f"{BASE_URL}/metar").mock(return_value=httpx.Response(200, content=clear_kden(recent)))
        router.get(f"{BASE_URL}/taf").mock(return_value=httpx.Response(200, content=b"[]"))
        assert main(["get", "KDEN", "--plain"]) == 0
    assert "freshness limit" not in capsys.readouterr().out


def test_get_tells_a_failed_fetch_from_an_absent_report(capsys: pytest.CaptureFixture[str]) -> None:
    with respx.mock() as router:
        router.get(f"{BASE_URL}/metar").mock(return_value=httpx.Response(500))
        router.get(f"{BASE_URL}/taf").mock(return_value=httpx.Response(200, content=b"[]"))
        assert main(["get", "KDEN", "--plain"]) == 1
        out = capsys.readouterr().out
        assert "fetch failed" in out and "no METAR in the last" not in out
        assert main(["get", "KDEN", "--json"]) == 1
    document = json.loads(capsys.readouterr().out)
    assert document["KDEN"]["metar"] is None and document["KDEN"]["errors"] == ["metar"]


def test_get_exits_3_when_one_of_two_stations_returned_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    metar = (FIXTURES / "metar_kden_egll.json").read_bytes()
    with respx.mock() as router:
        router.get(f"{BASE_URL}/metar").mock(return_value=httpx.Response(200, content=metar))
        router.get(f"{BASE_URL}/taf").mock(return_value=httpx.Response(204))
        assert main(["get", "KDEN", "ZZZZ", "--plain"]) == 3
    assert "no report for ZZZZ" in capsys.readouterr().err


def test_get_with_a_bad_ca_bundle_prints_a_message_and_exits_1(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "missing.pem"))
    monkeypatch.setenv("SSL_CERT_DIR", str(tmp_path / "missing-dir"))
    assert main(["get", "KDEN"]) == 1
    err = capsys.readouterr().err
    assert "cannot set up the HTTP client" in err and "Traceback" not in err


# --- the app -------------------------------------------------------------------------------------------------------


async def test_toasts_show_bracketed_text_as_it_is(tmp_path: Path) -> None:
    app = make_app(tmp_path, [])
    app.options.config_warnings = ["[Poll] is not a section; ignoring it", "stations.watchlist: ignoring '[/x]'"]
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        app.notify("[/X] is not a station", markup=True)  # even a caller that asks for markup gets plain text
        await pilot.pause()
        assert "[Poll] is not a section; ignoring it" in notes(app)
        assert all(not n.markup for n in app._notifications)


async def test_a_save_keeps_what_another_instance_and_the_user_wrote(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    first = Config()
    first.stations.watchlist = ["EGLL"]
    path.write_text(config_text(first), encoding="utf-8")
    app = make_app(tmp_path, [], watchlist=["EGLL"])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        edited = "# mine\n[stations]\nwatchlist = ['EGLL', 'KDEN']\n[poll]\nmetar_interval = 900\n"
        path.write_text(edited, encoding="utf-8")  # a second instance and a hand edit, after this one launched
        app.add_station("KSEA")
        await pilot.pause()
    saved = tomllib.loads(path.read_text(encoding="utf-8"))
    assert saved["stations"]["watchlist"] == ["EGLL", "KDEN", "KSEA"]
    assert saved["poll"]["metar_interval"] == 900
    assert (tmp_path / "config.toml.bak").read_text(encoding="utf-8") == edited


async def test_a_hand_edit_is_backed_up_even_when_a_backup_already_exists(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    (tmp_path / "config.toml.bak").write_text("older", encoding="utf-8")
    original = "# my stations\n[stations]\nwatchlist = ['EGLL']\n"
    path.write_text(original, encoding="utf-8")
    app = make_app(tmp_path, [], watchlist=["EGLL"])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        app.add_station("KDEN")
        await pilot.pause()
    assert (tmp_path / "config.toml.bak").read_text(encoding="utf-8") == original


async def test_a_config_broken_since_launch_is_not_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    app = make_app(tmp_path, [])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        path.write_text("this is [not toml", encoding="utf-8")
        app.add_station("KDEN")
        await pilot.pause()
    assert path.read_text(encoding="utf-8") == "this is [not toml"


async def test_no_saved_toast_when_the_list_is_full(tmp_path: Path) -> None:
    full = [f"K{a}{b}{c}" for a in "ABC" for b in "ABCDE" for c in "ABCDE"][:60]
    app = make_app(tmp_path, ["KSEA"], watchlist=full)
    t = app.ctx.translator
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        app.add_station("KSEA")  # listed for this run only; the saved list has no room
        await pilot.pause()
        assert t.t(K.UI_TOAST_WATCHLIST_FULL, limit=60) in notes(app)
        assert not any("now saved" in n for n in notes(app))
    assert not (tmp_path / "config.toml").exists()


async def test_no_saved_toast_when_the_config_is_unreadable(tmp_path: Path) -> None:
    app = make_app(tmp_path, ["KSEA"])
    app.options.config_usable = False
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        app.add_station("KSEA")
        await pilot.pause()
        assert any("already in the list" in n for n in notes(app))
        assert not any("now saved" in n for n in notes(app))


async def test_the_tui_stays_up_when_the_http_client_cannot_be_built(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import wxbrief.app as app_module

    def refuse() -> None:
        raise TransportError("cannot set up the HTTP client: ImportError: socksio")

    monkeypatch.setattr(app_module, "AwcClient", refuse)
    app = make_app(tmp_path, ["KDEN"])
    app.options.poll = True
    async with app.run_test(size=(100, 30)) as pilot:
        await wait_for(pilot, lambda: app.state.errors.get(Product.METAR))
        assert "cannot set up the HTTP client" in app.state.errors[Product.METAR]
        assert app.is_running


async def test_a_station_removed_while_offline_clears_the_offline_mark(tmp_path: Path) -> None:
    app = make_app(tmp_path, ["KDEN"], offline_client())
    async with app.run_test(size=(100, 30)) as pilot:
        await wait_for(pilot, lambda: Product.METAR in app.state.offline)
        app.remove_station("KDEN")
        await pilot.pause()
        assert not app.state.offline and not app.state.errors
