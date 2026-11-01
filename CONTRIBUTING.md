# Contributing

Thanks for helping with wxbrief. For anything larger than a typo, open an issue first so the change can be agreed
before you write it. The layout of the code is in [docs/development.md](docs/development.md).

## Setup

Python 3.12 or newer. Windows paths shown; use `.venv/bin/python` elsewhere.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

## Checks

Run these before opening a PR. CI runs the same steps on Windows, Linux and macOS.

```powershell
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m mypy wxbrief
.venv\Scripts\python -m vulture wxbrief scripts --min-confidence 80
.venv\Scripts\python -m pytest
```

More on tests, snapshots and screenshots is in [docs/development.md](docs/development.md).

Changes that only touch Markdown, `docs/` or `LICENSE` skip CI.

## Branches and pull requests

- Work on a branch cut from `main`. Use a short descriptive name.
- Open a PR to `main`. The description says what changed and why (the root cause, for a fix), and how you verified it.
  Link the issue with `Closes #N`.
- PRs merge when CI is green after a review pass.

## Commits

Commit subjects are plain imperative sentences, such as "Add TAF timeline widget". No prefixes or trailers.

## Test reports and goldens

Decoder tests use saved reports in `tests/fixtures/reports/` with a `.golden.json` beside each. Adding one is described
in [docs/decoding.md](docs/decoding.md) under "Adding a fixture". `python -m pytest --update-goldens` rewrites the
goldens from the current decoder, so read `git diff` against the raw report before committing; a golden only counts as
a test once someone has checked it.

## Snapshots

`tests/test_snapshots.py` compares screenshots of the briefing screen. After a deliberate interface change, run
`python -m pytest tests/test_snapshots.py --snapshot-update` and read each changed SVG before committing it.

## Versions and the changelog

Versions follow ZeroVer: `0.MINOR.PATCH`, with the major staying 0. `__version__` in `wxbrief/__init__.py` is edited by
hand: minor for features, patch for fixes. Release tags are `v0.x.y` and match `__version__`.

`CHANGELOG.md` follows [Common Changelog](https://common-changelog.org/). Add an entry only for user-visible changes,
as one imperative line with a `(#PR)` reference under Changed, Added, Removed or Fixed, in that order. Docs, dotfiles,
dev-only dependency bumps and style edits get none. The `0.1.0` entry is already written, so a user-visible change after it
goes in the section of the release it will ship in.

## License

By contributing you agree that your work is released under the [MIT License](LICENSE).
