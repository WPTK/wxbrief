# wxbrief

Terminal METAR/TAF briefing with colorways and plain-language translation.

wxbrief fetches METAR/SPECI observations and TAF forecasts from aviationweather.gov, decodes them with its own
parser, and shows them in a Textual terminal UI with switchable colorways and a plain-language translation
(English complete; Spanish, French, German and Portuguese seeded).

## Status

Work in progress. Nothing is released yet, and the current scaffold only answers `--version`. The design and the
build schedule live in [docs/plan.md](docs/plan.md).

## Development

Python 3.12 or newer. Windows paths shown; use `.venv/bin/python` elsewhere.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m wxbrief --version
```

Lint, type-check and test with `python -m ruff check .`, `python -m mypy wxbrief` and `python -m pytest`.

## License

MIT, see [LICENSE](LICENSE).
