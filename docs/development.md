# Development

Setup, checks, tests, snapshots and screenshots. The workflow for changes is in
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
| `scripts/` | `gen_keys.py`, `build_stations.py`, `make_screenshots.py`, `uat_screenshots.py`, `make_demo_gif.py` |
| `tests/` | the suite; `fixtures/` saved reports and AWC batches; `uat/` user journeys |

## Tests

- Decoder goldens: `tests/fixtures/reports/**/*.golden.json`. `pytest --update-goldens` rewrites them from the current
  decoder, so read `git diff` against the raw report first. See [decoding.md](decoding.md).
- Interface tests run the real app in Textual's pilot, with polling off and the network blocked. `--demo` gives a fixed
  clock and ten stations to test against.
- `tests/uat/test_journeys.py` walks complete journeys key by key: reading and copying a station, the dialogs, `g` `u`
  `z`, the grid, a 60x20 terminal, and the timeline markers without colour.
- A test that fails is run alone before it is called a flake.
- A runaway test ends the run instead of exhausting the machine. pytest-timeout stops a test after 120 s
  (`pyproject.toml`), and a watcher thread in `tests/conftest.py` ends a process over `WXBRIEF_TEST_RSS_MB` (2048) of
  resident memory. Both are Python threads, so neither runs while a test holds the GIL inside C code (a regex that
  backtracks for ever, one allocation of many GiB). Two backstops do not depend on Python code running: a `faulthandler`
  timer exits the process with a stack dump after `WXBRIEF_TEST_HARD_TIMEOUT` seconds (300), and on Windows a job object
  makes the kernel refuse a process more than `WXBRIEF_TEST_COMMIT_MB` (4096) of memory, so the test gets a
  `MemoryError`. Importing the test modules (collection) has its own `faulthandler` timer, `WXBRIEF_TEST_COLLECT_TIMEOUT`
  (300 s), and the memory watcher starts at configure time, so collection is inside the memory limits too. Under `-n`,
  xdist reports the crashed worker's test. `0` turns a time or commit backstop off, for a debugger session.
  `tests/test_limits.py` checks each limit.

## UAT suite

`tests/uat/test_uat.py` drives the real app on `--demo` data at the sizes users have: 120x30 (the main case), 200x50,
100x50, 280x70, the 80x24 floor, and 60x20 and 60x16 (the smallest the app draws; below 60x16 it shows a notice). The journeys live in `tests/uat/journeys.py` (list, grid,
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

## Real-terminal kit

`tests/uat_kit/` drives any terminal program through a real pseudo-terminal using Microsoft's `tui-test` (ConPTY on
Windows, a pty elsewhere; pinned in the dev extra). It imports nothing from wxbrief, so other projects can copy the
folder. `Terminal(argv, cols, rows, env=...)` gives blocking `send_keys`, `click(col, row)` (SGR pointer motion, press,
release), `click_text`, `resize`, `wait_for(predicate)` (fails with a screen dump), `settle`, `screen_text` and
`wait_exit`; the program and its children are killed by PID on close and at interpreter exit, and its config, cache and
working directory are a scratch directory with a dead proxy. `tests/uat_kit/test_kit.py` tests the kit against a tiny
echo program. Set `PYTHONUTF8=1` on Windows when printing screen text.

## Real-terminal suite

`tests/pty/` runs the real program (`python -m wxbrief --demo`, or the built exe when `WXBRIEF_PTY_EXE` is set) in a
pseudo-terminal through `tests/uat_kit`, with the bytes a terminal sends, and asserts on the rendered screen. It has
journeys (list and grid click, selection that sticks, keys 1/2/3, dialogs, resize, exit code), an input inventory
(`test_pty_inventory.py`: every `bind()` key, every clickable widget and every key in the README table must have a
scenario, or the meta-tests fail), a state matrix (`test_pty_matrix.py`: five states, four sizes, seven screens, with
rules that no screen contradicts itself) and terminal compatibility (`test_pty_compat.py`: `NO_COLOR`, `TERM` and
`COLORTERM` variants, ASCII glyphs, minimum size, clean exit). The suite takes about 2.5 minutes with `-n 4`; it is
marked `pty` and skipped with a reason when tui-test is missing. `WXBRIEF_PTY_SRC` runs another source tree.
Each pty test has a 90 s limit and each call into tui-test a 30 s limit, so a hang fails with a message (waits fail with a
screen dump) instead of stalling CI. The suite adds about two to two and a half minutes per OS with `-n 4`. The kit
gives the child empty `COLUMNS` and `LINES`: under pytest on Linux the native layer otherwise passes the child
`COLUMNS=80 LINES=24` from its C environment, the app lays out for 80x24 in a 120x30 terminal and every start waits
in vain for the station list. #235 (focus reporting left on at exit) shows on Windows only; Linux and macOS exit clean.

Severity: a dead advertised key, a click that does not stick and a screen that contradicts itself are P1.
Not covered: Windows Terminal rendering, sixel, real tmux or SSH sessions, a partial-failure feed (the AWC base URL
cannot be overridden).

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
.venv\Scripts\python scripts\make_screenshots.py              # SVGs into .shots/ (gitignored)
python scripts\make_screenshots.py --png-only                 # .shots/*.svg to docs/img/*.png
```

The first step renders five 120x30 screens from `--demo` with Textual's exporter. The second converts them with
Playwright and Chromium (`pip install playwright`, `playwright install chromium`), which are not project dependencies
and may live in a different Python from the venv. The README and `themes.md` use the PNGs because GitHub does not load
the SVG's web font. The demo clock is fixed, so the pictures change only when the interface does. Commit them with the
change that altered them, and look at each one first. The scripts clear `NO_COLOR` for their own process and fail on a
picture with no chromatic colour. The app itself honours `NO_COLOR` (monochrome output, tested in
`tests/test_screenshot_colour.py`).

The animated demo at the top of the README is recorded the same way, from the real app on `--demo`:

```powershell
python scripts\make_demo_gif.py
```

It writes `docs/img/demo.gif`. It needs Pillow and a monospaced TrueType font (see the script), and re-record it after
an interface change that shows in it.

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
