# Releasing wxbrief

Versions are ZeroVer (`0.MINOR.PATCH`), edited by hand in `wxbrief/__init__.py`. A release is a tag `v0.x.y` on
`main`. Pushing the tag is the only thing that starts `release.yml`; branches and pull requests never do. Tag only
when the owner says so.

## Cut a release

1. Set `__version__` in `wxbrief/__init__.py` (minor for features, patch for fixes).
2. Add the `## 0.x.y - YYYY-MM-DD` section to `CHANGELOG.md` (Common Changelog; see `CLAUDE.md`). Commit both in a PR
   and merge it once CI is green.
3. Optionally build and test the Windows binary locally: `scripts\build_exe.ps1` (see below).
4. On `main` at the merged commit: `git tag v0.x.y` then `git push origin v0.x.y`.
5. Watch the run in the Actions tab. When it is green, do the manual smoke checklist on the published files.

If the run fails before the `publish` job, nothing was released: fix the cause, delete the tag
(`git push origin :refs/tags/v0.x.y`, `git tag -d v0.x.y`), and tag again. If a release was created and is bad, mark it
as a draft or delete it and fix forward with a patch version.

## What `release.yml` does

| Job | What it does |
| --- | --- |
| `verify` | The tag must be `v0.MINOR.PATCH`, equal `v` plus `__version__`, and `CHANGELOG.md` must have a `## <version> - date` section with entries. That section becomes the release notes. |
| `dist` | Builds the wheel and sdist with `python -m build`, installs the wheel in a clean venv and runs `--version` and `--selftest`. |
| `binary` | Builds one-file PyInstaller binaries from `wxbrief.spec` and runs `--version` and `--selftest` on each: Windows x86_64 (`.exe`), Linux x86_64 and arm64 (built in `python:3.12-bullseye` for an old glibc), macOS arm64 and x86_64. Linux and macOS files are `.tar.gz`. |
| `publish` | Collects every file, writes `SHA256SUMS`, attests build provenance for each file, and creates the GitHub release for the tag with the changelog section as its notes. Only this job has write permissions. |

Nothing is uploaded to PyPI. There is no self-updater.

To check a download: `sha256sum -c SHA256SUMS --ignore-missing`, and
`gh attestation verify <file> --repo WPTK/wxbrief`.

## Build the Windows binary locally

```powershell
.venv\Scripts\python -m pip install -e ".[dev]"
scripts\build_exe.ps1
```

It runs PyInstaller on `wxbrief.spec` (output in `dist\`, work files in `.pyi-build\`, both gitignored), then runs
`dist\wxbrief.exe --selftest` and prints the SHA-256.

`--selftest` is hidden. It checks that all five catalogs load, the station database opens with a valid time zone, `app.tcss`
is bundled, a METAR and a TAF decode and render, and the demo reports load. It prints one line per check and exits 0 only
if all pass; it never uses the network, config or cache.

## Manual smoke checklist

On each platform you can reach, with the downloaded file (not a dev install):

- [ ] `wxbrief --version` prints the tag's version.
- [ ] `wxbrief --selftest` exits 0 with five `ok` lines.
- [ ] `wxbrief decode --plain "METAR KDEN 131453Z 06007KT 3/4SM BR OVC003 09/08 A3001"` shows LIFR.
- [ ] `wxbrief decode --lang de ...` prints German with no English labels.
- [ ] `wxbrief --demo` opens the TUI offline, shows ten stations, `t` changes the colorway, `v` switches layouts, `?`
      opens help, `q` quits and the terminal is restored.
- [ ] `wxbrief KDEN EGLL` loads live data (network needed) and the status bar shows the poll budget.
- [ ] On Windows, a first run from a plain folder works (no Python installed, no admin rights).
- [ ] `SHA256SUMS` matches the downloaded files, and the release notes equal the changelog section.
- [ ] `pip install wxbrief-<version>-py3-none-any.whl` in a fresh venv, then `wxbrief --version`.

## The stations canary

`stations-canary.yml` runs weekly (Monday 06:17 UTC) and on demand. It runs `scripts/check_stations_source.py`, which
downloads the AWC station cache that `scripts/build_stations.py` reads and fails if it is unreachable, unparsable, has no
usable rows, or its usable-row count differs from the bundled `stations.json.gz` by more than 2 %. On failure the workflow
opens an issue titled "Station database source check failed" (labelled `data`) or comments on the open one. To resolve a
drift report, run `python scripts/build_stations.py`, review the change and commit it. The workflow needs no secrets and
changes nothing in the repository.
