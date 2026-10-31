# Contributing

Thanks for helping with wxbrief. The architecture and the build schedule are in [docs/plan.md](docs/plan.md); read it
before starting anything larger than a typo.

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

Changes that only touch Markdown, `docs/` or `LICENSE` skip CI.

## Branches and pull requests

- Work on a branch cut from `main`. Milestone work is named `s<N>-<slug>` (for example `s3-data-layer`); other changes
  can use a short descriptive name.
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

## Versions and the changelog

Versions follow ZeroVer: `0.MINOR.PATCH`, with the major staying 0. `__version__` in `wxbrief/__init__.py` is edited by
hand: minor for features, patch for fixes. Release tags are `v0.x.y` and match `__version__`.

`CHANGELOG.md` follows [Common Changelog](https://common-changelog.org/). Add an entry only for user-visible changes,
as one imperative line with a `(#PR)` reference under Changed, Added, Removed or Fixed, in that order. Docs, dotfiles,
dev-only dependency bumps and style edits get none. The first `0.1.0` entry is written when that release is prepared,
so leave `CHANGELOG.md` alone until then.

## License

By contributing you agree that your work is released under the [MIT License](LICENSE).
