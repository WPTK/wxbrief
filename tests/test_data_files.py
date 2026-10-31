"""Disk cache, station database and config."""

from __future__ import annotations

from pathlib import Path

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
