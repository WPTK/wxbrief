# wxbrief — METAR/TAF briefing TUI: implementation plan

## Context

Bill wants a new terminal app that fetches METAR/SPECI and TAF reports from airports worldwide, shows them in pretty, switchable colorways, and "translates" them into plain language in English and other languages. Nothing exists yet; this is a greenfield project at `C:\Users\BK\TUI\wxbrief`.

He has already built the domain knowledge and the conventions this should reuse:

- **Decode rules**: his `metar-taf-decoder-skill` repo, with a local copy at `C:\Users\BK\Downloads\Projects\Code and Tools\metar-taf-decode\` (`SKILL.md`, `references/remarks.md`, `weather-phenomena.md`, `taf.md`, `international.md`). Covers FAA remarks, ICAO meters/QNH/CAVOK/trends, NATO color states, runway state groups, Discord output template.
- **Flight-rules logic**: `C:\Users\BK\ibm-jcl-metar-decoder\src\METARDEC.cbl` (`700-FLIGHT-RULES`, `657-INHERIT-GROUP`): FAA VFR/MVFR/IFR/LIFR thresholds and the rule that TEMPO/PROB periods inherit prevailing ceiling/vis before overlaying.
- **TUI conventions**: his `cfbtui` repo (github.com/WPTK/cfbtui), a Textual app: TOML config via platformdirs, glyph sets (ascii/unicode/emoji/nerd), layout toggle, Discord copy, settings `S` and help `?` screens, saved-payload fixtures, 3-OS CI, PyInstaller single-file releases.

### Decisions made with Bill
| Topic | Decision |
|---|---|
| Stack | Python + Textual 8.2.x (same as cfbtui) |
| Decoder | Hand-written tokenizer + group decoders; no third-party METAR library |
| Translate | Plain-language decode; English complete, **es / fr / de / pt** seeded |
| Name / path | `wxbrief` at `C:\Users\BK\TUI\wxbrief` |
| GitHub | Create **public** repo `WPTK/wxbrief` (gh is signed in as WPTK), MIT license |
| Python | `>=3.12` (local interpreter is 3.12.10; cfbtui's 3.13 floor is deliberately relaxed) |
| Versioning | **ZeroVer**: `0.MINOR.PATCH`, major stays 0; first release `0.1.0`; tags `v0.x.y`. No FibVer tool. |
| Changelog | **Common Changelog** (common-changelog.org) — rules below |
| Attribution | **No AI attribution anywhere**: no co-author trailers, no "generated with" footers, and no authorship credit in README, docs, CHANGELOG, commits, or PR descriptions. Stated in the repo's CLAUDE.md. |
| Delivery | **One fresh session per milestone**, sequential, each briefed from the committed `docs/plan.md`, to keep context windows small |

### Common Changelog rules (applied to `CHANGELOG.md`)
- `# Changelog` top heading; releases latest-first as `## 0.2.0 - 2026-11-15` (semver, no `v`, ISO date; heading linked reference-style to the GitHub release). Commit the entry **before** tagging.
- Groups only `### Changed`, `### Added`, `### Removed`, `### Fixed`, in that order, each an unnumbered list. Deprecations go under Changed. No `Unreleased` section, no Deprecated/Security groups, no Conventional-Commit markers, no pasted git log.
- Entries: one line, imperative present-tense verb ("Add TAF timeline widget"), then references in parentheses (`(#12)` preferred, else commit); authors omitted (single contributor). Breaking changes prefixed `**Breaking:**` and listed first.
- Exclude noise: dotfiles, dev-only dependency bumps, style edits, doc formatting. Include refactors, runtime changes, new docs.
- First release gets a one-sentence notice (e.g. _Initial release._) plus its groups.

### Environment facts
- Python 3.12.10 only (no uv/pipx). Installed: httpx 0.28, rich 13.9, tzdata. **Textual is not installed** — M0 installs it.
- Go 1.27, Node 26, gh 2.103 present. Windows Terminal with CaskaydiaCove Nerd Font installed.
- Data API verified against the OpenAPI spec: `https://aviationweather.gov/api/data/{metar,taf,stationinfo}` (no key; `ids`, `format=json`, `taf=true`, `hours`; 100 req/min hard limit; custom User-Agent required; 204 = no data). Daily world station list at `/data/cache/stations.cache.json.gz`.

## Architecture

### Repo layout
```
wxbrief/
├── pyproject.toml  wxbrief.spec  README.md  CHANGELOG.md  CLAUDE.md  LICENSE
├── .github/workflows/ci.yml  release.yml  stations-canary.yml
├── docs/  plan.md (this architecture + session checklist)  development.md  decoding.md  themes.md  i18n.md
├── scripts/  build_stations.py  fetch_fixtures.py  i18n_report.py  build_exe.ps1  version_info.py
├── tests/  (see Testing)
└── wxbrief/
    ├── __init__.py (__version__ = "0.1.0")  __main__.py (CLI)  app.py (WxBriefApp)  config.py  state.py  clipboard.py
    ├── decode/   tokens.py  model.py  tables.py  units.py  times.py  detect.py  metar.py  remarks.py
    │             taf.py  timeline.py  flightcat.py  colorstate.py  derived.py  split.py  groups/*.py
    ├── i18n/     __init__.py (Translator)  keys.py  plurals.py  numbers.py  locales/{en,es,fr,de,pt}.toml
    ├── data/     awc.py  models.py  poll.py  cache.py  stations.py  stations.json.gz  demo/*.txt
    ├── render/   highlight.py  phrases.py  plain.py  richtext.py  discord.py  jsonout.py  palette.py
    └── ui/       app.tcss  glyphs.py  themes/{aviation,semantic}.py  screens/*.py  widgets/*.py
```

### Decoder (`wxbrief/decode/`)
Principles: **never raise** on real input (wrap each group parser; failures become `Unknown` spans plus a `ParseWarning`); **never drop input** (every character belongs to exactly one `Token` with a `SemanticKind`, which also drives syntax highlighting); **language-neutral** (model holds codes, enums, numbers, aware datetimes; `tables.py` maps codes to i18n keys like `wx.phenomenon.RA`, never English words).

- `tokens.py`: `Token(text, start, end, kind)` from `re.finditer(r"\S+")` over the raw string so spans index the original text; `Cursor` with `peek/take/mark/reset` for multi-token groups (`1 1/2SM`, `PK WND 20032/25`, `BECMG FM1130 TL1230 0350`).
- `metar.py`: ordered section state machine (TYPE, STATION, TIME, MODIFIERS, WIND, WIND_VARIATION, VISIBILITY, RVR*, WEATHER*, SKY*, TEMP_DEW, PRESSURE, ICAO tail: RECENT_WX, WINDSHEAR, SEA_STATE, RUNWAY_STATE, TREND, COLOR_STATE, then `RMK`). Each section tries its regexes; unmatched tokens skip forward to later sections, with a small allowlist permitted to match earlier ones; otherwise `Unknown` + warning and advance one token. Same driver pattern reused by `remarks.py` and `taf.py`.
- `detect.py`: flavor (US / ICAO / mixed, `military` flag) scored from tokens (`SM`, `A####` vs `Q####`, 4-digit meters, `CAVOK`, `MPS`, color-state codes), never from the station prefix. Used only to disambiguate (RVR feet vs meters, `M1/4SM` vs `M0050`, runway-state group only in ICAO flavor).
- `units.py`: `Speed`, `Distance`, `Pressure`, `Temperature` frozen dataclasses storing the reported unit; renderers convert per `UnitsMode` (us / metric / mixed). Stdlib only.
- `times.py`: `resolve_day_time(day, hour, minute, reference)` picks the candidate month nearest the reference (API `reportTime`, or `--date`/now for pasted text); hour 24 rolls over; invalid day yields `None` + warning. Station-local rendering uses `Station.tz` from the bundled DB.
- `model.py`: `Metar`, `Taf`, `TafPeriod`, `ForecastElements` (all-optional = "unchanged"), `Wind`, `Visibility` (prefix P/M, cavok, ndv, directional minimum), `RVR`, `WeatherGroup`, `CloudLayer`/`SkyCondition` (incl. VV, SKC/CLR/NSC/NCD, `///`), `Trend`, `ColorStateGroup`, `RunwayState`, ~30 `Remark` variants from `remarks.md` (SLP, T-group, 1/2-group 6-h extremes, 5-group tendency, 6/7-group precip, PK WND, WSHFT FROPA, lightning, precip timing, 4/### snow, 8/### cloud types, Canada `SC5AC2`, free text), `Modifier` (AUTO COR NIL AMD CNL CCA…), `Flag` (CB, TCU, LOW_CEILING, LOW_VIS, GUSTS, WIND_SHEAR, FREEZING_PRECIP, THUNDERSTORM, CORRECTED, AUTOMATED, SPECIAL_REPORT, …), `Condition` for the header glyph (thunderstorm > snow/freezing > rain > obscuration > overcast > broken > partly > clear day/night).
- `flightcat.py`: FAA thresholds matching the COBOL `700-FLIGHT-RULES`; ceiling = lowest BKN/OVC/VV; one missing component computes from the other.
- `colorstate.py`: NATO table BLU 2500 ft/8 km, WHT 1500/5 km, GRN 700/3.7 km, **YLO1 500/2.5 km, YLO2 300/1.6 km** (the skill's `international.md` lists YLO1 as 700/3.7, which collides with GRN; port the standard values and cite in `docs/decoding.md`), AMB 200/0.8 km, RED below; `computed_color_state()` lets military stations show reported vs computed.
- `taf.py` + `timeline.py`: FM, BECMG, TEMPO, PROB30/40 [TEMPO], INTER (Australia), legacy 6-digit windows, WS wind shear, military icing/turb groups, TX/TN, NSW, AMD/COR/CNL. `expand_timeline(taf)` yields hourly-resamplable slices: BASE/FM replace prevailing, BECMG merges listed elements at window end (window tagged `becoming`), TEMPO/PROB/INTER overlay without altering prevailing and get a category computed from `merge(prevailing, overlay)` (COBOL `657-INHERIT-GROUP`); `worst_category` per slice.
- `split.py`: `parse_any(text)` splits pasted blobs on METAR/SPECI/TAF keywords, `=` terminators, blank lines; joins TAF continuation lines.

### i18n (`wxbrief/i18n/`)
**TOML catalogs with dotted semantic keys + `str.format_map`**, stdlib `tomllib`. Chosen over gettext/.po: no compile step or Babel dependency, keys map 1:1 to model enums, completeness is a trivial test, plain data files for PyInstaller. `scripts/i18n_report.py --export-pot` as a future escape hatch.

- `locales/en.toml` complete; `es`, `fr`, `de`, `pt` seeded with `[meta] status = "seeded"` (Settings shows a "machine-seeded" note). `[meta]` also carries `plural_rule`, decimal/group separators, `clock = "12h"|"24h"`, month/day names.
- `Translator.load(lang)` flattens to dotted keys; lookup chain `pt-BR → pt → en`; `t(key, **params)`, `t.plural(key, n, **params)` (`one`/`other`; `fr` treats 0 and 1 as singular).
- `keys.py` exposes `K.WIND_CALM = "wind.calm"` constants; a test asserts constants == en keys exactly.
- `render/phrases.py` is the **only** place keys become sentences (`describe_wind`, `describe_visibility`, `describe_sky`, `describe_weather`, `describe_remark`, `describe_trend`, `describe_period`, `summary_line`).
- Never translated: ICAO/IATA codes, raw tokens, runway designators, AWC station names, VFR/BLU codes (shown as code + translated long name), unit symbols, theme/key names, CLI `--help` (English-only at v1).
- Selection: config `[view] lang`, override `--lang`.

### Colorways (`wxbrief/ui/themes/`, `render/palette.py`)
1. **Chrome themes** = Textual `Theme` objects registered with `self.register_theme()` in `WxBriefApp.__init__`: custom `cockpit-night` (near-black, dim amber, low blue), `phosphor-green`, `phosphor-amber` (monochrome CRT), `paper-chart` (light; sectional cream, magenta/blue airspace accents), `high-contrast-dark`, `high-contrast-light`; plus curated built-ins (nord, gruvbox, catppuccin-mocha/latte, dracula, tokyo-night, monokai, flexoki, solarized-light/dark, textual-dark/light). `t` cycles, `T` opens `ThemePickerScreen` with live preview, Ctrl+P palette's built-in ThemeProvider also works. `watch_theme` persists to config (skipped when `--theme` was passed: flags are never written back).
2. **Semantic token palette** for highlighting raw text: `SEMANTIC_DEFAULTS = {"wx-station": "$primary", "wx-time": "$text-muted", "wx-wind": "$secondary", "wx-vis": "$accent", "wx-wx": "$warning", "wx-cloud": "$foreground", "wx-temp": "$success", "wx-pressure": "$primary-lighten-2", "wx-remark": "$text-muted", "wx-trend": "$secondary-lighten-1", "wx-color-state": "$accent", "wx-unknown": "$error", …}` returned from `get_theme_variable_defaults()`; themes override via `Theme.variables`. `app.tcss` declares component classes (`RawReport > .wx--wind { color: $wx-wind; }`); `RawReport` builds Rich `Text` from `get_component_rich_style()` per `HighlightSpan.kind`, so it re-skins on theme change. `highlight.py` is pure and shared with the CLI.
3. **Fixed-meaning colors**: flight category (VFR green, MVFR blue, IFR red, LIFR magenta) and NATO color states as `(dark, light)` pairs injected as `$fcat-vfr`, `$cs-blu`… by overriding `get_css_variables()` based on `current_theme.dark`; used for badges (`color: auto`) and timeline segments.
4. **CLI parity**: `Palette.from_theme(theme)` runs `theme.to_color_system().generate()` without an App and yields a Rich `Theme` so `wxbrief decode --theme paper-chart` matches the TUI.

### UI (Textual)
- `BriefingScreen`: `StationList` (OptionList: ICAO, fcat badge, wind/vis one-liner, age glyph) + `DetailPane` (`StationHeader`, `FlagsRow` chips, `RawReport` with hover-to-row linking, `DecodedTable` two-column DataTable with converted units, `Collapsible` remarks, `TafTimeline`, `PeriodDetail`, raw TAF). `v` toggles a `StationGrid` of `StationCard`s with a 12-cell mini TAF strip. `StatusBar` shows freshness, next poll, rate budget `req 3/100`, theme, glyphs, lang, units/time mode.
- `TafTimeline`: one row of hourly cells over the valid period (background = prevailing fcat color, `becoming` cells hatched, overlays in a thin second row using worst-case color), tick labels in the chosen time mode, mouse hover and `←/→` cursor drive `PeriodDetail`.
- `PasteDecodeScreen` (TextArea + reference-date input, live decode with 200 ms debounce, fully offline, `c` copies Discord block), `AddStationScreen` (Input with `Suggester` over `StationDB.search()` + results list), `SettingsScreen`, `HelpScreen`, `ThemePickerScreen`, `StationDetailScreen` (full-screen detail for grid mode).
- Keys: `↑/↓ j/k` select, `Enter`, `Tab`, `a` add, `d` remove, `p` paste, `r` refresh, `t/T` theme, `g` glyphs, `v` layout, `u` units, `z` time mode, `1/2/3` jump raw/decoded/TAF, `[`/`]` prev/next station, `c`/`C` copy Discord METAR / METAR+TAF, `y` copy raw, `S` settings, `?` help, `q` quit.
- Responsive: `HORIZONTAL_BREAKPOINTS` `-narrow` (<90 cols hides list, 3-hour cells), `-normal`, `-wide` (≥140, METAR and TAF raw side by side). Glyph sets mirror cfbtui's registry API; **default `nerd`** like cfbtui (Bill has CaskaydiaCove NF), `--glyphs unicode` for other machines.

### Data layer (`wxbrief/data/`)
- `AwcClient` (httpx.AsyncClient, UA `wxbrief/<ver> (+https://github.com/WPTK/wxbrief)`, 10 s timeout): `metars(ids, hours=2)`, `tafs(ids)`, `stations(ids)`; chunks ≤400 ids; 204 → `[]`; 429 → `RateLimited(retry_after)`; 5xx/transport → typed errors. `models.py` parses JSON tolerantly (`wdir` int or `"VRB"`, `visib` `"10+"`). Our parser runs on `rawOb`/`rawTAF` and is the display truth; AWC `fltCat` is kept for a cross-check `≠` indicator and field fallback.
- `PollScheduler` (plain asyncio in an `@work(exclusive=True)` worker, as cfbtui): intervals metar 600 s / taf 1800 s / away 1800 s, exponential backoff capped 3600 s, honours `Retry-After`; `RateBudget(100, 60 s)` sliding window shown in the status bar; one batched request per product per cycle; `Freshness` fresh <75 min else stale.
- `DiskCache` in `platformdirs.user_cache_dir("wxbrief")`, atomic write, loaded before first poll so launch is instant offline.
- `StationDB`: bundled `stations.json.gz` (~10k rows: icao, iata, faa, name, lat, lon, elev, state, country, **tz**, types) built by `scripts/build_stations.py` from the AWC cache with `timezonefinder` as a **dev-only** dependency; runtime uses `zoneinfo`. `stations-canary.yml` rebuilds monthly and opens an issue on >2 % drift.

### CLI and config
- `wxbrief [ICAO ...]` opens the TUI (ids added for this run). `wxbrief decode [RAW ...]` or stdin → Rich decode to stdout; `--plain` (auto when not a TTY), `--json`, `--discord`, `--lang`, `--theme`, `--units`, `--time station|local|zulu`, `--date`. `wxbrief get KDEN EGLL [--json|--discord|--plain]` one-shot fetch without the TUI. Global: `--theme --glyphs --layout --units --time --lang --config --no-config --demo --version`, hidden `--selftest`.
- `config.toml` in `platformdirs.user_config_dir("wxbrief")`: `[stations] watchlist` (cap 60), `[poll]`, `[view] theme glyph_set layout units time lang show_computed_color`, `[decode] show_awc_crosscheck`. Never raises on bad config (cfbtui rules).
- `--demo` loads `data/demo/*.txt`: KDEN (RMK-heavy), EGLL, ETHB (color states), UUEE (MPS, runway state), YSSY (INTER), RJTT, VIDP (fog/RVR), SBGR, CYYZ, NZSP.

### Testing
- Corpus `tests/fixtures/reports/<region>/<ICAO>_<time>.txt` + `.golden.json` (via `jsonout.to_dict`), AWC batch payloads, station sample. Regions: US, UK, Germany civil + military, France, Russia, Australia, Japan, India, Brazil, Canada, Antarctica, plus NIL, TAF AMD/CNL, legacy TAF windows, lowercase multi-report blobs.
- `test_flightcat.py` asserts our category == AWC `fltCat` for every report in a saved batch (documented exceptions list). `test_fuzz.py` with `hypothesis`: random text and mutated corpus reports never raise, every char covered, raw round-trips.
- `test_i18n.py`: every locale has every en key, param sets match, plural forms present. `test_themes.py`: all themes register, semantic vars resolve, fcat colors contrast ≥3.0 on light and dark.
- `test_client.py` (respx: 200/204/429/500/timeout, chunking, UA), `test_poll.py` (injected clock), `test_app_smoke.py` (`App.run_test()` + `Pilot`, incl. 60×20), `test_snapshots.py` with `pytest-textual-snapshot` in textual-dark / paper-chart / phosphor-green; fallback to in-house `export_screenshot()` SVG comparison if the plugin lacks Textual 8 support.
- `tests/uat/` journeys; live test only with `WXBRIEF_LIVE=1`.

### Packaging and CI
- `pyproject.toml` mirrors cfbtui: setuptools, `dynamic=["version"]`, `requires-python >=3.12`, deps `textual>=8.2,<9 httpx>=0.28,<1 platformdirs>=4,<5 tomli-w>=1,<2 pyperclip>=1.9,<2 tzdata; sys_platform=="win32"`; dev extras = cfbtui's list + `hypothesis pytest-textual-snapshot timezonefinder>=9,<10`; package-data tcss, stations.json.gz, demo, locales; ruff 120 / py312 / `E F W I B UP SIM C4 RUF`; mypy strict for `decode` and `i18n`.
- `wxbrief.spec` one-file, `datas` for tcss/stations/demo/locales + `collect_data_files("textual")`; `scripts/build_exe.ps1`.
- Versioning: ZeroVer. `__version__` lives in `wxbrief/__init__.py`, edited by hand; minor bump for features, patch for fixes, major pinned at 0. Release tag `v0.x.y` must equal `__version__` and have a matching `CHANGELOG.md` section (checked by `release.yml`).
- `ci.yml` (created in S0 so every PR is checked): 3-OS matrix on 3.12 (+3.13 informational), ruff, vulture, mypy, pytest `-n auto`, `--version`, `decode --plain` smoke; skips docs-only. `release.yml` on `v*`: version/CHANGELOG check, wheel + sdist, 5 binaries (win x86_64, linux x86_64/arm64 in `python:3.12-bullseye`, macOS arm64/x86_64), attestations, SHA256SUMS. No self-updater at v1.
- Commits and PRs carry **no AI attribution** of any kind (see Decisions). Commit subjects are plain imperative sentences; PR bodies describe the change and how it was verified.

## Delivery: one session per milestone

**Why**: each milestone is a day-sized chunk; running them in fresh sessions keeps every context window small. The design lives in the repo, not in any conversation.

**Mechanics**
- S0 commits this architecture as `docs/plan.md` plus a `CLAUDE.md` with the repo rules (ZeroVer, Common Changelog, no AI attribution, PR flow, test/lint commands, "read only `docs/plan.md` and the files you touch"). Every later session is started **fresh** with a short brief: its session number, the `docs/plan.md` section to read, and the done-when check. Nothing else is carried over.
- S0 commits directly to `main`. S1 onward: branch `s<N>-<slug>` → PR to `main` → merge on green CI (cfbtui flow). Each PR adds its `CHANGELOG.md` entries under the upcoming `0.1.0` heading only when the session changes user-visible behaviour.
- Each session ends by ticking its row in the `docs/plan.md` session checklist, noting any deviation from the design in the same file, and merging its PR. The coordinating session (this one) starts the next session only after the previous PR is merged; sessions never overlap because each depends on the last.
- Sessions do not re-survey the repo or re-fetch the API docs; the facts they need are in `docs/plan.md`.

| Session | Scope | Done when |
|---|---|---|
| **S0 Scaffold** | `git init`, pyproject, package skeleton, `--version`, ruff/mypy/pytest config, `CLAUDE.md`, `docs/plan.md`, `CHANGELOG.md` (empty `0.1.0` scaffold is *not* allowed by the spec, so the file starts with the heading only), `LICENSE` (MIT), `.gitignore`/`.gitattributes`, `ci.yml`, first commit, `gh repo create WPTK/wxbrief --public --source . --push` | `pip install -e .[dev]`, `ruff check .`, `mypy wxbrief`, `pytest` green on Windows; `python -m wxbrief --version` prints `wxbrief 0.1.0`; repo on GitHub with CI green |
| **S1 Decoder core** | `tokens`, `model`, `units`, `times`, `detect`, METAR body groups (header, wind, visibility, RVR, weather, sky, temp/dew, pressure), `flightcat`, `derived`; en catalog + `phrases`; plain/Rich renderers; `wxbrief decode` CLI; US + UK + France fixtures with goldens; hypothesis fuzz test | goldens pass; fuzz 2,000 cases no raise; `wxbrief decode "METAR KDEN …"` prints a correct LIFR decode |
| **S2a METAR tail** | `remarks` (all variants from `remarks.md`), color states, runway state, trends, recent wx, wind shear, sea state for METAR/SPECI; model additions, phrases and plain/Rich/JSON rendering of them; remaining METAR regional fixtures (ETHB and other ET/EG/EH military, UUEE, YSSY, RJTT, VIDP, SBGR, CYYZ, NZSP, NIL); AWC structured-field cross-check | all goldens pass; AWC cross-check passes with documented exceptions; `docs/decoding.md` covers the tail |
| **S2b TAF and output** | `taf` + `timeline`, `split.py`, Discord and JSON renderers with the `--json`/`--discord` flags, TAF fixtures (AMD/CNL, legacy windows, INTER) | all TAF goldens pass; `--discord` reproduces the Discord template of the reference notes; `parse_any` splits pasted blobs |
| **S3 Data layer** | `AwcClient`, `data/models`, `poll`, `cache`, `StationDB` + `scripts/build_stations.py` (commits `stations.json.gz`), `config.py`, `wxbrief get` subcommand, respx tests | `wxbrief get KDEN EGLL --plain` prints live decodes; 204/429/500 handled in tests; station search returns EGLL for "heathrow" |
| **S4 TUI MVP** | `app.py`, `state.py`, `BriefingScreen` list layout, `StationList`, `DetailPane` (header, flags, raw, decoded table, remarks), `AddStationScreen`, `PasteDecodeScreen`, `StatusBar`, clipboard, poll worker, Help screen; `textual-dark` only | `wxbrief KDEN EGLL` shows live data; offline relaunch shows cached "stale" data; `run_test` smoke passes |
| **S5 Colorways** | aviation themes, semantic token variables + component classes, fixed fcat/color-state colors with light/dark adaption, `t`/`T` + picker, persistence, CLI palette parity, snapshot tests (or SVG fallback), `docs/themes.md` | `test_themes` passes for every theme; snapshots stable in 3 themes; CLI colors match TUI |
| **S6 TAF timeline** | `TafTimeline`, `PeriodDetail`, hover/keyboard cursor, TAF sections in detail pane, `--demo` set, grid layout + `StationCard` mini strip, `v` toggle | fixture TAFs render correct per-hour categories; hover selects the right period; `--demo` runs offline |
| **S7 i18n** | es/fr/de/pt seeded catalogs, `--lang`, Settings screen (theme, glyphs, units, time, lang, refresh), `numbers.py` formatting, completeness tests, `docs/i18n.md` | `test_i18n` passes; `wxbrief decode --lang de` shows no English leakage on a RMK-heavy US METAR |
| **S8 Polish** | glyph sets + `g`, `u`/`z` modes, responsive breakpoints, AWC cross-check indicator, README, `docs/development.md`, UAT journeys, first full `CHANGELOG.md` `0.1.0` entry | usable at 60×20; UAT journeys pass; README screenshots present |
| **S9 Release** | `wxbrief.spec`, `scripts/build_exe.ps1`, `release.yml`, `stations-canary.yml`, smoke-test doc, tag `v0.1.0` **only on Bill's word** | `dist\wxbrief.exe --selftest` passes; tag produces 5 binaries + wheel + SHA256SUMS |

## Verification (end to end)
1. `pip install -e .[dev]` then `ruff check . && mypy wxbrief && pytest -n auto` all green locally (Windows) and in CI on all three OSes.
2. Decoder: `python -m wxbrief decode "METAR KDEN 131453Z 06007KT 3/4SM R35L/P6000FT BR OVC003 09/08 A3001 RMK AO2 SLP162 T00890078"` → LIFR, RVR, remarks decoded; `--lang es` → Spanish; `--discord` → block matching the skill template; same for `ETHB` color-state and `UUEE` MPS fixtures.
3. TUI: launch `wxbrief KDEN EGLL ETHB UUEE` in Windows Terminal; verify live data, `t` cycles every theme without unreadable text, `T` picker previews, `p` decodes a pasted TAF offline, TAF timeline colors match the decoded periods, `c` puts a Discord block on the clipboard, status bar shows rate budget. Resize to 60×20 and confirm it stays usable. Use the `run` skill / built-in browser screenshots as needed.
4. Offline: disable network, relaunch → cached data marked stale, `--demo` works.
5. Packaging: `scripts\build_exe.ps1` → `dist\wxbrief.exe --selftest` and `dist\wxbrief.exe --demo` on this machine.

## Risks and resolved questions
- **Textual 8.2 API assumptions** (`current_theme`, `get_css_variables` override, `HORIZONTAL_BREAKPOINTS`, `Suggester`): verify in M0 and adapt before M3 depends on them.
- **pytest-textual-snapshot** may lag Textual 8 → in-house SVG snapshot fallback.
- **Clipboard on Windows**: pyperclip first, `App.copy_to_clipboard` (OSC 52) fallback, toast on failure.
- **AWC limits/drift**: budgeted requests, tolerant JSON parsing, our parser is the truth.
- **Seeded translations** are machine-written; flagged in `[meta]` and Settings until a native speaker reviews aviation terms.
- **Day/night glyph** uses 06–20 station-local at v1; solar elevation from lat/lon is a cheap later upgrade.
- **Session hand-off drift**: a fresh session may reinterpret the design. Mitigation: `docs/plan.md` is the single source, each session records deviations there, and the coordinating session reads the merged diff before starting the next one.
- Resolved: default glyphs `nerd` (cfbtui precedent); `get` subcommand included at v1; watchlist cap 60; ZeroVer with hand-edited `__version__` (no bump tool).

---

## Session checklist

Tick a row when the session has landed on `main` (S0 committed directly; later sessions merge their PR first).

| Session | Scope | Done |
|---|---|---|
| S0 | Scaffold: package, CI, project docs | [x] 2026-10-31 |
| S1 | Decoder core | [x] 2026-10-31 |
| S2a | Decoder depth: METAR/SPECI tail (trends, color states, runway state, remarks) | [x] 2026-10-31 |
| S2b | Decoder depth: TAF, timeline, `split.py`, Discord and JSON output | [x] 2026-10-31 |
| S3 | Data layer | [x] 2026-10-31 |
| S4 | TUI MVP | [x] 2026-10-31 |
| S5 | Colorways | [x] 2026-10-31 |
| S6 | TAF timeline | [x] 2026-10-31 |
| S7 | i18n | [x] 2026-10-31 |
| S8 | Polish | [ ] |
| S9 | Release | [ ] |

## Deviations from the design

Record anything a session did differently from the design above: what changed, why, and which session did it.

### S0 (2026-10-31)

**Textual 8.2.8 API check.** The risks listed above were verified against the installed package with a throwaway
script (not in the repo). None blocks the design.

- (a) `App.register_theme(theme)` exists (so does `unregister_theme`). `textual.theme.Theme` is a dataclass with
  fields `name, primary, secondary, warning, error, success, accent, foreground, background, surface, panel, boost,
  dark, luminosity_spread, text_alpha, variables, ansi`; `variables` is the per-theme override dict the design uses.
- (b) `App.get_css_variables()` and `App.get_theme_variable_defaults()` are both overridable and return
  `dict[str, str]`. Verified at runtime: a default such as `{"wx-wind": "$secondary"}` resolves through the
  stylesheet, a `Theme.variables` entry overrides it after a theme switch, and a value computed in
  `get_css_variables()` from `self.current_theme.dark` flips between `textual-dark` and `textual-light`. Textual's
  own merge order is `{**get_theme_variable_defaults(), **theme.to_color_system().generate(), **theme.variables}`.
- (c) `App.current_theme` is a property returning the active `Theme` (`.dark` works); `App.theme` is the reactive
  name; `App.available_themes` lists registered themes. Every built-in named in the Colorways section ships in
  8.2.8 (nord, gruvbox, catppuccin-mocha/latte, dracula, tokyo-night, monokai, flexoki, solarized-light/dark,
  textual-dark/light), plus ansi-dark/light, atom-one-dark/light, catppuccin-frappe/macchiato and
  rose-pine/moon/dawn.
- (d) `HORIZONTAL_BREAKPOINTS` exists on both `App` (default `[]`) and `Screen` (default `None`, which inherits
  the app's); `VERTICAL_BREAKPOINTS` too. With `[(0, "-narrow"), (90, "-normal"), (140, "-wide")]` on the app
  the screen carried `-normal` at 100 columns, `-narrow` at 60 and `-wide` at 160 after `pilot.resize_terminal`.
- (e) `textual.suggester.Suggester` (`async def get_suggestion(value) -> str | None`) and `SuggestFromList`
  import and subclass as expected.
- (f) pytest-textual-snapshot 1.1.0 installs against Textual 8.2.8 with no resolver conflict, imports, and
  registers its `snap_compare` fixture (it pulls in syrupy and jinja2). Whether its SVG snapshots are stable under
  Textual 8 is for S5 to confirm on real screens; the in-house `export_screenshot()` fallback stays as the backup.
- Also present: `Widget.get_component_rich_style(*names, partial=False, default=None)`,
  `App.copy_to_clipboard(text)`, `Theme.to_color_system()`, and the `Collapsible`, `DataTable`, `Input`,
  `OptionList` and `TextArea` widgets.

**Design correction from the check.**

- CLI palette parity (Colorways item 4): `theme.to_color_system().generate()` returns the 168 derived colour
  variables (`primary`, `primary-lighten-2`, ...) but not `Theme.variables` and not the app's semantic defaults.
  `Palette.from_theme()` in S5 must apply the same merge as `App.get_css_variables()` (semantic defaults, then the
  generated colours, then `theme.variables`) and resolve `$name` references itself.

**Routine choices made in S0.**

- `LICENSE` names "Bill Kane" (matching cfbtui's LICENSE and `authors` in `pyproject.toml`) rather than the git
  `user.name`, which is the GitHub handle `WPTK`.
- `wxbrief/i18n/locales/`, `wxbrief/data/demo/` and `scripts/` stay empty until S3, S6 and S7, so each holds a
  `.gitkeep` to keep the layout visible and the CI `vulture wxbrief scripts` step valid. Delete each `.gitkeep`
  when its first real file lands.
- `wxbrief` with no arguments prints the parser help and exits 0 until S4 wires up the TUI; `--version` is the
  only flag.
- `pyproject.toml` sets `asyncio_default_fixture_loop_scope = "function"` next to `asyncio_mode = "auto"` so
  pytest-asyncio stays warning-free.
- `.gitignore` also covers `.hypothesis/`, `.coverage`, `htmlcov/`, `.pyi-build/`, `snapshot_report.html`, editor
  folders and local tooling folders. `.gitattributes` adds `*.yml` to the LF rules.
- The Attribution row of the Decisions table above was reworded after the verbatim copy so that the repo names no
  AI vendor; the rule itself is unchanged.
- mypy: the whole package runs with `check_untyped_defs`, `warn_redundant_casts` and `warn_unused_ignores`;
  the strict set applies to `wxbrief.decode.*` and `wxbrief.i18n.*` through a per-module override. Writing
  `strict = true` inside that override made mypy 2.4.1 apply strict to every module (an untyped function under
  `wxbrief/ui/` was flagged too), so the override spells out the per-module flags instead
  (`disallow_any_generics`, `disallow_subclassing_any`, `disallow_untyped_calls`, `disallow_untyped_defs`,
  `disallow_incomplete_defs`, `disallow_untyped_decorators`, `warn_return_any`, `implicit_reexport = false`,
  `strict_equality`, `extra_checks`). Probed: untyped functions under `decode/` and `i18n/` fail, under `ui/` pass.
- Dev extras resolved on 2026-10-31 to textual 8.2.8, httpx 0.28, mypy 2.4.1, ruff 0.17.3, vulture 2.16,
  pytest 8.4.2, pytest-asyncio 1.4.1, pytest-xdist 3.8.0, pytest-textual-snapshot 1.1.0 (syrupy 4.8.0),
  hypothesis 6.170.14, respx 0.23.1, timezonefinder 9.2.0 and pyinstaller 6.22.3.

### S1 (2026-10-31)

**For S2: how the tail is tagged.** `decode/groups/tail.py` only recognises the groups between the pressure and `RMK`;
it tags tokens and decodes nothing, so highlighting works and no "unknown token" warning is raised. `NOSIG` is one
`TREND` token. `BECMG`/`TEMPO` plus every token after it up to the next trend keyword or `RMK` are all `TREND` (a
colour-state code inside the body is `COLOR_STATE`). `RERA`-style groups are `RECENT_WEATHER`, `WS ALL RWY`/`WS R24L`
are `WIND_SHEAR`, `W15/S3` is `SEA_STATE`, `BLU`/`YLO2`/`BLACK` are `COLOR_STATE`, and `88290192`, `R24L/290255`,
`R06R/CLRD62`, `R/SNOCLO` are `RUNWAY_STATE` (only when the detected flavor is not US). `RMK` and everything after it
is `REMARK`. On `Metar`: `tail_index` (index into `tokens` of the first tail token, `None` if no tail),
`remarks_index` (the `RMK` token), `remarks_raw` (verbatim text after `RMK`, `""` for a bare `RMK`, `None` without
one), and the properties `tail_tokens` and `remarks_tokens` (terminator excluded). S2 decodes from those token
slices and refines the kinds where it needs to; the extra model objects (`Trend`, `ColorStateGroup`, `RunwayState`,
remark variants ...) are S2's to add, and adding fields to `Metar` changes every golden (rerun `--update-goldens`
and review the diff).

**Final model names S2 builds on.** `decode/model.py`: `Metar(raw, tokens, report_type, station, observed, modifiers,
wind, wind_variation, visibility, rvr, weather, sky, temperature, dewpoint, altimeters, tail_index, remarks_index,
remarks_raw, flavor, military, ceiling, flight_category, flags, condition, relative_humidity, warnings)` with
`altimeter`, `cavok`, `tail_tokens`, `remarks_tokens` as properties; `Wind(direction, speed, gust, variable,
speed_above)`; `WindVariation(start, end)`; `Visibility(distance, prefix, cavok, unlimited, ndv, directional,
not_reported)`; `DirectionalVisibility(distance, direction)`; `RVR(runway, distance, prefix, variable_to,
variable_to_prefix, trend)`; `WeatherGroup(intensity, descriptor, phenomena, vicinity, nsw, not_observed)`;
`CloudLayer(cover, base, cloud_type)` with `cover` a `SkyCondition` (FEW, SCT, BKN, OVC, VV, SKC, CLR, NSC, NCD,
UNKNOWN for `///`); `ParseWarning(code, start, end, text)`; quantities in `decode/units.py` (`Speed`, `Distance`,
`Pressure`, `Temperature` and `UnitsMode`). Enums: `SemanticKind`, `ReportType`, `Modifier`, `Flavor`,
`FlightCategory`, `Flag` (including `WIND_SHEAR`, derived in S2), `Condition`, `VisPrefix`, `Intensity`, `Descriptor`,
`Phenomenon`, `CloudType`, `RvrTrend`. Group parsers are `parse_*(cursor)` functions returning a value and tagging the
tokens they take, or `None` without consuming; to add a section, add a parser and a `_Step` in `decode/metar.py`.
Keep regexes free of nested or overlapping repeats (see `_RECENT` in `tail.py`); the fuzz test has a timing check.

**How to add a fixture** is in `docs/decoding.md`. S1 saved three AWC batches (647 distinct reports, 2026-10-31)
under `tests/fixtures/awc/` and 65 report/golden pairs (20 hand-written) under
`tests/fixtures/reports/{us,uk,france,world}`; the `world/` folder holds one hand-written UUEE case (MPS winds, runway
state) that S2's regional fixtures can sit beside. Every golden was read against its raw report. The fltCat parity test
passes on all 647 saved reports with an empty exceptions list. Keys: edit `locales/en.toml`, run
`python scripts/gen_keys.py` (added in S1 although the plan did not list it).

**Deviations and routine choices.**

- CHANGELOG policy: the Delivery section says each PR adds entries under the upcoming `0.1.0` heading, but Common
  Changelog has no Unreleased section. Sessions S1 to S7 leave `CHANGELOG.md` untouched and S8 writes the single
  `0.1.0` entry from the merged PRs; `CLAUDE.md` says so.
- The tokenizer splits a trailing `=` off as its own `TERMINATOR` token (plan: plain `\S+` split) so `A3001=` still
  matches the pressure group. `remarks_raw` leaves the terminator out.
- `UnitsMode` (`us`, `metric`, `mixed`) lives in `decode/units.py` and is a rendering choice only. `us`/`metric` force
  that system and keep the reported value in parentheses when it differs; `mixed` (CLI default) shows the reported
  value first and the other system in parentheses. The plan did not define the modes beyond their names.
- `render/measure.py` (unit formatting; unit symbols are not translated) was added; the plan's render layout did not
  list it. `phrases.py` stays the only place that composes words.
- Times print as UTC ("2026-10-13 14:53 UTC"); station-local time needs the station DB from S3. `Condition` parses to
  `CLEAR`; `derived.refine_clear(condition, local_hour)` turns it into `CLEAR_DAY`/`CLEAR_NIGHT` (06 to 20 local) once
  the hour is known.
- `wxbrief decode` reads one report per non-blank stdin line; with several arguments that contain no whitespace they
  are joined into one report, otherwise each argument is a report. `--date` means noon UTC of that date. No input is
  exit code 2 with a message; any text, however broken, is exit 0 with a warning list. Output is plain when stdout is
  not a terminal or `--plain` is given; stdout errors are set to `replace` so a legacy console never raises.
- `ci.yml` gained the `decode --plain` smoke step that the plan attributes to S0 (the command did not exist then).
- A four-character word is accepted as the station only when a day/time group follows, when it follows `METAR`/
  `SPECI`, or when it is the only token (garbage like `THIS IS NOT A REPORT` otherwise yields a station `THIS`).
- Minimum visibility: besides `1200NW` and `NDV`, a bare four-digit group lower than the prevailing metres visibility
  (`0350 0300`, as French automatic stations send) is stored in `Visibility.directional` with `direction=None`.
  `0000` is stored as 50 m with prefix `LESS_THAN`; `9999` as 10 km with `unlimited`.
- Flags: `LOW_CEILING` is a ceiling below 1,000 ft and `LOW_VISIBILITY` a visibility below 3 SM (the IFR thresholds);
  `FREEZING_PRECIP` needs `FZ` with `RA`, `DZ` or `UP` (freezing fog is not precipitation); `THUNDERSTORM` includes
  `VCTS`. `WIND_SHEAR` exists in the enum but is derived in S2.
- Condition: the metar-taf-decode notes say `VCTS` counts as a thunderstorm yet other vicinity weather must not
  override the sky; both are implemented. `VV` counts as overcast; `IC` (ice crystals) counts as snow.
- Flight category: a ceiling layer of unknown height (`VV///`, `BKN///`) is ignored, and a report with neither
  visibility nor sky has no category. Distances of the same unit convert exactly (no `/ 0.3048 * 0.3048` drift).
- `TAF` input is not decoded in S1: the report gets one `unsupported_report` warning and all tokens stay `UNKNOWN`.
- `Metar.relative_humidity` is rounded to one decimal so goldens do not depend on the platform's `exp`.
- Rich output uses a built-in default theme with dotted style names (`wx.wind`, `fcat.ifr`); mapping the colourways
  onto those names is S5.

### S2a (2026-10-31)

**The split.** The original S2 was too big for one context. S2a (this session) covers everything for METAR/SPECI after
the body: trends, color states, runway state, recent weather, wind shear, sea state and the remarks, with their phrases
and plain/Rich/JSON rendering, the regional METAR fixtures and the AWC cross-check. S2b takes TAF, the timeline,
`split.py`, and the Discord and JSON output (`--json`/`--discord` flags). Both rows are in the table and the checklist
above; the other sessions are unchanged.

**Color-state thresholds.** The reference notes (`metar-taf-decode/references/international.md`) list `YLO1` as 700 ft / 3.7 km, which collides with `GRN`.
The design's figures are the standard ones and are verified: the UK Met Office aerodrome colour state register
(https://reference.metoffice.gov.uk/aviation/UKAerodromeColourStates; entries `BLU` 8000 m, `WHT` 5000, `GRN` 3700 /
700 ft, `YLO1` 2500 m / 500 ft, `YLO2` 1600 m / 300 ft, `AMB` 800 m) and the Wikipedia "Colour state" table agree. They are
cited in `docs/decoding.md` and in `decode/colorstate.py`. As a check, all 47 saved military reports that carry a
colour (German, Dutch and UK fields) recompute to the reported colour with this table. Plain `YLO` (no digit, used by
Dutch and German fields) has the `YLO2` minimums in every saved example and is stored as its own code `ColorCode.YLO`.

**Not verified, flagged.** (1) The `+` suffix on `BLU+` (ETHL, ETNN): no source found; it is stored as `plus` and
displayed as reported ("Blue (BLU+)") without an interpretation. (2) `///` as the last group of German AUTO reports
(`... Q1033 ///`) is read as "colour state not reported" from its position; it is stored as
`ColorState(None, not_reported=True)`. If it means something else, only that parser and one phrase change.

**Model (names as built).** In `decode/model.py`: `Trend(kind, times, elements)` with `TrendKind` (`NOSIG`, `BECMG`,
`TEMPO`; the field is `kind`, not `type`), `TrendTime(kind, hour, minute, moment)` with `TrendTimeKind` (`FROM`, `UNTIL`,
`AT`); `ForecastElements(wind, visibility, weather, sky, color_state)` (the plan listed it under S2; it is here because
`Trend` carries it; empty means unchanged); `ColorCode` (adds plain `YLO`), `ColorState(code, black, plus, not_reported)`,
`ColorForecast(state, change)`, `ColorStateGroup(current, forecast)`; `RunwayState(runway, all_runways, repeated, snoclo,
cleared, deposit, extent, depth, braking)` with `RunwayDeposit`, `RunwayExtent`, `RunwayDepth`/`RunwayDepthKind`,
`RunwayBraking`/`BrakingAction`; `RecentWeather(weather)` wrapping a `WeatherGroup`; `WindShearRunway(runway,
all_runways)`; `SeaState(temperature, state, wave_height_m)`; `Remark` and 35 frozen variants (the 30 listed in the brief
plus `ColorStateRemark`, `StationPressure` (QFE/QNH), `RunwayWind`, `AltimeterSetting` and `WindAtHeight`, which the real
Russian, Norwegian, Turkish and Asian reports in the saved batches needed); `RemarkTime(minute, hour)`. `Metar` gains
`trends`, `color_state`, `computed_color_state`, `runway_states`, `recent_weather`, `wind_shear`, `sea_state`, `remarks`
and `remarks_of(VariantClass)`. `jsonout.to_dict` writes `"variant": "<ClassName>"` on every remark because remarks are
a union. `Flag` gains `COLOR_BELOW_GRN`, `RAPID_PRESSURE_CHANGE`, `RUNWAY_CONTAMINATED`, `MAINTENANCE`, `VOLCANIC_ASH`
and `MISSING_DATA` (definitions in `docs/decoding.md`); `WIND_SHEAR` is now derived.

**Behaviour choices.**

- Token kinds: no new `SemanticKind`. The finer kinds are the existing ones used more precisely: a trend keyword and its
  `FM`/`TL`/`AT` times are `TREND`, its body elements `WIND`/`VISIBILITY`/`WEATHER`/`SKY`/`COLOR_STATE`; remark tokens
  are `PRESSURE`, `TEMPERATURE`, `WIND`, `VISIBILITY`, `WEATHER`, `SKY` by what they are, and `REMARK` for the rest.
  `highlight.py` and `richtext.py` needed no change (they style by kind); tests cover it.
- `computed_color_state` is filled only when the report carries a colour state (the plan says military reports show
  reported against computed). `decode/colorstate.py` also offers `visibility_meters`, `is_below_green` and
  `reported_matches_computed` (plain `YLO` matches a computed `YLO1` or `YLO2`). The ceiling is the lowest broken,
  overcast or vertical-visibility layer; the UK register counts scattered cloud too, so a UK field can legitimately
  report a worse colour than we compute.
- `military` is also set when the colour state sits in the remarks (RAF stations: `RMK YLO1 YLO1`), and not by `///`
  or a bare `BLACK`.
- A colour group is split from a weather trend by looking ahead: `TEMPO`/`BECMG` followed by a colour code belongs to
  the colour group (`BLU TEMPO YLO`), anything else starts a trend. A colour code inside a trend body is that trend's
  `color_state`.
- `tail.py`: `parse_tail_group(cur, flavor, observed)` now returns a `TailResult` (the kind of the first token plus the
  decoded value) instead of a bare `SemanticKind`; `is_color_state` moved to `groups/colorstate.py`
  (`COLOR_STATE_BASE_CODES` is gone). A bare `WS` is no longer recognised.
- Trend body tokens the parser cannot place stay `UNKNOWN` and get the usual `unknown_token` warning; the body carries on
  with the next token.
- Plain decode: the "Trend and other groups (raw)" row is gone; trends, color state, runway state, recent weather, wind
  shear and sea state have their own rows, each remark is a "Remark" row, and "Remarks (not decoded)" lists only the
  words of free text the catalog cannot spell out. A "Color state (computed)" row appears when the computed state
  differs from the reported one or none was reported.
- Units: precipitation, snow and hail are inches (`measure.format_inches`), runway depth millimetres/centimetres
  (`format_millimeters`), wave height metres, and `format_pressure`/`format_temperature` take `precise=True` for the
  T-group and sea-level pressure. Float rounding means 1.75 in prints as 44.4 mm.
- A latent S1 bug is fixed: a sky made only of `//////` placeholders (cover unknown) was treated as "no ceiling" and
  could make an empty report VFR; it now says nothing, and `flight_category` is `None` when visibility is missing too.
  Verified against AWC (`fltCat` is null for those reports).

**Fixtures and tests.** The corpus grew from 65 to 139 report/golden pairs (32 hand-written) in 14 regions: new folders
`canada`, `germany`, `netherlands`, `norway`, `russia`, `india`, `japan`, `australia`, `brazil`, `antarctica`. Two fresh
polite requests to the AWC API (2026-10-31, honest User-Agent) added `metar_military_20261031.json` (German, UK, Dutch,
Belgian-area military fields and eastern Europe and Russia, 270 reports) and `metar_world2_20261031.json` (400 reports
from the Gulf, Asia, Oceania, the Americas and Africa); 1,248 distinct saved reports in all. Every golden was read
against its raw text: the 74 new ones one by one, the 65 old ones as a diff (new empty fields, finer token kinds, the
decoded remarks and trends, the added flags). `tests/test_flightcat.py` parity exceptions are now named rules with
reasons (German AUTO reports with an unobserved sky; Greenland's `9999NDV`) and a staleness check.
`tests/test_awc_crosscheck.py` is the new cross-check (see `docs/decoding.md`). New unit tests: `test_tail.py` (each
group parser), `test_remarks.py` (every remark variant, enforced), `test_colorstate.py`, `test_phrases_tail.py`; the
fuzz test gained tail and remark inputs (it also passed 20,000 examples per property once, locally).

**For S2b: what to reuse.**

- `decode/groups/trend.py`: `parse_trend_body(cur, observed, stop)` reads time qualifiers and
  `ForecastElements` (wind, visibility, weather, sky, colour) until `stop(token)`; `parse_trend_time` handles
  `FM`/`TL`/`AT` + `HHMM`. TAF change groups have their own time syntax (`FM101200`, `1012/1018`, `PROB30`), so write
  those parsers, but read the elements of a period with `parse_trend_body` (give it a `stop` that ends at the next
  `FM`/`BECMG`/`TEMPO`/`PROB`/`INTER`/`RMK`), and reuse `ForecastElements` as the period payload. TAF-only elements
  (temperatures `TX`/`TN`, `WS020/30035KT`, icing and turbulence groups) are S2b's to add around it.
- `decode/times.py`: `resolve_clock_time(hour, minute, reference)` picks the day for a bare time; a TAF should resolve
  against its issue time, not an observation. `resolve_day_time` handles `DDHHMMZ`.
- `decode/colorstate.py` and `flightcat.py`: `computed_color_state(ceiling_ft, visibility_m)`, `visibility_meters`,
  `classify`, `ceiling_for_classification` give per-slice categories and colours for the timeline.
- `Cursor.token_at(index)` and `Cursor.kind_at(index)` exist for warnings after a group parser.
- Rendering: `phrases.describe_forecast_elements(t, elements, units)` and `describe_trend_time` render a period's
  elements; `describe_color_code`/`describe_color_state`, `describe_wind`, `describe_visibility`, `describe_weather`,
  `describe_sky` are public. For the Discord template: `metar.remarks_of(SeaLevelPressure)`,
  `PressureTendency` (net direction and `change_hpa`, "rising +0.8 mb/3hr"), the 6-hour and 24-hour extremes and the
  peak wind give the extra lines; `metar.trends` gives the ICAO trend line (`NOSIG` -> "Trend: NOSIG (no significant
  change next 2 hrs)" is `describe_trend`); `Metar.condition` is the header emoji; `render/plain.py` `decode_rows`
  shows how the rows are ordered and labelled.
- `render/jsonout.to_dict` already converts any frozen dataclass, tuples, enums and datetimes; a new `Taf` model only
  needs to be a dataclass. Remark variants carry `"variant"`.
- Catalog: add keys to `locales/en.toml`, run `python scripts/gen_keys.py`; `test_i18n` checks the tables in
  `decode/tables.py` against the catalog and the enums.
- AWC TAF JSON was not fetched or saved here (S2b did; see below).

### S2b (2026-10-31)

**How it was built.** The decoder, timeline, `split.py`, Discord renderer and AWC TAF cross-check were written first
and arrived as one local snapshot; the rest of S2b (fixtures, unit tests, docs, the review of the METAR golden changes)
was added around it and the history cut into logical commits.

**Model (names as built).** In `decode/model.py`: `Taf(raw, station, issue_time, valid_from, valid_to, modifiers, base,
changes, remarks, flavor, tokens, warnings, worst_category, report_type, temperatures, flags, legacy)` with the
properties `periods`, `amended`, `cancelled` and `nil`; `TafPeriod(change, probability, start, end, elements,
flight_category, tokens, becoming_end)`; `ChangeType` (`BASE`, `FM`, `BECMG`, `TEMPO`, `INTER`, `PROB`, `PROB_TEMPO`, `PROB_INTER`);
`TafTemperature(kind, temperature, day, hour, time)` with `TemperatureExtreme`; `WindShearLayer`, `IcingGroup`,
`TurbulenceGroup` with their intensity enums. `ForecastElements` (from S2a) gains `wind_shear`, `altimeter`, `icing`
and `turbulence`, so every METAR trend now carries four more (empty) fields. `Timeline`, `TimelineSlice`,
`TimelineOverlay` and `TimelineHour` describe the expansion. `parse_trend_body` takes an optional `extra` hook for the
TAF-only groups. The METAR parser's "unsupported TAF" special case is gone (`parse_any` picks the parser).

**Fixtures and tests.** TAFs live in `tests/fixtures/reports/taf-<region>/` (`taf-americas`, `taf-europe`,
`taf-world`) so the METAR corpus helpers and tests are untouched (`corpus.report_files()` still returns METARs;
`taf_files()` returns TAFs). 36 report/golden pairs: 24 real (from the five saved AWC TAF batches of 2026-10-31: 204
distinct forecasts) and 12 hand-written. The real batches contain no `CNL`, no `NIL`, no wind shear group, no
six-digit legacy valid period and no `INTER` outside Australia, so those forms are hand-written (`CNL`, `NIL`,
`WS020/30035KT`, `301212` with `BECMG 1517` and `FM2000`, `INTER`, `PROB30 TEMPO`, terminator `=`, negative
extremes). Every golden was read against its raw text (valid period, each window, the category of each group, extremes,
icing and turbulence codes). New tests: `test_taf_goldens.py`, `test_taf.py`, `test_tafgroups.py`, `test_timeline.py`,
`test_split.py`, `test_discord.py`, CLI tests for `--json`/`--discord`, and the fuzz test now covers TAFs (mutated
corpus, `parse_any` on mixed blobs, a pathological-input timing test).

**The 49 changed METAR goldens.** Every change is the same: `ForecastElements` inside a trend gained `wind_shear: null`,
`altimeter: null`, `icing: []`, `turbulence: []` and the preceding `color_state` line gained a comma (50 hunks in 49
files, WSSS has two trends). Nothing else moved in any METAR golden.

**Deviations.**

- The Discord template of the reference notes (`metar-taf-decode`, `SKILL.md`) was not available on this machine. The
  tests pin the layout documented in `render/discord.py`, which was written from the notes; the "`--discord` reproduces
  the template" check in the table still needs a comparison against the notes. Known differences from the template as
  quoted in the module: a station name arrives with the station database (S3), so the title is the ICAO code only; the
  separator before `AUTO` is an em dash; temperatures show both units.
- Unread TAF notes: the real KRIV (`WND 230V330`) and NZSP (`WND21008KT AFT 3122 ALL WINDS GRID`) forecasts keep those
  words as unknown tokens with a warning. Their goldens record it and `test_taf_goldens.py` names the two stations.
- `parse_any` keeps every non-blank character, so a stray `=` between reports becomes a one-token report with an unknown
  token warning rather than being dropped.

**For S3 and later.**

- Station name and local hour plug into `discord_block(..., station_name=, local_hour=)` and `condition_emoji`; both are
  tested but unused by the CLI.
- `PROB30 INTER` is its own `ChangeType.PROB_INTER` (an overlay like `PROB_TEMPO`), so the probability reaches the plain
  and Discord headings. AWC reports both `INTER` forms as `TEMPO`.
- `worst_category` counts a `BECMG` from the start of its window (the change may land at any moment), so it can be worse
  than the `category` of every slice. `split_reports` keeps `TAF AMD` and the line after it together, and a TAF wraps
  on any line that does not start with a keyword or a station and issue time. Legacy windows and notes
  (`1517`, `AFT 3023`) no longer take part in flavor detection (they read as metre visibility). Piped output is UTF-8.
- The TUI timeline strip should read `Timeline.hourly()` (`category`, `worst_category`, `becoming`, `overlay`); the
  cell colours are the flight category, and `TimelineSlice` has the prevailing and overlay elements for a detail view.
- `parse_any(text, reference)` is the entry point for the paste screen; the reference for a TAF is its receipt time.
- The AWC client should store `rawTAF` and `issueTime` per station; `issueTime` is the right reference for
  `parse_taf` (as the cross-check does). AWC TAFs sometimes lack an issue time (military `TAF KNID 3023/3123`).
- Locale catalogs: S2b added the `taf.*` and `discord.*` keys to `locales/en.toml`, the only catalog so far (S7 adds the rest).

### S3 (2026-10-31)

**Names as built.**

- `data/awc.py`: `AwcClient(base_url=, client=, timeout=)` with `metars(ids, hours=2)`, `tafs(ids)`, `stations(ids)`, usable as an
  async context manager; constants `BASE_URL`, `USER_AGENT`, `MAX_IDS_PER_REQUEST = 400`. Errors: `AwcError` base, `RateLimited(retry_after)`
  (default 60 s when the header is missing or unreadable), `ServerError(status)`, `ClientError` (other 4xx, or a body that is not JSON),
  `TransportError` (timeout, DNS, connect, TLS). 204 gives `[]`. Chunks go out one after another; a failure in any chunk raises.
- `data/models.py`: frozen `AwcMetar`, `AwcTaf`, `AwcStation`; `parse_metars/tafs/stations` drop rows without a raw report and turn a
  mistyped field into `None`; `parse_visibility("10+") -> (10.0, True)`; `latest_by_station`. `AwcMetar.source`/`AwcTaf.source` keep the
  original JSON object, which is what the cache stores.
- `data/poll.py`: `PollScheduler(client, ids, on_result, on_error, budget=, clock=, sleep=, metar_interval=, taf_interval=, away_interval=)`
  with `run_cycle()` (one pass, returns the products attempted), `run()` (loop; cancel it to stop), `poll_now()`, `next_due_in()`, `.away`;
  `RateBudget(100, 60, clock)` with `used`, `remaining`, `try_acquire`, `wait_time`; `Freshness` and `freshness(observed, now)` (fresh under
  75 min); `backoff_delay(interval, failures)`. A 429 waits at least its `Retry-After` (capped at 3600 s). The scheduler is plain asyncio and
  does no Textual work, so S4 runs `run()` inside its `@work(exclusive=True)` worker.
- `data/cache.py`: `DiskCache(directory=None)` with `write(key, payload)` (atomic, returns `False` on failure) and `read(key)` returning
  `(saved_at, payload)` or `None`; never raises.
- `data/stations.py`: `StationDB.load(path=None)`, `get(code)` (ICAO, or a unique IATA/FAA code), `search(query, limit=10)`; `bundled()`
  is the shared instance. `scripts/build_stations.py` builds `wxbrief/data/stations.json.gz` (8,751 stations with an ICAO id and valid coordinates,
  full coordinate precision, 258 KB) from the AWC `stations.cache.json.gz`, with `timezonefinder` imported only inside the script. It skips placeholder
  coordinates such as -99.99. The output is deterministic (sorted, gzip without timestamp).
- `config.py`: `load_config(path=None) -> LoadedConfig(config, warnings)`, `parse_config`, `save_config`, `default_config_path`, `clean_watchlist`.
  Each bad value falls back on its own and adds a warning; a missing file gives defaults with no warning.
- `getcmd.py` (new, so `__main__.py` changes by four lines): `wxbrief get ICAO... [--json|--plain] [--units]`.

**Deviations.**

- `StationDB` search covers name, state and country text plus codes; it does not search a city column because the AWC cache has none.
- `wxbrief get` decodes TAFs with `parse_taf` (AWC issue time as the reference) and renders `--discord` with `render_discord`
  (station name from the station DB, local hour from its time zone). `--json` gives `{icao: {"metar": <to_dict>, "taf": <to_dict>}}`. Units default
  as in `decode`: mixed, or US with `--discord`.
- `get` fetches `hours=2` and keeps the newest report per station; a station with no report in that window prints "no METAR".
- No `stations-canary.yml` yet (S9 per the table).

**For S4.**

- Run `PollScheduler.run()` in the poll worker; feed `on_result` into the state, write `[m.source for m in rows]` to
  `DiskCache("metars")`/`("tafs")`, and rebuild rows with `parse_metars(payload)` at launch for an instant offline start. `DiskCache.read`
  also gives the `saved_at` time for the stale marker; `freshness()` judges each report's own observation time.
- Show `scheduler.budget.used`/`remaining` in the status bar. Call `poll_now()` after adding a station and set `scheduler.away = True` when
  the window loses focus.
- The ids callable is read at the start of each cycle, so watchlist edits need no restart.
- `AwcMetar.flight_category` is AWC's `fltCat` for the cross-check indicator.
- `tests/fixtures/awc/metar_kden_egll.json` and `taf_kden_egll.json` (2026-10-31) include a real TAF payload for S2b/S6.

**Known limitations / S4 hand-off.**

- `RateBudget` counts one request per product per cycle, not per 400-id chunk; `wait_time(count)` with `count` above the limit raises
  `IndexError`. A 429 holds back every track, not only the product that got it.
- `save_config` rewrites the file without comments or unknown keys, so S4 must not save after a load that produced a parse-error warning, or
  must back the file up first.
- `stations.json.gz`: the `tz` field comes from `timezonefinder` data (ODbL), so add attribution before 0.1.0; record the AWC cache date and
  the `timezonefinder` version used for the build; add a test that every `tz` is a valid `zoneinfo` key. Seven IATA codes are ambiguous
  (GWD, ISU, CEM, PTZ, GYA, VTZ, SRG), and `get()` returns `None` for them.
- `DiskCache.read` accepts a naive `saved_at`; treat it as damaged or give it UTC.
- Refocus after away mode should call `poll_now()`.
- `wxbrief get` exit codes: 0 all arrived, 3 one product failed but some data arrived, 1 nothing arrived for any requested station.

### S4 (2026-10-31)

Screenshot of the briefing screen (120x36, `textual-dark`, saved KDEN and EGLL reports): `docs/s4-briefing.svg`.

**Names as built.**

- `app.py`: `AppOptions` (ids, `config` as loaded, `view` as in effect, `config_path`, `use_config`, `config_warnings`, `cache_dir`,
  `client`, `poll`, `now`) and `WxBriefApp(options)`. The poll worker is `poll_worker` (`@work(exclusive=True, group="poll")`) and builds
  a `PollScheduler`, kept as `app.scheduler`. `app.state`, `app.ctx`, `app.briefing`, `add_station`, `remove_station`, `refresh_now`.
  Command-line flags change `options.view` only; `options.config` is what `save_config` writes, so a flag is never saved.
- `state.py`: `AppState(watchlist, session, cache, now)` with `ids`, `add(icao, persist=)`, `remove`, `apply(product, rows)` (decodes,
  writes the cache), `load_cache()`, `reports()`; `StationReports(icao, awc_metar, awc_taf, metar, taf, updated, from_cache)`.
- `clipboard.py`: `copy_text(app, text, what)`. `ui/context.py`: `ViewContext` (translator, units, glyphs, time mode, station DB, and
  `palette` for the active theme). `ui/style.py`: `Palette` maps the decoder's `wx.*` style names to Rich styles from the theme's
  variables, plus fixed flight-category badges. `ui/glyphs.py`: `GLYPH_SETS`, `glyphs_for`. `getcmd.local_hour` is now public.
- Screens in `ui/screens/`: `briefing`, `add_station` (with `StationSuggester`), `paste`, `help`, `settings` (read-only). Widgets in
  `ui/widgets/`: `station_list`, `detail` (`StationHeader`, `FlagsRow`, `RawReport`, `DecodedTable`, `DetailPane`), `status_bar`.
- CLI: `wxbrief [ICAO ...]` opens the TUI; `decode` and `get` are unchanged. Global flags `--glyphs --layout --units --time --lang
  --config --no-config` (`--units` is stored as `tui_units`). Without a terminal on stdin and stdout, `wxbrief` prints the help and exits 0.

**Deviations.**

- `--demo` is deferred to S6 (the demo reports do not exist yet). `--theme` is S5's. `--layout grid` is accepted and shows a toast; the
  grid arrives in S6. `S` opens a read-only settings view, the editable one is S7. `g`, `u`, `z`, `t`, `T`, `v` are not bound yet.
- Ids given on the command line are for the run only (not saved). `a` saves the station to the watchlist; with `--no-config` it is kept
  for the run only. A config that loaded with warnings is copied to `config.toml.bak` once before the first save.
- The TAF in the detail pane is the plain-text decode plus the highlighted raw TAF; S6 replaces it with the timeline.
- Raw-text colours come from `ui/style.py`, not component classes in `app.tcss`; `app.tcss` uses built-in theme variables only. Textual
  8.2.8 does not expand `$name` references held in a variables dict, so S5 must put resolved values into `get_css_variables()`.
- Narrow terminals (under 90 columns) hide the list; `j`/`k`/`[`/`]` change station. 60x20 is covered by a test.
- Paste screen: `c` types a letter while the text box has focus, so copy is also `F2` (always works); `Tab` leaves the box (`tab_behavior="focus"`).
- Refocus: after away mode the scheduler is set back to normal and `poll_now()` is called on every refocus from away.
- Cache: a cache file whose `saved_at` has no time zone is ignored as damaged.

**For S5.** `Palette` and `ViewContext.palette` are the single place the TUI turns style names into colours; replace the `_SEMANTIC` and
`_BADGES` tables in `ui/style.py` (the badge colours are fixed Rich names today). The list and detail redraw on every poll and every
30 s, so they pick up a theme change at the next redraw; call `briefing.refresh_view()` from `watch_theme`.

**For S6.** The detail pane has `#taf-title`, `#taf` (plain text); put `TafTimeline` and `PeriodDetail` there. `1/2/3` jump to
`#raw-title`, `#decoded-title`, `#taf-title`. `AppOptions.layout` is read only for the "grid" toast.

**For S7.** `SettingsScreen(lines)` takes `(name, value)` pairs; replace it. Only `en` exists, `Translator.load(view.lang)` falls back to it.

**After review (PR #21).**

- `PollScheduler.hold_until` is set by a 429 and `poll_now()` never makes a track due before it. On refocus the app calls `poll_now()`
  only when it was away for at least the METAR interval (`app._monotonic`, `_blurred_at`).
- Enter on a station focuses the detail pane through `OptionSelected` (the list's own binding wins over a screen binding).
  A redraw uses `prevent(OptionList.OptionHighlighted)`, so it no longer re-selects.
- Saving: a config that could not be read at all (`LoadedConfig.usable` is false) is never overwritten, the app says so once and keeps
  the change for the run. A config that loaded with warnings is copied to `<name>.bak` once, with a toast naming the file. Nothing is
  written unless the watchlist changed, so removing a command-line-only id leaves the file alone.
- Command-line ids go through `getcmd.resolve_ids` (IATA and FAA codes resolve); ids that are not plausible are reported in
  `AppOptions.notices`, which is separate from `config_warnings` and never triggers a backup. `wxbrief` returns the app's return code.
- Adding a station requires a station the bundled database knows (ICAO, or a unique IATA/FAA code). `ZZZZ` is refused with "Unknown
  station" and not saved; an id the database lacks cannot be added until the database is rebuilt, because the app does not verify ids
  with the weather service first. Adding a duplicate says "KDEN is already in the list" and selects it (an id given on the command
  line is saved by `a`, with "(now saved)").
- The Help screen escapes `[`; the flight-category row in the decoded table wraps like the other rows.
- `WXBRIEF_CACHE_DIR` overrides the cache folder (`data/cache.py`, `default_cache_dir`); platformdirs ignores the usual variables on Windows.
- Parked in issue #22: paste screen runs on the event loop and truncates at 60,000 characters; a TAF arrival resets the cached METAR's
  age; global flags before a subcommand are ignored; 60x20 footer and Help height; raw exception text when offline; visibility always
  orange; TAF block label alignment.

**Known limits.** The decoded table wraps values to the width at the last resize. `StationList` is rebuilt on each redraw. No snapshot tests yet.

### S5a (2026-10-31)

The app-independent half of S5, in new files only, so it could land beside S4. Nothing is ticked: S5 is not done.

**What exists.**

- `wxbrief/ui/themes/aviation.py`: the six `Theme` objects (`cockpit-night`, `phosphor-green`, `phosphor-amber`,
  `paper-chart`, `high-contrast-dark`, `high-contrast-light`) and `AVIATION_THEMES`.
- `wxbrief/ui/themes/semantic.py`: `SEMANTIC_DEFAULTS` (the `wx-*` tokens, plus `wx-label` and `wx-warning` which the
  Rich renderer also uses), the `(dark, light)` flight-category and colour-state pairs, `BUILTIN_THEME_NAMES`, and
  `semantic_variables(dark)` returning `fcat-*` and `cs-*` as hex. `wxbrief.ui.themes.THEME_CYCLE` is the order `t` cycles.
- `wxbrief/render/palette.py`: `Palette.from_theme(theme)` does the three-way merge (semantic defaults and fixed colours,
  then `generate()`, then `theme.variables`), resolves `$name` references and `auto N%` itself, and builds a Rich `Theme`
  on `wx.*`, `fcat.*` and `fcat.*.badge`. `all_themes()` lists the built-ins plus the aviation themes.
- `wxbrief decode --theme NAME` (coloured terminal output only; an unknown name exits 2).
- `tests/test_themes.py` and `docs/themes.md`.

**Deviation: Textual does not resolve references in a variables dict.** The S0 check said a default such as
`{"wx-wind": "$secondary"}` resolves through the stylesheet. It does not: `$name` is expanded in CSS text only, so
`color: $wx-wind` fails with "Invalid value ('$secondary')" when the value comes from `get_theme_variable_defaults()` or
`get_css_variables()`. `SEMANTIC_DEFAULTS` therefore stays a table of references that only `Palette` reads, and the app
injects resolved hex.

**What S5b must wire.**

- Register `AVIATION_THEMES` in `WxBriefApp.__init__`.
- Override `get_css_variables()` to return `{**super().get_css_variables(), **Palette.from_theme(self.current_theme).css_variables()}`
  (this supplies every `$wx-*`, `$fcat-*` and `$cs-*`). Do not return `SEMANTIC_DEFAULTS` from
  `get_theme_variable_defaults()`.
- Component classes in `app.tcss`, `RawReport` built from `get_component_rich_style()`, badges and timeline segments using
  `$fcat-*`, `t`/`T` over `THEME_CYCLE`, `ThemePickerScreen`, persistence (skipped when `--theme` was passed), snapshots in
  three themes, and the `--theme` flag on the TUI entry.

### S5b (2026-10-31)

The app half of S5. S5 is ticked: the aviation themes, the palette and the app wiring are all in. Screenshots:
`docs/s5-paper-chart.svg`, `docs/s5-theme-picker.svg`; the guide is `docs/themes.md`.

**Names as built.**

- `WxBriefApp`: registers `AVIATION_THEMES` in `__init__`, starts in `options.view.theme` (an unknown name falls back to
  `textual-dark` with a notice and the file is left alone), `get_css_variables()` adds `Palette.from_theme(...).css_variables()`.
  Bindings `t` (`action_cycle_theme`, over `THEME_CYCLE`) and `T` (`action_theme_picker`) live on the app, not on
  `BriefingScreen`. `AppOptions.theme_from_flag` marks a `--theme` run.
- Theme changes: `theme_changed_signal` calls `_theme_changed`, which redraws the briefing and calls `_settle()`.
  `_settle()` saves the theme unless the picker is open (`_previewing`) or it is the theme already settled; it reads
  `self.theme`, not the signal's value, because the signal is published after a delay and a late message about a preview
  must not be saved. `_save()` writes the watchlist and `[view] theme` together, only what changed, with the existing
  unreadable-config, backup and `--no-config` rules; `_chosen_theme` is only set by a user choice, so a fallback theme or a
  `--theme` run never reaches the file.
- `ui/screens/theme_picker.py`: `ThemePickerScreen(names, current)`, dismisses with the kept name or `None`; highlighting
  sets `app.theme`, Esc restores it. Opening it twice does nothing.
- `ui/style.py`: `ViewPalette(palette)` replaces S4's `Palette`, `_SEMANTIC` and `_BADGES`. It reads the Rich theme of
  `wxbrief.render.palette.Palette` (`style`, `badge`, `raw_text`, and `fresh`, `stale`, `offline`, `muted`).
  `ViewContext.palette` builds it from `app.current_theme`, so the CLI and the TUI share every colour.
- `--theme NAME` is a global flag (`dest=tui_theme`, validated by `_tui_theme` against the built-ins plus the aviation themes;
  an unknown name is an argparse error, exit 2, with the names listed). `decode --theme` is unchanged.
- `app.tcss`: a section at the end for the picker, the highlighted station row (`$primary` tint) and the `.fcat-*`/`.cs-*`
  classes (`background: $fcat-ifr; color: auto`).
- Tests: `tests/test_app_themes.py` (every theme applies and the wind colour in the raw text changes, `t` order, picker
  preview/keep/revert, persistence, flag, unreadable config, `--no-config`, unknown saved theme, CLI/TUI parity in four
  themes, stylesheet classes); `tests/test_snapshots.py` (three themes); `tests/test_themes.py` gained the legibility test.

**Deviations.**

- Raw-text colours are not component classes with `get_component_rich_style()`. `ViewPalette` reads the Rich theme directly:
  one source of truth with the CLI, and no second table in the stylesheet to keep equal to it. The stylesheet carries the
  `$fcat-*` and `$cs-*` classes for widgets Textual draws itself (S6's timeline).
- `wx-*` tokens that come from `SEMANTIC_DEFAULTS` are now moved towards black or white until they reach 4.5:1 against the
  surface and the panel (`Palette._legible`, `MIN_TEXT_CONTRAST`). The scan of all 18 themes found textual-dark's
  wind group (`$secondary`, 1.5:1), solarized and latte tokens and the status-bar counters unreadable. Tokens a theme sets in
  `variables` are untouched. This changes the CLI colours for `decode --theme` in the same way, which is wanted.
- The freshness marks, "stale" and offline text used the ANSI names `green`, `yellow` and `red`, which follow the terminal and
  not the theme (green on a blue highlight, 1.0:1). They now use the VFR colour, `wx.warning` and the IFR colour; the
  secondary text (`dim`) became `wx.time` (`ViewPalette.muted`), and the highlighted station row is a tint of the primary colour
  rather than a solid fill. The station name and the footer key hints are the theme's own colours and were not touched.
- `ansi-dark` and `ansi-light` are unregistered in the app (`Palette.from_theme` cannot resolve `ansi_default`, which crashed the
  redraw when Ctrl+P picked one), so `--theme` accepts exactly what `decode --theme` accepts.
- Settings still shows the theme read-only; S7 makes it editable.

**Snapshots (closes #13).** `pytest-textual-snapshot` 1.1.0 works with Textual 8.2.8: the same picture came out on every run,
under `NO_COLOR=1`, under `pytest -n 3` (the app runs on an injected clock with polling off and the saved
KDEN and EGLL reports; the test unsets `NO_COLOR`, which would otherwise turn every cell grey). The exporter's "Generated with Rich"
comment is removed from the stored SVGs by patching `textual._doc.take_svg_screenshot` in the test. The fallback (comparing
`export_screenshot()` text in-house) was not needed. Stored on Windows only; the other two systems are confirmed by CI. If the
Linux or macOS job shows a diff, the likely causes are font metrics (not in the SVG, which has fixed cell sizes) or the time zone
database; regenerate on one system, compare, and fall back to a text comparison of the screen rather than the SVG. Regenerate with
`pytest tests/test_snapshots.py --snapshot-update` and read the diff.

**For S6.** `$fcat-*` and `$cs-*` are in `get_css_variables()` and the classes `.fcat-vfr` ... `.cs-red` exist; a timeline segment
only needs the class (or `background: $fcat-ifr; color: auto`). `ViewPalette.badge()` is the Rich badge. A new widget that draws
Rich text takes colours from `ctx.palette`, never from ANSI names.

### S6 (2026-10-31)

Screenshots (`--demo`, 120x50 and 60x20): `docs/s6-timeline-textual-dark.svg`, `docs/s6-timeline-paper-chart.svg` (cursor moved to
15:00), `docs/s6-timeline-60x20.svg` (nord, three-hour cells), `docs/s6-grid-140.svg` (grid, three columns). The paper-chart shot
registers `AVIATION_THEMES` itself because the app does not until S5b lands.

**Names as built.**

- `ui/strip.py` (no Textual): `StripCell` (one hour or several merged, worst case wins: `category`, `worst_category`, `becoming`,
  `overlay`, `overlay_category`, `hours`, `slices`), `group_cells(hours, step)`, `merge_hours`, `cell_at`, `mini_cells(hours, now,
  count=12)`, `hour_step(count, width, narrow=)`, `strip_for(taf)` (timeline and hourly summaries).
- `ui/fcat.py`: `CategoryColors` and `category_colors(ctx.palette)`: cell fills taken from the same `Palette` that styles the
  badges, so there is one source. Badges, muted text and the fresh/stale marks all come from `ctx.palette` (`badge`, `muted`,
  `fresh`, `stale`); the widgets hold no colour names of their own.
- `ui/widgets/taf_timeline.py`: `TafTimeline` (focusable; `Left`/`Right`/`Home`/`End`; mouse hover or click moves the cursor;
  posts `TafTimeline.Moved`, which carries the forecast, its timeline, the station and the cell, and is dropped when stale). Rows: tick labels, cells, thin temporary-group row, cursor, legend. Hatched `▒` = becoming
  (background is the prevailing colour, hatch foreground the worst case); `▀` = temporary groups in the worst-case colour. A letter
  (`V M I L`) marks each change of category, so the strip still reads without colour (`NO_COLOR`).
- `ui/widgets/period_detail.py`: `PeriodDetail`, `rows_text`. Shows the cell's window in the time mode, its category and
  worst case, then the prevailing group (and later groups inside a three-hour cell), a `BECMG` under way and each temporary group,
  decoded with `render.plain.element_rows` (new public function; `_period_rows` calls it).
- `ui/widgets/station_card.py` (`StationCard`, `strip_lines`) and `station_grid.py` (`StationGrid`: arrows move, `Enter` or a second
  click opens, columns = width // 38). `ui/screens/station_detail.py`: `StationDetailScreen`, the full-screen detail `Enter` opens
  from the grid (a snapshot taken when it opens; it does not redraw on polls).
- `BriefingScreen`: `layout_mode` (`list`/`grid`), `v` binding `toggle_layout`, the `-grid` class swaps the panes through the
  stylesheet. `DetailPane` gains `#taf-summary`, `#taf-note`, `#timeline`, `#period`, a collapsible `#taf-groups-box` (every group in
  words, the S4 text) and keeps the raw TAF in `RawReport`. `3` focuses the timeline.
- `ViewContext.localize()` and `is_zulu()` (`clock()` is built on them). `AppState.load_demo()`. `AppOptions.demo`.
- Demo: `data/demo.py` (`DEMO_NOW`, `demo_ids()`, `load_demo()`) and `data/demo/<ICAO>.txt` for KDEN, EGLL, ETHB, UUEE, YSSY, RJTT,
  VIDP, SBGR, CYYZ and NZSP, each a METAR and a TAF; `#` lines are comments saying where the text came from.
- CSS: a marked S6 block at the end of `app.tcss`.

**Deviations.**

- The hourly strip needs 2 columns per hour (60 for a 30-hour TAF), so three-hour cells are used when that does not fit the pane as
  well as in `-narrow` (between 90 and about 100 columns the pane is too small for 30 hours).
- `--demo` runs on a fixed clock (`DEMO_NOW`, 2026-10-31 12:00Z) so that every METAR is fresh and every TAF in force. KDEN's TAF and EGLL's reports are
  real; KDEN's METAR is hand-written with a long remarks section; NZSP's TAF is real and its METAR is
  the real one retimed to 11:50Z; the others are hand-written, each decode read against the raw text. NZSP's TAF keeps the six unknown
  words the S2b notes list. `--demo` uses the default config plus command-line view flags, sets `use_config` false (no write). There was no `.gitkeep` in `data/demo/` to remove.
- `v` is not persisted to the config; `--layout grid` picks the starting layout.
- No "now" marker on the strip; the cursor starts on the hour containing the clock.
- The one-second tick (status bar, and a full redraw every 30 s) moved from `WxBriefApp` to `BriefingScreen.on_mount`, so the screen's
  own timer stops with it. `StationCard` has no widget id (cards are found by `icao`), so a station removed and added again cannot
  collide with its dying card. `StationDetailScreen.redraw()` is called from `WxBriefApp._theme_changed`.
- The demo data was corrected after review: ETHB's TAF now says `GRN` where 4000 m and 800 ft is Green, VIDP's TAF uses knots like
  its METAR and `FG` for 800 m, KDEN's METAR lost its precipitation remarks (no precipitation is reported).

**Known limitations** (issue #22): the zone label comes from the first cell only, so it is wrong after the 2026-11-01 DST change
inside one TAF; station-mode ticks for half-hour zones (+5:30) show `%H` only; the card mini strip has no time label; a station
whose TAF has expired shows `no TAF`; every 30 s redraw calls `scroll_visible` on the selected card, which snaps the grid back.

**Tests.** `tests/test_strip.py` (cell computation, real KDEN and EGLL per-hour strings read against the raw TAFs, three-hour cells,
mini strip, step choice), `tests/test_timeline_ui.py` (demo boots offline and writes nothing, every demo report decodes without
unexpected warnings, cursor keys, hover, 60x20 three-hour cells, time modes, no TAF, grid at 60 and 140 columns, grid keys and
detail screen, card text).

**For S7 i18n: new user-visible catalog keys** (all in `locales/en.toml`, `[timeline]`): `timeline.span` (`{start} to {end}`),
`timeline.prevailing` (`Prevailing: {header}`), `timeline.then` (`From {time}: {header}`), `timeline.worst` (`Worst case in this
window:`), `timeline.legend_becoming`, `timeline.legend_temporary`, `timeline.none`, `timeline.no_taf`. Hard-coded English chrome
that S7 should move: `Forecast (TAF)`, `All forecast groups (N)`, `no report` on cards, the `List layout`/`Grid layout` toast, the demo
toast, the Help lines for `v` and `Left/Right`. The tick labels are hours only; the time-zone name comes from `zoneinfo` (or `UTC`).
Also hard-coded and to move in S7: the `v` footer label `List/grid` and `Back`, the `TafTimeline` and `StationGrid` binding descriptions,
the category letters `V M I L` in `LETTERS`, the `UTC` fallback, the `--demo` help text, the `--` placeholder badge, and the
`layout_mode.capitalize()` toast.

### S7 (2026-10-31)

What landed: the es, fr, de and pt catalogs (same keys as `en.toml`, about 730 each), `--lang` for the TUI, `decode` and `get`,
an editable Settings screen, locale-aware numbers (`i18n/numbers.py`) and plurals, every S6 hand-off string moved into the
catalogs, `docs/i18n.md`, and the tests `tests/test_i18n_locales.py` (completeness, numbers, plurals, `--lang`, English leakage on
an RMK-heavy METAR in each language) and `tests/test_app_i18n.py` (live switching, saving, toasts, `--demo` in Spanish).

Deviations from the design:

- **Catalog status.** The four catalogs are `status = "seeded"` (first-pass translations nobody native has read). The design's
  "machine-seeded" note in Settings is not drawn; the status is in `[meta]` and `docs/i18n.md` says so.
- **Settings is partly editable.** Language, units, time and glyph set are rows that Enter cycles, applied at once and saved.
  Theme (`t`/`T`), layout (`v`), poll intervals and the file paths stay read-only lines. The design's "refresh" row is not a row:
  the intervals are `config.toml` values.
- **`decode` and `get` do not read the config.** They default to `en` and take `--lang`; only the TUI uses `[view] lang`. A
  setting made in the interface therefore never changes script output.
- **`--lang` after the subcommand.** `decode` and `get` also accept it (default `SUPPRESS`, so a top-level `--lang` is not
  overwritten with `None`).
- **`--help` is translated** for the TUI flags, in the language named by `--lang` on the command line (English otherwise, the config is not read for `--help`), which reverses the design's "CLI
  `--help` English-only at v1". The `decode` and `get` subparser help, argparse's own headings and config/AWC error text stay
  English.
- **New `[meta]` keys.** `keep_case` (German capitalises nouns, so `lower_first` must not run) and `min_grouping` (Spanish
  groups thousands from five digits). `Translator.lower_first` replaces `phrases.lower_first`.
- **New plural rule `one_below_two`** for French and Portuguese, and `RULE_CATEGORIES` so the completeness test knows which
  forms a rule can return.
- **Bindings are relabelled at runtime.** `ui/bindings.py: bind()` gives each binding the catalog key as its `id` and the English
  text as default; `relabel_tree` rewrites descriptions when the language changes. English is not duplicated in `BINDINGS`.
- **`_save` also persists `lang`, `units`, `time` and `glyph_set`** chosen in Settings (and `theme`, as before), and only
  those: a value that came from a flag is never written.
- **`ui.option.*` keys** (not `ui.settings.units.*`) hold the names of units, time, glyph and layout values; a table named like
  its parent key collides in TOML.

**For S8.** Anything that adds user-visible text adds a key to `en.toml` first, then to all four catalogs (the completeness test
fails otherwise) and regenerates `keys.py`. A new widget with key bindings uses `bind()` and calls `localize(self)` in `on_mount`.
Native-speaker review of the four catalogs is open and would flip their `status` to `complete`.
