"""The Textual application: owns the state, the poll worker and the config, and shows the briefing screen."""

from __future__ import annotations

import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from textual import events, work
from textual.app import App
from textual.binding import Binding
from textual.theme import Theme

from wxbrief.config import Config, ViewConfig, default_config_path, save_config
from wxbrief.data.awc import AwcClient, AwcError
from wxbrief.data.cache import DiskCache, default_cache_dir
from wxbrief.data.poll import PollScheduler, Product
from wxbrief.data.stations import bundled
from wxbrief.decode.units import UnitsMode
from wxbrief.i18n import Translator
from wxbrief.render.palette import Palette
from wxbrief.state import AppState
from wxbrief.ui.context import ViewContext
from wxbrief.ui.glyphs import glyphs_for
from wxbrief.ui.screens.briefing import BriefingScreen
from wxbrief.ui.screens.theme_picker import ThemePickerScreen
from wxbrief.ui.themes import AVIATION_THEMES, THEME_CYCLE


@dataclass(slots=True)
class AppOptions:
    """Everything the app needs from the command line and the config file."""

    ids: list[str] = field(default_factory=list)
    config: Config = field(default_factory=Config)  # as loaded: what a save writes back
    view: ViewConfig = field(default_factory=ViewConfig)  # in effect: the config plus command-line overrides
    config_path: Path | None = None
    use_config: bool = True  # False for --no-config: nothing is read from or written to the config file
    theme_from_flag: bool = False  # --theme was given: the theme is for this run and is never saved
    config_warnings: list[str] = field(default_factory=list)
    config_usable: bool = True  # False when the config file could not be read at all: it is never overwritten
    notices: list[str] = field(default_factory=list)  # problems with command-line station ids
    cache_dir: Path | None = None
    use_cache: bool = True
    client: AwcClient | None = None  # tests inject one with a mock transport
    poll: bool = True
    now: Callable[[], datetime] = lambda: datetime.now(UTC)


class WxBriefApp(App[None]):
    CSS_PATH = "ui/app.tcss"
    TITLE = "wxbrief"
    HORIZONTAL_BREAKPOINTS = [(0, "-narrow"), (90, "-normal"), (140, "-wide")]
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("t", "cycle_theme", "Theme"),
        Binding("T", "theme_picker", "Themes", show=False),
    ]

    def __init__(self, options: AppOptions | None = None) -> None:
        super().__init__()
        self.options = options or AppOptions()
        view = self.options.view
        for theme in AVIATION_THEMES:
            self.register_theme(theme)
        for name in [name for name, theme in self.available_themes.items() if theme.ansi]:
            self.unregister_theme(name)  # the terminal's own colours have no RGB palette for the highlight colours
        self._previewing = False  # the theme picker is open: a highlighted theme is a preview, not a choice
        self._theme_notice = ""
        if view.theme in self.available_themes:
            self.theme = view.theme
        else:
            self.theme = "textual-dark"
            self._theme_notice = f"Unknown theme {view.theme!r}; using textual-dark"
        self._settled_theme = self.theme  # the theme in effect that nobody has changed yet
        self._chosen_theme: str | None = None  # set once the user picks one: only then is the theme saved
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
        self._monotonic: Callable[[], float] = time.monotonic
        self._blurred_at: float | None = None
        self._warned_unusable = False

    def now(self) -> datetime:
        return self.options.now()

    # --- start up --------------------------------------------------------------------------------------------------

    def on_mount(self) -> None:
        self.state.load_cache()
        self.push_screen(self.briefing)
        self.theme_changed_signal.subscribe(self, self._theme_changed)
        if self._theme_notice:
            self.notify(self._theme_notice, severity="warning", title="Theme", timeout=10)
        for warning in self.options.config_warnings:
            self.notify(warning, severity="warning", title="Config", timeout=10)
        for notice in self.options.notices:
            self.notify(notice, severity="warning", title="Stations", timeout=10)
        if self.options.view.layout == "grid":
            self.notify("The grid layout is not built yet; showing the list", severity="warning")
        if self.options.poll:
            self.poll_worker()
        self.set_interval(1.0, self._tick)

    # --- themes ----------------------------------------------------------------------------------------------------

    def get_css_variables(self) -> dict[str, str]:
        """Textual's variables plus the resolved ``$wx-*``, ``$fcat-*`` and ``$cs-*`` ones for the current theme."""
        return {**super().get_css_variables(), **Palette.from_theme(self.current_theme).css_variables()}

    def _theme_changed(self, theme: Theme) -> None:
        self.briefing.refresh_view()  # the list, detail and status bar are Rich text drawn from the palette
        self._settle()

    def _settle(self) -> None:
        """Remember the current theme as the user's choice (and save it) unless it is only a preview.

        The signal is published after a delay, so this reads ``self.theme`` rather than the signal's theme: a late
        message about a theme the picker already moved past must not be saved.
        """
        if self._previewing or self.theme == self._settled_theme:
            return
        self._settled_theme = self._chosen_theme = self.theme
        self._save()

    def action_cycle_theme(self) -> None:
        if self._previewing:
            return
        names = [name for name in THEME_CYCLE if name in self.available_themes]
        index = names.index(self.theme) + 1 if self.theme in names else 0
        self.theme = names[index % len(names)]

    def action_theme_picker(self) -> None:
        if self._previewing:
            return
        self._previewing = True
        names = [name for name in THEME_CYCLE if name in self.available_themes]
        if self.theme not in names:
            names.append(self.theme)

        def closed(chosen: str | None) -> None:
            self._previewing = False
            self._settle()  # a kept theme is saved; a cancelled one is back to the settled theme and saves nothing

        self.push_screen(ThemePickerScreen(names, self.theme), closed)

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
            self._blurred_at = self._monotonic()

    def on_app_focus(self, event: events.AppFocus) -> None:
        scheduler = self.scheduler
        if scheduler is None or not scheduler.away:
            return
        scheduler.away = False
        away_for = self._monotonic() - self._blurred_at if self._blurred_at is not None else 0.0
        self._blurred_at = None
        if away_for >= self.options.config.poll.metar_interval:
            scheduler.poll_now()  # data is a full poll interval old: catch up (a rate-limit hold still applies)

    # --- the list --------------------------------------------------------------------------------------------------

    def add_station(self, icao: str) -> None:
        typed = icao.strip().upper()
        station = self.ctx.station(typed)  # an ICAO id, or a unique IATA or FAA code
        if station is None:
            self.notify(f"Unknown station {typed}", severity="warning")
            return
        code = station.icao
        if code in self.state.ids:
            note = f"{code} is already in the list"
            if self.options.use_config and not self.state.is_saved(code):
                self.state.add(code, persist=True)  # it was only listed for this run: keep it now
                self._save()
                note += " (now saved)"
            self.notify(note)
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
        """Write the watchlist and the theme back when either changed.

        A config file that could not be read is never overwritten. One that loaded with warnings is copied to
        ``<name>.bak`` first, once.
        """
        options = self.options
        watchlist = list(self.state.watchlist)
        theme = None if options.theme_from_flag else self._chosen_theme
        changed = watchlist != options.config.stations.watchlist or (
            theme is not None and theme != options.config.view.theme
        )
        if not options.use_config or not changed:
            return
        path = options.config_path or default_config_path()
        if not options.config_usable:
            if not self._warned_unusable:
                self._warned_unusable = True
                self.notify(
                    f"{path} could not be read, so it was left alone. Changes last for this run only.",
                    severity="warning",
                    timeout=10,
                )
            return
        if options.config_warnings and not self._backed_up and path.exists():
            backup = path.with_name(path.name + ".bak")
            try:
                shutil.copy2(path, backup)
            except OSError:
                self.notify("Could not back up the config; not saving it", severity="error")
                return
            self._backed_up = True
            self.notify(f"The config had problems; the original is kept as {backup}", timeout=10)
        options.config.stations.watchlist = watchlist
        if theme is not None:
            options.config.view.theme = theme
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
