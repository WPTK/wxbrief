"""Run a PUBLISHED wxbrief executable the way a user would (post-release gate, issue #212).

    python scripts/post_release_check.py <path-to-exe> <version>

Checks `--version`, `--help`, `--selftest` and `decode`, then starts `--demo` in a real pseudo-terminal (ConPTY on
Windows), waits for a station to be drawn, presses q and requires exit code 0. Needs `tui-test`, `psutil` and `pyte`;
the executable is run from an empty directory with no Python of the checkout involved.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

METAR = "METAR KDEN 131453Z 06007KT 3/4SM BR OVC003 09/08 A3001"
failures: list[str] = []


def check(ok: bool, what: str, detail: str = "") -> None:
    print(("ok    " if ok else "FAIL  ") + what)
    if not ok:
        failures.append(what)
        print(detail[-2000:])


def run(exe: str, cwd: Path, *argv: str) -> tuple[int, str]:
    proc = subprocess.run(
        [exe, *argv], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180
    )
    return proc.returncode, proc.stdout + proc.stderr


def main() -> int:
    exe, version = str(Path(sys.argv[1]).resolve()), sys.argv[2]
    empty = Path(tempfile.mkdtemp(prefix="post-release-"))

    code, out = run(exe, empty, "--version")
    check(code == 0 and version in out, f"--version prints {version}", out)
    code, out = run(exe, empty, "--help")
    check(code == 0 and "usage: wxbrief" in out, "--help", out)
    code, out = run(exe, empty, "--selftest")
    check(code == 0, "--selftest", out)
    code, out = run(exe, empty, "decode", "--plain", METAR)
    check(code == 0 and "Flight category" in out and "Traceback" not in out, "decode", out)

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))
    from uat_kit import Terminal, unavailable_reason

    reason = unavailable_reason()
    check(reason is None, "a pseudo-terminal is available", str(reason))
    if reason is None:
        with Terminal(
            [exe, "--demo", "--config", "{dir}/config.toml"], 100, 30, env={"WXBRIEF_CACHE_DIR": "{dir}/cache"}
        ) as term:
            try:
                term.wait_for_text("KDEN", 60)
                check(True, "--demo draws its stations")
            except Exception as exc:  # the kit raises with a screen dump
                check(False, "--demo draws its stations", str(exc))
            term.send_keys("q")
            exit_code = term.wait_exit(30)
            check(exit_code == 0, f"q quits --demo cleanly (exit {exit_code})")

    if failures:
        print(f"\nPOST-RELEASE CHECK FAILED: {len(failures)} check(s)")
        return 1
    print("\npost-release check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
