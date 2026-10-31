"""User configuration (``config.toml``). Loading never raises: bad input falls back to defaults with a warning."""

from __future__ import annotations

import os
import re
import tempfile
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import platformdirs
import tomli_w

WATCHLIST_CAP = 60
UNITS = ("us", "metric", "mixed")
TIME_MODES = ("station", "local", "zulu")
LAYOUTS = ("list", "grid")
_STATION_ID = re.compile(r"^[A-Z0-9]{3,4}$")


@dataclass(slots=True)
class StationsConfig:
    watchlist: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PollConfig:
    metar_interval: int = 600
    taf_interval: int = 1800
    away_interval: int = 1800


@dataclass(slots=True)
class ViewConfig:
    theme: str = "textual-dark"
    glyph_set: str = "nerd"
    layout: str = "list"
    units: str = "mixed"
    time: str = "station"
    lang: str = "en"
    show_computed_color: bool = True


@dataclass(slots=True)
class DecodeConfig:
    show_awc_crosscheck: bool = True


@dataclass(slots=True)
class Config:
    stations: StationsConfig = field(default_factory=StationsConfig)
    poll: PollConfig = field(default_factory=PollConfig)
    view: ViewConfig = field(default_factory=ViewConfig)
    decode: DecodeConfig = field(default_factory=DecodeConfig)


@dataclass(slots=True)
class LoadedConfig:
    config: Config
    warnings: list[str] = field(default_factory=list)


def default_config_path() -> Path:
    return Path(platformdirs.user_config_dir("wxbrief")) / "config.toml"


def _section(data: dict[str, Any], name: str, warnings: list[str]) -> dict[str, Any]:
    value = data.get(name, {})
    if isinstance(value, dict):
        return value
    warnings.append(f"[{name}] must be a table; using defaults")
    return {}


def _choice(
    table: dict[str, Any], key: str, allowed: tuple[str, ...], default: str, where: str, warns: list[str]
) -> str:
    value = table.get(key, default)
    if isinstance(value, str) and value.lower() in allowed:
        return value.lower()
    if key in table:
        warns.append(f"{where}.{key} must be one of {', '.join(allowed)}; using {default!r}")
    return default


def _text(table: dict[str, Any], key: str, default: str, where: str, warns: list[str]) -> str:
    value = table.get(key, default)
    if isinstance(value, str) and value.strip():
        return value.strip()
    if key in table:
        warns.append(f"{where}.{key} must be a non-empty string; using {default!r}")
    return default


def _flag(table: dict[str, Any], key: str, default: bool, where: str, warns: list[str]) -> bool:
    value = table.get(key, default)
    if isinstance(value, bool):
        return value
    if key in table:
        warns.append(f"{where}.{key} must be true or false; using {default}")
    return default


def _seconds(table: dict[str, Any], key: str, default: int, where: str, warns: list[str]) -> int:
    value = table.get(key, default)
    if isinstance(value, int) and not isinstance(value, bool) and 60 <= value <= 86400:
        return value
    if key in table:
        warns.append(f"{where}.{key} must be a whole number of seconds from 60 to 86400; using {default}")
    return default


def clean_watchlist(values: object, warnings: list[str] | None = None) -> list[str]:
    """Upper-cased, de-duplicated station ids, dropping anything that is not a plausible id, capped at 60."""
    warns = warnings if warnings is not None else []
    if not isinstance(values, list):
        warns.append("stations.watchlist must be a list; using an empty list")
        return []
    result: list[str] = []
    for value in values:
        code = value.strip().upper() if isinstance(value, str) else ""
        if not _STATION_ID.match(code):
            warns.append(f"stations.watchlist: ignoring {value!r}")
        elif code not in result:
            result.append(code)
    if len(result) > WATCHLIST_CAP:
        warns.append(f"stations.watchlist: keeping the first {WATCHLIST_CAP} of {len(result)}")
        result = result[:WATCHLIST_CAP]
    return result


def parse_config(data: dict[str, Any]) -> LoadedConfig:
    """Build a ``Config`` from parsed TOML, replacing every bad value with its default."""
    warns: list[str] = []
    config = Config()

    stations = _section(data, "stations", warns)
    if "watchlist" in stations:
        config.stations.watchlist = clean_watchlist(stations["watchlist"], warns)

    poll, view, decode = (_section(data, name, warns) for name in ("poll", "view", "decode"))
    defaults = PollConfig()
    config.poll = PollConfig(
        metar_interval=_seconds(poll, "metar_interval", defaults.metar_interval, "poll", warns),
        taf_interval=_seconds(poll, "taf_interval", defaults.taf_interval, "poll", warns),
        away_interval=_seconds(poll, "away_interval", defaults.away_interval, "poll", warns),
    )
    vd = ViewConfig()
    config.view = ViewConfig(
        theme=_text(view, "theme", vd.theme, "view", warns),
        glyph_set=_text(view, "glyph_set", vd.glyph_set, "view", warns),
        layout=_choice(view, "layout", LAYOUTS, vd.layout, "view", warns),
        units=_choice(view, "units", UNITS, vd.units, "view", warns),
        time=_choice(view, "time", TIME_MODES, vd.time, "view", warns),
        lang=_text(view, "lang", vd.lang, "view", warns),
        show_computed_color=_flag(view, "show_computed_color", vd.show_computed_color, "view", warns),
    )
    config.decode = DecodeConfig(
        show_awc_crosscheck=_flag(decode, "show_awc_crosscheck", True, "decode", warns),
    )
    return LoadedConfig(config, warns)


def load_config(path: Path | None = None) -> LoadedConfig:
    """Read the config file. A missing file is the defaults with no warning; an unreadable one is defaults plus one."""
    target = path or default_config_path()
    try:
        text = target.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return LoadedConfig(Config())
    except (OSError, UnicodeDecodeError) as exc:
        return LoadedConfig(Config(), [f"cannot read {target}: {exc}"])
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return LoadedConfig(Config(), [f"{target} is not valid TOML ({exc}); using defaults"])
    return parse_config(data)


def save_config(config: Config, path: Path | None = None) -> bool:
    """Write the config atomically; ``False`` when the disk refuses."""
    target = path or default_config_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=".config.", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as handle:
                tomli_w.dump(asdict(config), handle)
            os.replace(tmp_name, target)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise
    except (OSError, TypeError, ValueError):
        return False
    return True
