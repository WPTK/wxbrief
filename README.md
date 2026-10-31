# wxbrief

[![CI](https://github.com/WPTK/wxbrief/actions/workflows/ci.yml/badge.svg)](https://github.com/WPTK/wxbrief/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Terminal METAR/TAF briefing with colorways and plain-language translation.

wxbrief is meant to fetch METAR/SPECI observations and TAF forecasts from aviationweather.gov, decode them with its
own parser, and show them in a Textual terminal UI with switchable colorways and a plain-language translation
(English complete; Spanish, French, German and Portuguese seeded). Only the decoder is usable today; see Status.

## Status

Work in progress. Nothing is released yet, and there are no packaged downloads.

| Part | State |
|---|---|
| METAR/SPECI decoder (`python -m wxbrief decode`) | Works, with plain and Rich (colour) text output |
| TAF decoding, JSON and Discord output | In progress |
| Fetching reports from aviationweather.gov | In progress |
| Terminal UI, colorways, other languages | Not started |

The design and the build schedule live in [docs/plan.md](docs/plan.md).

## Install from source

Python 3.12 or newer. Windows paths shown; use `.venv/bin/python` elsewhere.

```powershell
git clone https://github.com/WPTK/wxbrief.git
cd wxbrief
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m wxbrief --version
```

## Usage

Decode a METAR or SPECI given on the command line. Quote each report:

```powershell
.venv\Scripts\python -m wxbrief decode "METAR KDEN 131453Z 06007KT 3/4SM BR OVC003 09/08 A3001"
```

Output is coloured on a terminal. Add `--plain` for text without colour (this is automatic when output is piped).
Reports can also be piped in on stdin, one per line:

```powershell
Get-Content reports.txt | .venv\Scripts\python -m wxbrief decode --plain
```

Other options: `--units us|metric|mixed` picks the unit system shown first, and `--date YYYY-MM-DD` sets the date used
to resolve the day of the month in the report's timestamp (default: today, UTC). Run `decode --help` for details.

## Development

```powershell
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m mypy wxbrief
.venv\Scripts\python -m vulture wxbrief scripts --min-confidence 80
.venv\Scripts\python -m pytest
```

CI runs the same checks on Windows, Linux and macOS. See [CONTRIBUTING.md](CONTRIBUTING.md) for the workflow.

## Project layout

- [docs/plan.md](docs/plan.md): architecture, session plan, checklist and deviations from the design.
- [docs/decoding.md](docs/decoding.md): how the decoder works and how to add a test report.
- `wxbrief/`: the package (`decode/`, `render/`, `i18n/`, and later `data/` and `ui/`); `tests/`: the test suite and
  saved reports.

## License

MIT, see [LICENSE](LICENSE).
