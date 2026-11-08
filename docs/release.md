# Releasing wxbrief

Versions are ZeroVer (`0.MINOR.PATCH`), edited by hand in `wxbrief/__init__.py`. A release is a tag `v0.x.y` on
`main`. Pushing the tag is the only thing that starts `release.yml`; branches and pull requests never do. Tag only
when the owner says so.

## Cut a release

1. Set `__version__` in `wxbrief/__init__.py` (minor for features, patch for fixes).
2. Add the `## 0.x.y - YYYY-MM-DD` section to `CHANGELOG.md` (Common Changelog; see [CONTRIBUTING.md](../CONTRIBUTING.md)). Commit both in a PR
   and merge it once CI is green.
3. When a dependency moved, regenerate `.github/release-constraints.txt` (the command is at the top of the file) and commit it with the version.
4. Optionally build and test the Windows binary locally: `scripts\build_exe.ps1` (see below).
5. On `main` at the merged commit: `git tag v0.x.y` then `git push origin v0.x.y`.
6. Watch the run in the Actions tab. When it is green, do the manual smoke checklist on the published files.

If the run fails before the `publish` job, nothing was released: fix the cause, delete the tag
(`git push origin :refs/tags/v0.x.y`, `git tag -d v0.x.y`), and tag again. If a release was created and is bad, mark it
as a draft or delete it and fix forward with a patch version.

## What `release.yml` does

| Job | What it does |
| --- | --- |
| `verify` | The tagged commit must be on `main` and have a successful `ci.yml` run (so a tag on a commit CI skipped or failed is refused). The tag must be `v0.MINOR.PATCH`, equal `v` plus `__version__`, and `CHANGELOG.md` must have a `## <version> - date` section with entries. That section becomes the release notes. |
| `dist` | Builds the wheel and sdist (build tools and dependencies pinned by `.github/release-constraints.txt`) with `python -m build`, installs the wheel in a clean venv and runs `--version` and `--selftest`. |
| `binary` | Calls `binaries.yml` (below). |
| `check` | Calls the shared `check-release.yml`: the build produced exactly the seven expected files (wheel, sdist and the five binaries), and the tag still points at the built commit. Runs before anything is attested. |
| `attest` | Attests build provenance for each file. It runs in this workflow, not in the shared one, because the certificate names the workflow that ran it and `gh attestation verify --signer-workflow` expects `release.yml`. |
| `publish` | Calls the shared `publish-release.yml`: checks the file set again, writes `SHA256SUMS`, confirms the tag still points at the built commit and creates the GitHub release (as a draft, uploads the files, then publishes it) with the changelog section as its notes. Only this job has write permissions. |
| `pypi` | After the release exists and the `pypi` environment is approved, uploads the wheel and sdist from the `dist` job (not rebuilt) to PyPI by trusted publishing, in the `pypi` environment. Only this job has `id-token: write` besides `attest`. |

`binaries.yml` calls the shared `build-binaries.yml` (from [WPTK/release-workflows](https://github.com/WPTK/release-workflows),
also used by the other WPTK apps). It builds one-file PyInstaller binaries from `wxbrief.spec` with the versions pinned
in `.github/release-constraints.txt`, one per platform on its own kind of runner, and runs `--version` and `--selftest`
on each: Windows x86_64 (`.exe`), Linux x86_64 and arm64 (built in `python:3.12-bullseye`, pinned by digest, and checked
to need no glibc symbol newer than 2.31), macOS arm64 and x86_64. Files are named `wxbrief-<version>-<os>-<arch>`;
Linux and macOS files are `.tar.gz`, so the executable bit survives. It also runs by hand (Actions tab, Run workflow)
and on pull requests that touch the build (`wxbrief.spec`, `pyproject.toml`, the package, the pins), which is how the
build is proved without a release. It publishes nothing and has no secrets.

`post-release.yml` runs after a release is published and by hand against an existing tag (input `tag`). Its `published`
job calls the shared `verify-published.yml`: it downloads every published file from its public URL, checks the file
set, `SHA256SUMS` and each build attestation (signed by `release.yml` at the tag), then runs each of the five binaries
on a runner of its own kind with nothing of ours installed (`--version`, `--selftest`). Its `run` job then drives the
published Linux and Windows executables through `scripts/post_release_check.py`.

The shared workflows are pinned by commit SHA in `binaries.yml`, `release.yml` and `post-release.yml`; to take a change,
move the SHA in all three together. All third-party actions are pinned to a commit SHA too.

`publish.yml` (Actions tab, run by hand, input `ref`) builds a ref, runs `twine check`, fails unless the wheel version
equals `__version__`, and uploads to PyPI through the same `pypi` environment. Use it only to publish a ref that
`release.yml` did not. PyPI refuses a second upload of the same version. There is no self-updater.

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
is bundled, a METAR and a TAF decode and render, the demo reports load, the real app mounts headless on them and the live-feed client is built. It prints one line per check and exits 0 only
if all pass; it never uses the network, config or cache.

## Manual smoke checklist

On each platform you can reach, with the downloaded file (not a dev install):

- [ ] `wxbrief --version` prints the tag's version.
- [ ] `wxbrief --selftest` exits 0 with eight `ok` lines.
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

## The feed check

`feed-check.yml` runs daily (07:43 UTC) and on demand, never in pull request CI. It runs `scripts/check_feeds.py`, which
makes one request each to the AWC `metar`, `taf` and `stationinfo` endpoints for five large airports and passes the
answers through the app's own client, row parsers and decoders. A format change (a body that is not a JSON list, rows
the parsers drop, a report the decoder fails on) opens an issue titled "Live feed check failed" (labelled `data`) at
once, or comments on the open one. A feed that is down, rate limited or empty fails the run with its own `DOWN:` line
but raises an issue only when the two runs before it failed too.
