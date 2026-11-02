"""Check an installed copy of wxbrief (CI packaging gate).

Run it with the Python of a clean virtual environment that has the wheel or the sdist installed, from any directory
except the source checkout:

    <venv>/bin/python -I scripts/ci_check_install.py

It proves the installed copy, not the source tree: the package is imported from site-packages, the package data is read
through importlib.resources, and the command-line entry point and `python -m wxbrief` run.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
import sysconfig
from importlib import resources
from pathlib import Path

METAR = "METAR KDEN 131453Z 06007KT 3/4SM BR OVC003 09/08 A3001"
LOCALES = ("de", "en", "es", "fr", "pt")
THEME_MODULES = ("aviation.py", "semantic.py")

failures: list[str] = []


def check(ok: bool, what: str) -> None:
    print(("ok    " if ok else "FAIL  ") + what)
    if not ok:
        failures.append(what)


def run(argv: list[str], what: str, *, want: str | None = None, timeout: int = 120) -> None:
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
    out = proc.stdout + proc.stderr
    ok = proc.returncode == 0 and (want is None or want in out)
    check(ok, f"{what} (exit {proc.returncode})")
    if not ok:
        print(out[-2000:])


def main() -> int:
    import wxbrief

    where = Path(wxbrief.__file__).resolve()
    check("site-packages" in where.parts, f"wxbrief is imported from site-packages ({where})")
    version = wxbrief.__version__

    scripts_dir = Path(sysconfig.get_path("scripts"))
    exe = next((p for p in (scripts_dir / "wxbrief.exe", scripts_dir / "wxbrief") if p.is_file()), None)
    check(exe is not None, f"entry point wxbrief exists in {scripts_dir}")
    if exe is not None:
        run([str(exe), "--version"], "wxbrief --version", want=version)
        run([str(exe), "--help"], "wxbrief --help", want="usage: wxbrief")
        run([str(exe), "decode", "--plain", METAR], "wxbrief decode", want="Flight category")
        run([str(exe), "--selftest"], "wxbrief --selftest")
    run([sys.executable, "-m", "wxbrief", "--version"], "python -m wxbrief --version", want=version)

    # Package data, read from the installed copy through importlib.resources.
    root = resources.files("wxbrief")
    locales = root.joinpath("i18n", "locales")
    for code in LOCALES:
        f = locales.joinpath(f"{code}.toml")
        check(f.is_file() and len(f.read_bytes()) > 1000, f"locale {code}.toml is present and not empty")
    check(root.joinpath("ui", "app.tcss").is_file(), "ui/app.tcss is present")
    db = root.joinpath("data", "stations.json.gz")
    check(db.is_file() and len(db.read_bytes()) > 100_000, "data/stations.json.gz is present and plausible in size")
    demo = [p.name for p in root.joinpath("data", "demo").iterdir() if p.name.endswith(".txt")]
    check(len(demo) >= 10, f"{len(demo)} demo reports are present (ten stations expected)")
    themes = root.joinpath("ui", "themes")
    for name in THEME_MODULES:
        check(themes.joinpath(name).is_file(), f"theme module ui/themes/{name} is present")
    importlib.import_module("wxbrief.ui.themes")
    check(True, "wxbrief.ui.themes imports")

    print()
    if failures:
        print(f"{len(failures)} check(s) failed:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("installed copy is complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
