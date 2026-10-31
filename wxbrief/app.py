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
from textual.theme import Theme

from wxbrief.config import TIME_MODES, WATCHLIST_CAP, Config, ViewConfig, default_config_path, save_config
from wxbrief.data.awc import AwcClient, AwcError
from wxbrief.data.cache import DiskCache, default_cache_dir
from wxbrief.data.demo import load_demo
from wxbrief.data.poll import PollScheduler, Product
from wxbrief.data.stations import bundled
from wxbrief.decode.units import UnitsMode
from wxbrief.i18n import LANGUAGES, Translator
from wxbrief.i18n.keys import K
from wxbrief.render.palette import Palette
from wxbrief.state import AppState
from wxbrief.ui.bindings import bind, localize, relabel_tree
from wxbrief.ui.context import ViewContext
from wxbrief.ui.glyphs import GLYPH_SETS, glyphs_for
from wxbrief.ui.screens.briefing import BriefingScreen
from wxbrief.ui.screens.station_detail import StationDetailScreen
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
    demo: bool = False  # --demo: the bundled reports on a fixed clock; no polling, cache or config writes
    now: Callable[[], datetime] = lambda: datetime.now(UTC)


class WxBriefApp(App[None]):
    CSS_PATH = "ui/app.tcss"
    TITLE = "wxbrief"
    HORIZONTAL_BREAKPOINTS = [(0, "-narrow"), (90, "-normal"), (140, "-wide")]
    BINDINGS = [
        bind("q", "quit", K.UI_BINDING_QUIT),
        bind("t", "cycle_theme", K.UI_BINDING_CYCLE_THEME),
        bind("T", "theme_picker", K.UI_BINDING_THEME_PICKER, show=False),
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
        translator = Translator.load(view.lang)
        self._theme_notice = ""
        if view.theme in self.available_themes:
            self.theme = view.theme
        else:
            self.theme = "textual-dark"
            self._theme_notice = translator.t(K.UI_TOAST_UNKNOWN_THEME, theme=repr(view.theme))
        self._settled_theme = self.theme  # the theme in effect that nobody has changed yet
        self._chosen_theme: str | None = None  # set once the user picks one: only then is the theme saved
        self._chosen_view: dict[str, str] = {}  # view settings changed in the settings dialog: saved with the config
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
            translator=translator,
            units=UnitsMode(view.units),
            glyphs=glyphs_for(view.glyph_set),
            time_mode=view.time,
            stations=bundled(),
        )
        self.scheduler: PollScheduler | None = None
        self.briefing = BriefingScreen()
        self._backed_up = False
        self._monotonic: Callable[[], float] = time.monotonic
        self._blurred_at: float | None = None
        self._warned_unusable = False

    def now(self) -> datetime:
        return self.options.now()

    # --- start up --------------------------------------------------------------------------------------------------

    def on_mount(self) -> None:
        t = self.ctx.translator
        localize(self)
        if self.options.demo:
            self.state.load_demo(load_demo())
            self.notify(t.t(K.UI_TOAST_DEMO), timeout=6)
        else:
            self.state.load_cache()
        self.push_screen(self.briefing)
        self.theme_changed_signal.subscribe(self, self._theme_changed)
        if self._theme_notice:
            self.notify(self._theme_notice, severity="warning", title=t.t(K.UI_TOAST_THEME_TITLE), timeout=10)
        for warning in self.options.config_warnings:
            self.notify(warning, severity="warning", title=t.t(K.UI_TOAST_CONFIG_TITLE), timeout=10)
        for notice in self.options.notices:
            self.notify(notice, severity="warning", title=t.t(K.UI_TOAST_STATIONS_TITLE), timeout=10)
        if self.options.poll:
            self.poll_worker()

    # --- themes ----------------------------------------------------------------------------------------------------

    def get_css_variables(self) -> dict[str, str]:
        """Textual's variables plus the resolved ``$wx-*``, ``$fcat-*`` and ``$cs-*`` ones for the current theme."""
        return {**super().get_css_variables(), **Palette.from_theme(self.current_theme).css_variables()}

    def _theme_changed(self, theme: Theme) -> None:
        self.briefing.refresh_view()  # the list, detail and status bar are Rich text drawn from the palette
        for screen in self.screen_stack:
            if isinstance(screen, StationDetailScreen):
                screen.redraw()
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
            fetch = self.ctx.translator.t(
                K.UI_TOAST_FETCH_FAILED, product=product.value.upper(), error=error or type(error).__name__
            )
            self.notify(fetch, severity="warning")
        self.briefing.refresh_view()

    def refresh_now(self) -> None:
        if self.scheduler is None:
            self.notify(self.ctx.translator.t(K.UI_TOAST_POLLING_OFF), severity="warning")
            return
        self.scheduler.poll_now()
        self.notify(self.ctx.translator.t(K.UI_TOAST_REFRESHING))

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
        t = self.ctx.translator
        typed = icao.strip().upper()
        station = self.ctx.station(typed)  # an ICAO id, or a unique IATA or FAA code
        if station is None:
            self.notify(t.t(K.UI_TOAST_UNKNOWN_STATION, code=typed), severity="warning")
            return
        code = station.icao
        if code in self.state.ids:
            key = K.UI_TOAST_ALREADY_LISTED
            if self.options.use_config and not self.state.is_saved(code):
                self.state.add(code, persist=True)  # it was only listed for this run: keep it now
                self._save()
                key = K.UI_TOAST_ALREADY_LISTED_SAVED
            self.notify(t.t(key, code=code))
            self.briefing.select(code)
            return
        if not self.state.add(code, persist=self.options.use_config):
            self.notify(t.t(K.UI_TOAST_WATCHLIST_FULL, limit=WATCHLIST_CAP), severity="warning")
            return
        self._save()
        if self.scheduler is not None:
            self.scheduler.poll_now()
        self.briefing.select(code)
        self.briefing.refresh_view()

    def remove_station(self, icao: str) -> None:
        if self.state.remove(icao):
            self._save()
            self.notify(self.ctx.translator.t(K.UI_TOAST_REMOVED, code=icao))
            self.briefing.refresh_view()

    def _save(self) -> None:
        """Write the watchlist, the theme and the settings dialog's choices back when any of them changed.

        A config file that could not be read is never overwritten. One that loaded with warnings is copied to
        ``<name>.bak`` first, once.
        """
        options = self.options
        t = self.ctx.translator
        watchlist = list(self.state.watchlist)
        chosen = dict(self._chosen_view)
        if self._chosen_theme is not None and not options.theme_from_flag:
            chosen["theme"] = self._chosen_theme
        saved_view = options.config.view
        changed = watchlist != options.config.stations.watchlist or any(
            getattr(saved_view, name) != value for name, value in chosen.items()
        )
        if not options.use_config or not changed:
            return
        path = options.config_path or default_config_path()
        if not options.config_usable:
            if not self._warned_unusable:
                self._warned_unusable = True
                self.notify(t.t(K.UI_TOAST_CONFIG_UNREADABLE, path=path), severity="warning", timeout=10)
            return
        if options.config_warnings and not self._backed_up and path.exists():
            backup = path.with_name(path.name + ".bak")
            try:
                shutil.copy2(path, backup)
            except OSError:
                self.notify(t.t(K.UI_TOAST_BACKUP_FAILED), severity="error")
                return
            self._backed_up = True
            self.notify(t.t(K.UI_TOAST_BACKED_UP, path=backup), timeout=10)
        options.config.stations.watchlist = watchlist
        for name, value in chosen.items():
            setattr(saved_view, name, value)
        if not save_config(options.config, path):
            self.notify(t.t(K.UI_TOAST_SAVE_FAILED, path=path), severity="error")

    # --- settings --------------------------------------------------------------------------------------------------

    def _setting_choices(self, name: str) -> tuple[str, ...]:
        return {
            "lang": LANGUAGES,
            "units": tuple(mode.value for mode in UnitsMode),
            "time": TIME_MODES,
            "glyph_set": GLYPH_SETS,
        }[name]

    def current_setting(self, name: str) -> str:
        return {
            "lang": self.ctx.translator.lang,
            "units": self.ctx.units.value,
            "time": self.ctx.time_mode,
            "glyph_set": self.glyph_set,
        }[name]

    def setting_text(self, name: str) -> str:
        """The current value of a view setting as the settings dialog shows it (a language by its own name)."""
        value = self.current_setting(name)
        if name == "lang":
            return self.ctx.translator.language_name
        group = "glyphs" if name == "glyph_set" else name
        return self.ctx.translator.t(f"ui.option.{group}.{value}")

    def cycle_setting(self, name: str) -> None:
        """Move a view setting to its next value, apply it at once and save it."""
        choices = self._setting_choices(name)
        current = self.current_setting(name)
        index = choices.index(current) if current in choices else -1
        self.apply_setting(name, choices[(index + 1) % len(choices)])

    def apply_setting(self, name: str, value: str) -> None:
        """Change ``lang``, ``units``, ``time`` or ``glyph_set`` for the running app and remember it for the config."""
        match name:
            case "lang":
                self.ctx.translator = Translator.load(value)
                relabel_tree(self, self.ctx.translator)
            case "units":
                self.ctx.units = UnitsMode(value)
            case "time":
                self.ctx.time_mode = value
            case "glyph_set":
                self.glyph_set = value
                self.ctx.glyphs = glyphs_for(value)
            case _:
                raise ValueError(f"not a view setting: {name}")
        setattr(self.options.view, name, value)
        self._chosen_view[name] = value
        self.briefing.refresh_view()
        for screen in self.screen_stack:
            if isinstance(screen, StationDetailScreen):
                screen.redraw()
        self._save()

    def settings_extra_lines(self) -> list[tuple[str, str]]:
        """The settings the dialog only shows: theme, layout, poll times and the file locations."""
        t = self.ctx.translator
        options = self.options
        poll = options.config.poll
        cache = self.state.cache.directory if self.state.cache else t.t(K.UI_SETTINGS_OFF)
        off_config = t.t(K.UI_SETTINGS_OFF_NO_CONFIG)
        config = (options.config_path or default_config_path()) if options.use_config else off_config
        layout = t.t(f"ui.option.layout.{self.briefing.layout_mode}")
        poll_text = t.t(
            K.UI_SETTINGS_POLL_VALUE, metar=poll.metar_interval, taf=poll.taf_interval, away=poll.away_interval
        )
        return [
            (t.t(K.UI_SETTINGS_THEME), self.theme),
            (t.t(K.UI_SETTINGS_LAYOUT), layout),
            (t.t(K.UI_SETTINGS_POLL), poll_text),
            (t.t(K.UI_SETTINGS_CONFIG_FILE), str(config)),
            (t.t(K.UI_SETTINGS_CACHE_FOLDER), str(cache or default_cache_dir())),
        ]
