"""The Textual application: owns the state, the poll worker and the config, and shows the briefing screen."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from textual import events, work
from textual.app import App
from textual.binding import Binding

from wxbrief.config import Config, ViewConfig, default_config_path, save_config
from wxbrief.data.awc import AwcClient, AwcError
from wxbrief.data.cache import DiskCache, default_cache_dir
from wxbrief.data.poll import PollScheduler, Product
from wxbrief.data.stations import bundled
from wxbrief.decode.units import UnitsMode
from wxbrief.i18n import Translator
from wxbrief.state import AppState
from wxbrief.ui.context import ViewContext
from wxbrief.ui.glyphs import glyphs_for
from wxbrief.ui.screens.briefing import BriefingScreen


@dataclass(slots=True)
class AppOptions:
    """Everything the app needs from the command line and the config file."""

    ids: list[str] = field(default_factory=list)
    config: Config = field(default_factory=Config)  # as loaded: what a save writes back
    view: ViewConfig = field(default_factory=ViewConfig)  # in effect: the config plus command-line overrides
    config_path: Path | None = None
    use_config: bool = True  # False for --no-config: nothing is read from or written to the config file
    config_warnings: list[str] = field(default_factory=list)
    cache_dir: Path | None = None
    use_cache: bool = True
    client: AwcClient | None = None  # tests inject one with a mock transport
    poll: bool = True
    now: Callable[[], datetime] = lambda: datetime.now(UTC)


class WxBriefApp(App[None]):
    CSS_PATH = "ui/app.tcss"
    TITLE = "wxbrief"
    HORIZONTAL_BREAKPOINTS = [(0, "-narrow"), (90, "-normal"), (140, "-wide")]
    BINDINGS = [Binding("q", "quit", "Quit")]

    def __init__(self, options: AppOptions | None = None) -> None:
        super().__init__()
        self.options = options or AppOptions()
        view = self.options.view
        self.theme = "textual-dark"
        self.glyph_set = view.glyph_set
        cache = DiskCache(self.options.cache_dir) if self.options.use_cache else None
        self.state = AppState(
            self.options.config.stations.watchlist if self.options.use_config else (),
            self.options.ids,
            cache,
            self.options.now,
        )
        self.ctx = ViewContext(
            app=self,
            translator=Translator.load(view.lang),
            units=UnitsMode(view.units),
            glyphs=glyphs_for(view.glyph_set),
            time_mode=view.time,
            stations=bundled(),
        )
        self.scheduler: PollScheduler | None = None
        self.briefing = BriefingScreen()
        self._backed_up = False
        self._ticks = 0

    def now(self) -> datetime:
        return self.options.now()

    # --- start up --------------------------------------------------------------------------------------------------

    def on_mount(self) -> None:
        self.state.load_cache()
        self.push_screen(self.briefing)
        for warning in self.options.config_warnings:
            self.notify(warning, severity="warning", title="Config", timeout=10)
        if self.options.view.layout == "grid":
            self.notify("The grid layout is not built yet; showing the list", severity="warning")
        if self.options.poll:
            self.poll_worker()
        self.set_interval(1.0, self._tick)

    def _tick(self) -> None:
        self._ticks += 1
        if self._ticks % 30 == 0:
            self.briefing.refresh_view()  # fresh reports turn stale as time passes
        else:
            self.briefing.refresh_status()

    # --- polling ---------------------------------------------------------------------------------------------------

    @work(exclusive=True, group="poll")
    async def poll_worker(self) -> None:
        poll = self.options.config.poll
        client = self.options.client or AwcClient()
        self.scheduler = PollScheduler(
            client,
            lambda: self.state.ids,
            self._on_result,
            self._on_error,
            metar_interval=poll.metar_interval,
            taf_interval=poll.taf_interval,
            away_interval=poll.away_interval,
        )
        try:
            await self.scheduler.run()
        finally:
            await client.aclose()

    def _on_result(self, product: Product, rows: list[object]) -> None:
        self.state.apply(product, rows)
        self.briefing.refresh_view()

    def _on_error(self, product: Product, error: AwcError) -> None:
        first = product not in self.state.errors
        self.state.record_error(product, f"{product.value}: {error}" if str(error) else type(error).__name__)
        if first:
            self.notify(f"Could not fetch {product.value.upper()}: {error or type(error).__name__}", severity="warning")
        self.briefing.refresh_view()

    def refresh_now(self) -> None:
        if self.scheduler is None:
            self.notify("Polling is off", severity="warning")
            return
        self.scheduler.poll_now()
        self.notify("Refreshing")

    def on_app_blur(self, event: events.AppBlur) -> None:
        if self.scheduler is not None:
            self.scheduler.away = True

    def on_app_focus(self, event: events.AppFocus) -> None:
        scheduler = self.scheduler
        if scheduler is None or not scheduler.away:
            return
        scheduler.away = False
        scheduler.poll_now()  # catch up after being away

    # --- the list --------------------------------------------------------------------------------------------------

    def add_station(self, icao: str) -> None:
        station = self.ctx.station(icao) if len(icao.strip()) == 3 else None
        code = (station.icao if station else icao).strip().upper()
        if code in self.state.watchlist or (not self.options.use_config and code in self.state.ids):
            self.notify(f"{code} is already listed")
            self.briefing.select(code)
            return
        if not self.state.add(code, persist=self.options.use_config):
            self.notify("The watchlist is full (60 stations)", severity="warning")
            return
        self._save()
        if self.scheduler is not None:
            self.scheduler.poll_now()
        self.briefing.select(code)
        self.briefing.refresh_view()

    def remove_station(self, icao: str) -> None:
        if self.state.remove(icao):
            self._save()
            self.notify(f"Removed {icao}")
            self.briefing.refresh_view()

    def _save(self) -> None:
        """Write the watchlist back. A config that loaded with warnings is copied to ``.bak`` first, once."""
        options = self.options
        if not options.use_config:
            return
        path = options.config_path or default_config_path()
        if options.config_warnings and not self._backed_up and path.exists():
            try:
                shutil.copy2(path, path.with_suffix(".toml.bak"))
            except OSError:
                self.notify("Could not back up the config; not saving it", severity="error")
                return
            self._backed_up = True
        options.config.stations.watchlist = list(self.state.watchlist)
        if not save_config(options.config, path):
            self.notify(f"Could not save {path}", severity="error")

    def settings_lines(self) -> list[tuple[str, str]]:
        view = self.options.view
        options = self.options
        cache = self.state.cache.directory if self.state.cache else "off"
        config = (options.config_path or default_config_path()) if options.use_config else "off (--no-config)"
        return [
            ("Theme", self.theme),
            ("Glyphs", view.glyph_set),
            ("Layout", view.layout),
            ("Units", view.units),
            ("Time", view.time),
            ("Language", self.ctx.translator.lang),
            ("Poll (s)", f"METAR {options.config.poll.metar_interval}, TAF {options.config.poll.taf_interval}, "
             f"away {options.config.poll.away_interval}"),
            ("Config file", str(config)),
            ("Cache folder", str(cache or default_cache_dir())),
        ]
