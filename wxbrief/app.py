"""The Textual application: owns the state, the poll worker and the config, and shows the briefing screen."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from textual import events, work
from textual.app import App
from textual.geometry import Size
from textual.notifications import SeverityLevel
from textual.theme import Theme

from wxbrief.config import (
    TIME_MODES,
    WATCHLIST_CAP,
    Config,
    LoadedConfig,
    ViewConfig,
    config_text,
    default_config_path,
    load_config,
    merge_session,
    save_config,
)
from wxbrief.data.awc import AwcClient, AwcError, TransportError
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
from wxbrief.ui.screens.paste import PasteDecodeScreen
from wxbrief.ui.screens.station_detail import StationDetailScreen
from wxbrief.ui.screens.theme_picker import ThemePickerScreen
from wxbrief.ui.screens.too_small import MIN_SIZE, TooSmallScreen
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
    flag_view: frozenset[str] = frozenset()  # view settings given as flags: for this run only, never saved
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
    VERTICAL_BREAKPOINTS = [(0, "-short"), (24, "-tall"), (40, "-roomy")]
    BINDINGS = [
        bind("q", "quit", K.UI_BINDING_QUIT),
        bind("t", "cycle_theme", K.UI_BINDING_CYCLE_THEME),
        bind("T", "theme_picker", K.UI_BINDING_THEME_PICKER, show=False),
        bind("g", "cycle_glyphs", K.UI_BINDING_CYCLE_GLYPHS, show=False),
        bind("u", "cycle_units", K.UI_BINDING_CYCLE_UNITS, show=False),
        bind("z", "cycle_time", K.UI_BINDING_CYCLE_TIME, show=False),
        # Textual adds this binding with an English label only when the app has none, and the footer reads it by key.
        bind(App.COMMAND_PALETTE_BINDING, "command_palette", K.UI_BINDING_PALETTE, show=False, priority=True),
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
            crosscheck=self.options.config.decode.show_awc_crosscheck,
        )
        self.scheduler: PollScheduler | None = None
        self.briefing = BriefingScreen()
        self._saved_watchlist = list(self.options.config.stations.watchlist)  # the file's list as last read or written
        self._warned_unusable = False

    def now(self) -> datetime:
        return self.options.now()

    def notify(
        self,
        message: str,
        *,
        title: str = "",
        severity: SeverityLevel = "information",
        timeout: float | None = None,
        **_markup: bool,
    ) -> None:
        """Show a toast with the text exactly as given (a ``markup`` argument is ignored): station ids, paths and
        errors may hold ``[...]``, which Textual would read as markup."""
        super().notify(message, title=title, severity=severity, timeout=timeout, markup=False)

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
        self._check_size(self.size)

    def on_resize(self, event: events.Resize) -> None:
        self._check_size(event.size)

    def _check_size(self, size: Size) -> None:
        """Cover the app with the too-small notice while the terminal cannot hold it; take it away when it can."""
        small = size.width < MIN_SIZE.width or size.height < MIN_SIZE.height
        notices = [screen for screen in self.screen_stack if isinstance(screen, TooSmallScreen)]
        if not small and notices:
            while notices[0] in self.screen_stack:  # the palette may sit above it: that goes too
                self.pop_screen()
        elif small and notices:
            notices[0].show_size(size)
        elif small and len(self.screen_stack) > 1:  # not before the briefing screen is up
            self.push_screen(TooSmallScreen())

    # --- themes ----------------------------------------------------------------------------------------------------

    def get_css_variables(self) -> dict[str, str]:
        """Textual's variables plus the resolved ``$wx-*``, ``$fcat-*`` and ``$cs-*`` ones for the current theme."""
        return {**super().get_css_variables(), **Palette.from_theme(self.current_theme).css_variables()}

    def redraw_screens(self, *, paste: bool = True) -> None:
        """Draw the briefing and every open screen that shows data again (their text is Rich text with the palette,
        units and clock baked in)."""
        self.briefing.refresh_view()
        for screen in self.screen_stack:
            if isinstance(screen, StationDetailScreen) or (paste and isinstance(screen, PasteDecodeScreen)):
                screen.redraw()

    def _theme_changed(self, theme: Theme) -> None:
        self.redraw_screens()
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

    def action_cycle_glyphs(self) -> None:
        self.cycle_setting("glyph_set")

    def action_cycle_units(self) -> None:
        self.cycle_setting("units")

    def action_cycle_time(self) -> None:
        self.cycle_setting("time")

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
        try:
            client = self.options.client or AwcClient()
        except AwcError as exc:  # no HTTP client can be built here (a proxy or CA setting): stay up on the cache
            self._on_error(Product.METAR, exc)
            return
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
        self.state.apply(product, rows, self.scheduler.requested if self.scheduler is not None else None)
        self.redraw_screens(paste=False)

    def _on_error(self, product: Product, error: AwcError) -> None:
        if self.scheduler is not None and not set(self.scheduler.requested) & set(self.state.ids):
            return  # the stations it was for are gone from the list: nothing will fetch again to clear this
        first = product not in self.state.errors
        self.state.record_error(
            product,
            f"{product.value}: {error}" if str(error) else type(error).__name__,
            offline=isinstance(error, TransportError),
        )
        if first:
            fetch = self.ctx.translator.t(
                K.UI_TOAST_FETCH_FAILED, product=product.value.upper(), error=error or type(error).__name__
            )
            self.notify(fetch, severity="warning")
        self.redraw_screens(paste=False)

    def refresh_now(self) -> None:
        if self.scheduler is None:
            self.notify(self.ctx.translator.t(K.UI_TOAST_POLLING_OFF), severity="warning")
            return
        held = self.scheduler.hold_remaining()
        if held > 0:  # a 429 hold: nothing is fetched until it ends
            self.notify(self.ctx.translator.t(K.UI_TOAST_RATE_LIMITED, seconds=int(held + 0.5)), severity="warning")
            return
        self.scheduler.poll_now()
        self.notify(self.ctx.translator.t(K.UI_TOAST_REFRESHING))

    def on_app_blur(self, event: events.AppBlur) -> None:
        if self.scheduler is not None:
            self.scheduler.away = True

    def on_app_focus(self, event: events.AppFocus) -> None:
        if self.scheduler is not None and self.scheduler.away:
            self.scheduler.return_from_away()  # polls at once what the away interval kept waiting past its normal time

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
                if not self.state.add(code, persist=True):  # it was only listed for this run: keep it now
                    self.notify(t.t(K.UI_TOAST_WATCHLIST_FULL, limit=WATCHLIST_CAP), severity="warning")
                    self.briefing.select(code)
                    return
                if self._save():
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

    def _warn_unreadable(self, path: Path) -> None:
        if not self._warned_unusable:
            self._warned_unusable = True
            self.notify(self.ctx.translator.t(K.UI_TOAST_CONFIG_UNREADABLE, path=path), severity="warning", timeout=10)

    def _save(self) -> bool:
        """Write the watchlist, the theme and the settings dialog's choices back when any of them changed.

        The file is read again first and only this session's changes are applied to it, so a station another
        instance added or a setting edited by hand since launch is kept. A file that cannot be read is never
        overwritten. One that holds more than a save writes back (warnings, comments, other layout) is copied to
        ``<name>.bak`` first. Returns whether the file was written.
        """
        options = self.options
        t = self.ctx.translator
        watchlist = list(self.state.watchlist)
        chosen = {k: v for k, v in self._chosen_view.items() if k not in options.flag_view}
        if self._chosen_theme is not None and not options.theme_from_flag:
            chosen["theme"] = self._chosen_theme
        saved_view = options.config.view
        changed = watchlist != self._saved_watchlist or any(
            getattr(saved_view, name) != value for name, value in chosen.items()
        )
        if not options.use_config or not changed:
            return False
        path = options.config_path or default_config_path()
        if not options.config_usable:
            self._warn_unreadable(path)
            return False
        loaded = load_config(path) if path.exists() else LoadedConfig(deepcopy(options.config))
        if not loaded.usable:  # it was readable at launch and has been broken since
            self._warn_unreadable(path)
            return False
        backup = path.with_name(path.name + ".bak")
        if path.exists():
            try:
                on_disk = path.read_text(encoding="utf-8-sig")
                hand_written = bool(loaded.warnings) or on_disk != config_text(loaded.config)
            except OSError:
                hand_written = False
            if hand_written:
                try:
                    shutil.copy2(path, backup)
                except OSError:
                    self.notify(t.t(K.UI_TOAST_BACKUP_FAILED), severity="error")
                    return False
                self.notify(t.t(K.UI_TOAST_BACKED_UP, path=backup), timeout=10)
        merged, dropped = merge_session(loaded.config, self._saved_watchlist, watchlist, chosen)
        if not save_config(merged, path):  # nothing is remembered as saved, so the next change tries again
            self.notify(t.t(K.UI_TOAST_SAVE_FAILED, path=path), severity="error")
            return False
        options.config = merged
        if dropped:  # the file was filled by another instance meanwhile: these stay for this session only
            for code in dropped:
                self.state.watchlist.remove(code)
                self.state.session.append(code)
            watchlist = [code for code in watchlist if code not in dropped]
            self.notify(t.t(K.UI_TOAST_WATCHLIST_FULL, limit=WATCHLIST_CAP), severity="warning")
        self._saved_watchlist = watchlist
        return True

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
        self.redraw_screens()
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
