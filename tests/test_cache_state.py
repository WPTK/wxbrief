"""The shared disk cache and AWC's TAF ``remarks`` field, through ``AppState``."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from corpus import awc_rows, awc_taf_rows

from wxbrief.data.cache import DiskCache
from wxbrief.data.models import parse_metars, parse_taf, parse_tafs
from wxbrief.data.poll import Product
from wxbrief.decode.model import Flag, Modifier
from wxbrief.decode.units import UnitsMode
from wxbrief.i18n import Translator
from wxbrief.render.discord import discord_block
from wxbrief.state import CACHE_MAX_AGE, AppState

NOW = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)


def _metars(*icaos: str) -> list[Any]:
    rows = [m for m in parse_metars(awc_rows()) if m.icao in icaos]
    assert {m.icao for m in rows} == set(icaos)
    return rows


def _cached_icaos(cache: DiskCache, key: str) -> set[str]:
    found = cache.read(key)
    assert found is not None
    return {row["icaoId"] for row in found[1]}


def _taf_row(icao: str = "KATL") -> dict[str, Any]:
    return next(r for r in awc_taf_rows() if r["icaoId"] == icao)


# --- AMD / COR / CNL in the row's remarks field -----------------------------------------------------------------------


def test_an_amended_awc_row_is_amended_though_rawtaf_has_no_amd() -> None:
    row = _taf_row("KATL")
    assert row["remarks"].strip() == "AMD" and "AMD" not in row["rawTAF"].split()[:3]
    state = AppState(["KATL"], now=lambda: NOW)
    state.apply(Product.TAF, parse_tafs([row]))
    taf = state.stations["KATL"].taf
    assert taf is not None
    assert taf.modifiers == (Modifier.AMD,)
    assert Flag.AMENDED in taf.flags
    assert "— AMD" in discord_block(taf, Translator.load("en"), UnitsMode.US)


def test_cor_and_cnl_in_remarks_are_read_and_plain_rows_are_unchanged() -> None:
    row = _taf_row("KATL")
    cor, both, text = (parse_taf({**row, "remarks": r}) for r in (" COR", "CNL AMD", "NO AMDS AFT 3100"))
    assert cor is not None and cor.modifiers == (Modifier.COR,)
    assert both is not None and both.modifiers == (Modifier.CNL, Modifier.AMD)
    assert text is not None and text.modifiers == ()
    state = AppState(["KATL"], now=lambda: NOW)
    state.apply(Product.TAF, parse_tafs([{**row, "remarks": None}]))
    taf = state.stations["KATL"].taf
    assert taf is not None and taf.modifiers == ()


def test_a_report_whose_text_already_says_amd_is_not_doubled() -> None:
    row = {**_taf_row("KATL"), "rawTAF": "TAF AMD KATL 310935Z 3110/0112 08009KT P6SM SCT150", "remarks": " AMD"}
    state = AppState(["KATL"], now=lambda: NOW)
    state.apply(Product.TAF, parse_tafs([row]))
    taf = state.stations["KATL"].taf
    assert taf is not None and taf.modifiers == (Modifier.AMD,)


# --- the cache file is shared by every run ----------------------------------------------------------------------------


def test_a_run_with_another_station_list_keeps_the_other_stations_rows(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path)
    wide = AppState(["KDEN", "KSEA", "KATL"], cache=cache, now=lambda: NOW)
    wide.apply(Product.METAR, _metars("KDEN", "KSEA", "KATL"))
    wide.apply(Product.TAF, parse_tafs([r for r in awc_taf_rows() if r["icaoId"] in ("KATL", "KDEN")]))
    narrow = AppState(["KSEA"], cache=cache, now=lambda: NOW + timedelta(minutes=5))
    narrow.apply(Product.METAR, _metars("KSEA"))
    narrow.apply(Product.TAF, [])
    assert _cached_icaos(cache, "metars") == {"KDEN", "KSEA", "KATL"}
    assert _cached_icaos(cache, "tafs") == {"KATL", "KDEN"}


def test_a_loaded_run_writes_back_the_stations_it_was_not_asked_about(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path)
    first = AppState(["KDEN", "KSEA"], cache=cache, now=lambda: NOW)
    first.apply(Product.METAR, _metars("KDEN", "KSEA"))
    second = AppState(["KSEA"], cache=cache, now=lambda: NOW + timedelta(minutes=5))
    second.load_cache()
    second.apply(Product.METAR, _metars("KSEA"))
    assert _cached_icaos(cache, "metars") == {"KDEN", "KSEA"}
    third = AppState(["KDEN", "KSEA"], cache=cache, now=lambda: NOW + timedelta(minutes=9))
    third.load_cache()
    assert third.stations["KDEN"].awc_metar is not None


def test_other_stations_rows_are_pruned_by_age_and_expiry_not_by_the_run_list(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path)
    first = AppState(["KDEN", "KSEA", "KATL"], cache=cache, now=lambda: NOW)
    first.apply(Product.METAR, _metars("KDEN", "KSEA", "KATL"))
    first.apply(Product.TAF, parse_tafs([_taf_row("KATL")]))
    later = NOW + CACHE_MAX_AGE + timedelta(hours=1)  # the KATL forecast has also lapsed by now
    run = AppState(["KSEA"], cache=cache, now=lambda: later)
    run.apply(Product.METAR, _metars("KSEA"))
    run.apply(Product.TAF, [])
    assert _cached_icaos(cache, "metars") == {"KSEA"}
    assert _cached_icaos(cache, "tafs") == set()


# --- the temp-file sweep only touches this cache's own files ----------------------------------------------------------


def test_clean_leaves_other_programs_temp_files_alone(tmp_path: Path) -> None:
    old = time.time() - 7200
    names = [".metars.abc.tmp", ".tafs.abc.tmp", ".upload.tmp", ".other.xyz.tmp"]
    for name in names:
        (tmp_path / name).write_text("x", encoding="utf-8")
        os.utime(tmp_path / name, (old, old))
    DiskCache(tmp_path).clean(["metars", "tafs"])
    assert sorted(p.name for p in tmp_path.iterdir()) == [".other.xyz.tmp", ".upload.tmp"]


def test_a_long_running_run_does_not_overwrite_a_newer_row_another_run_wrote(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path)
    early = AppState(["KDEN", "KSEA"], cache=cache, now=lambda: NOW)
    early.apply(Product.METAR, _metars("KDEN", "KSEA"))
    clock = [NOW + timedelta(minutes=1)]
    long_running = AppState(["KDEN"], cache=cache, now=lambda: clock[0])
    long_running.load_cache()  # holds KSEA from 12:00
    other = AppState(["KSEA"], cache=cache, now=lambda: NOW + timedelta(hours=4))
    other.apply(Product.METAR, _metars("KSEA"))
    clock[0] = NOW + timedelta(hours=4, minutes=10)
    long_running.apply(Product.METAR, _metars("KDEN"))
    found = cache.read("metars")
    assert found is not None
    stamps = {row["icaoId"]: row["wxbriefFetched"] for row in found[1]}
    assert stamps["KSEA"] == (NOW + timedelta(hours=4)).isoformat()
