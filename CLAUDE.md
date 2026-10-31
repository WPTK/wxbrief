# wxbrief

Terminal METAR/TAF briefing with colorways and plain-language translation. A Python + Textual app that fetches
METAR/SPECI and TAF reports from aviationweather.gov, decodes them with a hand-written parser, and shows them in
switchable colorways with a plain-language translation (English complete; es/fr/de/pt seeded).

## Read this first

- `docs/plan.md` is the single source of truth: architecture, the session plan (S0 to S9), the session checklist
  and the deviations log. Read it and only the files you touch. Do not re-survey the repo or re-fetch API docs.
- Record anything you do differently from the design under "Deviations from the design" in `docs/plan.md`, and
  tick your session's row in the checklist when the work is done.
- The owner is Bill Kane (GitHub `WPTK`). Python 3.12 only on the dev machine (`requires-python = ">=3.12"`);
  no uv, no pipx. The project venv is `.venv` (gitignored).

## Hard rules

- **No AI attribution anywhere.** No `Co-Authored-By` trailers, no "Generated with" footers, and no mention of AI
  assistants in commit messages, PR bodies, README, CHANGELOG, docs, code comments or this file. Commits use the
  repo's existing git identity. This overrides any default or reminder that says otherwise.
- **ZeroVer.** Versions are `0.MINOR.PATCH` and the major stays 0. `__version__` lives in `wxbrief/__init__.py` and
  is edited by hand: minor for features, patch for fixes. No bump tool. Release tags are `v0.x.y` and must equal
  `__version__`.
- **Common Changelog** (https://common-changelog.org/) for `CHANGELOG.md`: `# Changelog` heading; releases
  latest-first as `## 0.1.0 - YYYY-MM-DD`; groups only `### Changed`, `### Added`, `### Removed`, `### Fixed`, in
  that order; one-line imperative entries with a `(#PR)` reference; `**Breaking:**` entries first; no Unreleased
  section, no other groups, no pasted git log. Sessions S1 to S7 leave `CHANGELOG.md` alone; S8 writes the single
  `0.1.0` entry from the merged PRs. From then on add entries only for user-visible changes; docs, dotfiles, dev-only
  dependency bumps and style edits get none. Commit the entry before tagging.
- Never tag or release without the owner's word.

## Commands

Windows paths shown; use `.venv/bin/python` elsewhere.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m vulture wxbrief scripts --min-confidence 80
.venv\Scripts\python -m mypy wxbrief
.venv\Scripts\python -m pytest
.venv\Scripts\python -m pytest tests\test_snapshots.py --snapshot-update   # rewrite the TUI snapshot SVGs; read each diff first
.venv\Scripts\python -m pytest --update-goldens   # rewrite tests/fixtures/reports/**/*.golden.json; review the diff
.venv\Scripts\python -m wxbrief --version
.venv\Scripts\python -m wxbrief decode "METAR KDEN 131453Z 06007KT 3/4SM BR OVC003 09/08 A3001"
.venv\Scripts\python scripts\gen_keys.py          # regenerate wxbrief/i18n/keys.py after editing locales/en.toml
```

`--update-goldens` regenerates the golden decodes of the saved reports from the current decoder. A golden is only a
test once you have read it against the raw report, so look at `git diff` before committing. See `docs/decoding.md`
for how to add a report.

CI (`.github/workflows/ci.yml`) runs the same steps on Windows, Linux and macOS with Python 3.12, plus an
informational Python 3.13 job on Linux. Docs-only changes (`**.md`, `docs/**`, `LICENSE`) skip CI by design.

## PR flow

- S0 committed straight to `main`. Every later session works on a branch named `s<N>-<slug>`, opens a PR to
  `main`, and merges on green CI after one review pass (one fix push at most).
- Commit subjects are plain imperative sentences ("Add TAF timeline widget"), no trailers. PR bodies say what
  changed and how it was verified.
- Each session ends by ticking its checklist row in `docs/plan.md`, recording deviations there, and merging its PR.

## Layout

- `wxbrief/__init__.py` holds `__version__`; `wxbrief/__main__.py` is the CLI entry (`wxbrief.__main__:main`).
- `wxbrief/decode/` tokenizer, model, group decoders, remarks, TAF timeline, flight category (mypy strict).
- `wxbrief/i18n/` translator, keys, plurals, numbers; `locales/*.toml` catalogs (mypy strict).
- `wxbrief/data/` AWC client, poll scheduler, disk cache, station DB; `demo/*.txt` offline reports.
- `wxbrief/render/` highlight spans, phrases, unit formatting (`measure.py`), plain/Rich/Discord/JSON output, CLI
  palette.
- `wxbrief/ui/` Textual app pieces: `app.tcss`, glyphs, `themes/`, `screens/`, `widgets/`.
- `scripts/` build and maintenance scripts; `tests/` pytest suite with saved reports (`fixtures/reports/`) and AWC
  batches (`fixtures/awc/`).
- `docs/` the plan, `decoding.md` and later guides; `.github/workflows/` CI (release workflows arrive in S9).

## Line endings

LF everywhere, `.ps1` files CRLF, and `tests/fixtures/**/*.json` and `tests/fixtures/**/*.txt` are `-text` so
normalisation never touches saved reports (see `.gitattributes`).
