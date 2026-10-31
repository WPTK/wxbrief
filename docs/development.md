# Development

Setup, checks, tests, snapshots and screenshots. The design is in [plan.md](plan.md); the workflow for changes is in
[../CONTRIBUTING.md](../CONTRIBUTING.md). Windows paths shown; use `.venv/bin/python` elsewhere.

## Setup

Python 3.12 or newer.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

## Checks

CI runs these on Windows, Linux and macOS. Run them before pushing.

```powershell
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m vulture wxbrief scripts --min-confidence 80
.venv\Scripts\python -m mypy wxbrief
.venv\Scripts\python -m pytest -n auto
```

Changes that only touch Markdown, `docs/` or `LICENSE` skip CI.

## Layout

| Folder | Holds |
|---|---|
| `wxbrief/decode/` | tokenizer, model, group decoders, remarks, TAF timeline, flight category (mypy strict) |
| `wxbrief/i18n/` | translator, key constants, plurals, numbers; `locales/*.toml` catalogs (mypy strict) |
| `wxbrief/data/` | AWC client, poll scheduler, disk cache, station database, the `--demo` reports |
| `wxbrief/render/` | phrases, plain, Rich, Discord and JSON output, the CLI palette |
| `wxbrief/ui/` | the Textual interface: `app.tcss`, glyph sets, themes, screens, widgets |
| `scripts/` | `gen_keys.py`, `build_stations.py`, `make_screenshots.py` |
| `tests/` | the suite; `fixtures/` saved reports and AWC batches; `uat/` user journeys |

## Tests

- Decoder goldens: `tests/fixtures/reports/**/*.golden.json`. `pytest --update-goldens` rewrites them from the current
  decoder, so read `git diff` against the raw report first. See [decoding.md](decoding.md).
- Interface tests run the real app in Textual's pilot, with polling off and the network blocked. `--demo` gives a fixed
  clock and ten stations to test against.
- `tests/uat/test_journeys.py` walks complete journeys key by key: reading and copying a station, the dialogs, `g` `u`
  `z`, the grid, a 60x20 terminal, and the timeline markers without colour.
- A test that fails is run alone before it is called a flake.

## UAT suite

`tests/uat/test_uat.py` drives the real app on `--demo` data at the sizes users have: 120x30 (the main case), 200x50,
100x50, 280x70, the 80x24 floor, and 60x20, 50x14 and 40x12. The journeys live in `tests/uat/journeys.py` (list, grid,
station detail, paste, add station, help, themes, settings, copy keys, quit, and a live resize 120x30 to 100x50 to
200x50 to 80x24 and back); `harness.py` holds the app setup and screen reading. Each journey asserts what is on screen
and where focus is, and any saved config goes to a temp directory. Waits poll with a deadline, never a fixed sleep.

```powershell
.venv\Scripts\python -m pytest tests/uat
.venv\Scripts\python -m pytest tests/uat -m "not slow"    # skip the theme cycle and the resize journey
```

`tests/uat/test_known_bugs.py` holds defects the journeys found as `xfail(strict=True)` tests named after their GitHub
issue. When a fix lands the test XPASSes and fails the run: remove its `xfail` mark and keep it as a regression test.

`scripts/uat_screenshots.py OUT_DIR` runs the same journeys and writes each state as SVG and PNG (the PNGs need
Playwright with Chromium; `--no-png` and `--png-only` split the two steps). The folder is for looking at, so pass one
outside the checkout.

## Snapshots

`tests/test_snapshots.py` compares screenshots of the briefing screen in three themes
(pytest-textual-snapshot, pinned to 1.1.* because the test patches a private Textual function). When a deliberate
change alters them:

```powershell
.venv\Scripts\python -m pytest tests/test_snapshots.py --snapshot-update
```

then read each changed SVG (open it, or diff the text) before committing. A snapshot is a test only once someone has
looked at it.

## Translations

User-visible text lives in `wxbrief/i18n/locales/en.toml`. A new key goes into `en.toml` first, then into the four other
catalogs (a completeness test fails otherwise), and `python scripts/gen_keys.py` regenerates `wxbrief/i18n/keys.py`.
A key binding uses `bind()` from `wxbrief/ui/bindings.py` so its footer label comes from the catalog. See
[i18n.md](i18n.md).

## Screenshots

```powershell
.venv\Scripts\python scripts\make_screenshots.py
```

writes `docs/img/*.svg` from `--demo` with Textual's exporter. The demo clock is fixed, so the pictures change only
when the interface does. Commit them with the change that altered them.

## Station database

`wxbrief/data/stations.json.gz` is built by `scripts/build_stations.py` (needs `timezonefinder`, a dev-only
dependency). Positions keep the full precision of the AWC list. The time zones come from timezone-boundary-builder
data under the ODbL; the attribution is in the README and must stay with any release. The script prints the two
facts to record here after a rebuild. The current file was built on 2026-10-31 from that day's AWC cache with
timezonefinder 9.2.0. `get()` returns `None` for the eight IATA codes two stations share (GWD, ISU, CEM, PTZ, GYA, VTZ, TRK,
SRG); `tests/test_data_files.py` pins the list, so a rebuild that changes it fails there.

## Versions and releases

ZeroVer: `__version__` in `wxbrief/__init__.py` is edited by hand, `0.MINOR.PATCH`. `CHANGELOG.md` follows Common
Changelog. Tags are `v0.x.y` and equal `__version__`; the owner decides when to tag.
