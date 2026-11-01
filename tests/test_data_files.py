"""Disk cache, station database and config."""

from __future__ import annotations

import json
from pathlib import Path
from zoneinfo import ZoneInfo

from wxbrief.config import WATCHLIST_CAP, Config, load_config, parse_config, save_config
from wxbrief.data.cache import DiskCache
from wxbrief.data.stations import bundled


def test_cache_round_trip_and_atomic_write(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path / "nested")
    assert cache.read("metars") is None
    assert cache.write("metars", [{"icaoId": "KDEN"}])
    saved_at, payload = cache.read("metars") or (None, None)
    assert payload == [{"icaoId": "KDEN"}] and saved_at is not None
    assert [p.name for p in (tmp_path / "nested").iterdir()] == ["metars.json"]


def test_cache_survives_damage_and_unwritable_dirs(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path)
    (tmp_path / "metars.json").write_text("{not json", encoding="utf-8")
    assert cache.read("metars") is None
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    assert DiskCache(blocker / "sub").write("k", 1) is False
    assert not cache.write("k", object())
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []


def test_station_search_finds_heathrow() -> None:
    db = bundled()
    assert len(db) > 5000
    assert db.search("heathrow")[0].icao == "EGLL"
    assert db.search("LHR")[0].icao == "EGLL"
    assert db.search("DEN")[0].icao == "KDEN"  # an exact code beats every name that merely starts with it
    egll = db.get("EGLL")
    assert egll is not None and egll.tz == "Europe/London"
    kden = db.get("DEN")
    assert kden is not None and kden.icao == "KDEN" and kden.tz == "America/Denver"
    assert db.search("   ") == []
    assert db.search("zzzzzzzzzz") == []


def test_station_search_ignores_case() -> None:
    assert any(s.icao == "SBGR" for s in bundled().search("SAO paulo"))


def test_config_missing_file_is_defaults_without_warnings(tmp_path: Path) -> None:
    loaded = load_config(tmp_path / "none.toml")
    assert loaded.warnings == [] and loaded.config == Config()


def test_config_bad_toml_never_raises(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[view\ntheme = ", encoding="utf-8")
    loaded = load_config(path)
    assert loaded.config == Config() and len(loaded.warnings) == 1
    path.write_bytes(b"\xff\xfe\x00")
    assert load_config(path).config == Config()
    path.write_bytes(b"\xff\xfe\x00")
    unreadable = load_config(path)
    assert unreadable.config == Config() and not unreadable.usable and len(unreadable.warnings) == 1
    assert load_config(tmp_path / "none.toml").usable


def test_config_bad_values_fall_back_one_by_one() -> None:
    loaded = parse_config(
        {
            "stations": {"watchlist": ["kden", "KDEN", "toolongid", 5, "EGLL"]},
            "poll": {"metar_interval": 5, "taf_interval": "x", "away_interval": 900},
            "view": {"units": "furlongs", "time": "zulu", "show_computed_color": "yes", "theme": 3},
            "decode": [],
        }
    )
    config = loaded.config
    assert config.stations.watchlist == ["KDEN", "EGLL"]
    assert (config.poll.metar_interval, config.poll.taf_interval, config.poll.away_interval) == (600, 1800, 900)
    assert config.view.units == "mixed" and config.view.time == "zulu"
    assert config.view.show_computed_color is True and config.view.theme == "textual-dark"
    assert config.decode.show_awc_crosscheck is True
    assert len(loaded.warnings) >= 6


def test_watchlist_is_capped() -> None:
    ids = [f"K{n:03d}" for n in range(80)]
    loaded = parse_config({"stations": {"watchlist": ids}})
    assert len(loaded.config.stations.watchlist) == WATCHLIST_CAP


def test_config_save_and_reload(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "config.toml"
    config = Config()
    config.stations.watchlist = ["KDEN", "EGLL"]
    config.view.theme = "paper-chart"
    assert save_config(config, path)
    loaded = load_config(path)
    assert loaded.warnings == [] and loaded.config == config


def test_config_with_a_bom_is_read(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_bytes(b'\xef\xbb\xbf[view]\ntheme = "paper-chart"\n')
    loaded = load_config(path)
    assert loaded.warnings == [] and loaded.config.view.theme == "paper-chart"


def test_cache_naive_saved_at_is_damaged(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path)
    cache.write("k", [1])
    path = tmp_path / "k.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["saved_at"] = "2026-10-31T11:40:00"
    path.write_text(json.dumps(document), encoding="utf-8")
    assert cache.read("k") is None


def test_every_bundled_time_zone_is_a_zoneinfo_key() -> None:
    zones = {s.tz for s in bundled()._stations if s.tz}
    assert len(zones) > 100
    for zone in zones:
        ZoneInfo(zone)


def test_station_get_prefers_iata_over_faa_and_refuses_shared_codes() -> None:
    db = bundled()
    manchester = db.get("MAN")
    assert manchester is not None and manchester.icao == "EGCC"
    shared = ("GWD", "ISU", "CEM", "PTZ", "GYA", "VTZ", "SRG", "TRK")
    assert all(db.get(code) is None for code in shared)
    iata: dict[str, int] = {}
    for station in db._stations:
        if station.iata:
            iata[station.iata] = iata.get(station.iata, 0) + 1
    assert sorted(code for code, n in iata.items() if n > 1) == sorted(shared)


def test_cache_nested_past_the_recursion_limit_reads_as_damaged(tmp_path: Path) -> None:
    (tmp_path / "metars.json").write_text("[" * 100000 + "]" * 100000, encoding="utf-8")
    assert DiskCache(tmp_path).read("metars") is None


def test_unknown_keys_and_sections_are_warned_about() -> None:
    loaded = parse_config({"view": {"theem": "nord"}, "poll": {"metar_intervall": 300}, "alerts": {"webhook": "x"}})
    assert sorted(loaded.warnings) == [
        "[alerts] is not a section; ignoring it",
        "poll.metar_intervall is not a setting; ignoring it",
        "view.theem is not a setting; ignoring it",
    ]
    assert parse_config({"view": {"theme": "nord"}}).warnings == []


def test_watchlist_iata_codes_resolve_to_icao() -> None:
    assert parse_config({"stations": {"watchlist": ["DEN", "kden", "EGLL"]}}).config.stations.watchlist == [
        "KDEN",
        "EGLL",
    ]


def test_a_failed_cache_write_is_reported_through_the_error_path(tmp_path: Path) -> None:
    from wxbrief.data.poll import Product
    from wxbrief.state import AppState

    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    state = AppState(["KDEN"], cache=DiskCache(blocker / "sub"))
    state.apply(Product.METAR, [])
    assert "could not write the cache" in state.errors[Product.METAR]
    assert Product.METAR not in state.offline


def test_a_failed_config_save_returns_false_and_leaves_no_temp_file(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    assert save_config(Config(), blocker / "sub" / "config.toml") is False
    assert [p.name for p in tmp_path.iterdir()] == ["file"]
    path = tmp_path / "config.toml"
    path.mkdir()  # the target is a directory: the temp file is written, the replace fails and the temp file goes
    assert save_config(Config(), path) is False
    assert sorted(p.name for p in tmp_path.iterdir()) == ["config.toml", "file"]


def test_a_good_fetch_clears_the_error_and_offline_mark_of_every_product() -> None:
    from wxbrief.data.poll import Product
    from wxbrief.state import AppState

    state = AppState(["KDEN"])
    for _ in range(2):
        state.record_error(Product.METAR, "x", offline=True)
        state.record_error(Product.TAF, "y", offline=True)
    assert state.offline == {Product.METAR, Product.TAF}
    state.apply(Product.METAR, [])  # offline is the network's: one answer of either product ends it for both
    assert state.errors == {} and state.offline == set() and state.transport_failures == {}


def test_numeric_admin_codes_are_not_shown_as_a_region() -> None:
    db = bundled()
    haneda, denver = db.get("RJTT"), db.get("KDEN")
    assert haneda is not None and haneda.state is None  # AWC gives Japan "13"
    assert denver is not None and denver.state == "CO"
