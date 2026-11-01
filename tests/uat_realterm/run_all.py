"""Run every real-terminal check for one terminal on one runner; one failing run never stops the next.

    python run_all.py {wt,conhost,vscode} --wxbrief PATH [--tool-exe PATH] --out DIR

Runs, in order: the Medium-integrity probe; a High-integrity baseline journey (what the first spike did); the journey at
Medium integrity in dark and light profiles with the driver itself at Medium (``medium_exec.py``); the journey with a High
driver and a Medium terminal (``--medium-spawn``); the code page, font size, colour depth (light profile) and gesture
scenarios at Medium; for VS Code also the PowerShell profile. Exit code 1 if any run failed.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = sys.executable


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("terminal", choices=["wt", "conhost", "vscode"])
    ap.add_argument("--wxbrief", required=True, type=Path)
    ap.add_argument("--tool-exe", type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--only", default="", help="comma separated run names (default: all)")
    args = ap.parse_args()
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    t = args.terminal
    # The runner's processes are elevated, so files they create are owned by Administrators; the Medium token has
    # Administrators deny-only and could not write the output folder, read the launcher scripts or write VS Code's data dir.
    # Everyone:Modify on the folders the runs use (an ephemeral runner; nothing else lives there).
    roots = {str(out), str(args.wxbrief.resolve().parents[1]), str(Path.cwd())}
    for root in sorted(roots):
        rc = subprocess.run(
            ["icacls", root, "/grant", "*S-1-1-0:(OI)(CI)M", "/T", "/C", "/Q"],
            capture_output=True,
            text=True,
            check=False,
        ).returncode
        print(f"icacls grant Everyone:Modify on {root}: exit {rc}", flush=True)
    common = ["--wxbrief", str(args.wxbrief), "--out", str(out)] + (
        ["--tool-exe", str(args.tool_exe)] if args.tool_exe else []
    )

    def spike(*extra: str) -> list[str]:
        return [PY, str(HERE / "run_spike.py"), t, *common, *extra]

    def matrix(*extra: str) -> list[str]:
        return [PY, str(HERE / "run_matrix.py"), t, *common, *extra]

    def medium(name: str, argv: list[str]) -> list[str]:
        return [PY, str(HERE / "medium_exec.py"), str(out / f"medium-{t}-{name}.log"), "--", *argv]

    runs: list[tuple[str, list[str]]] = [
        ("medium-probe", [PY, str(HERE / "medium.py"), "probe", str(out / "medium-probe.txt")]),
        ("baseline-high", spike("--tag", "high")),
        ("journey-medium-dark", medium("journey-dark", spike("--require-medium", "--tag", "medium"))),
        (
            "journey-medium-light",
            medium("journey-light", spike("--require-medium", "--scheme", "light", "--tag", "medium")),
        ),
        ("journey-highdriver-mediumterm", spike("--medium-spawn", "--require-medium", "--tag", "spawn")),
        ("matrix-medium", medium("matrix", matrix("--require-medium", "--tag", "medium"))),
    ]
    if t == "vscode":
        runs.append(
            (
                "journey-medium-powershell",
                medium("ps", spike("--require-medium", "--profile", "powershell", "--tag", "ps")),
            )
        )
    only = {x for x in args.only.split(",") if x}
    failed: list[str] = []
    flaky: list[str] = []
    for name, argv in runs:
        if only and name not in only:
            continue
        print(f"::group::{t} {name}", flush=True)
        print(" ".join(argv), flush=True)
        t0 = time.monotonic()
        rc = subprocess.run(argv, check=False).returncode
        print(f"--> {name}: exit {rc} in {time.monotonic() - t0:.0f}s", flush=True)
        if rc != 0:  # GUI input can lose one event: run once more, and say so loudly if the second attempt passes
            print(f"::warning::{t} {name} failed (exit {rc}); one retry", flush=True)
            rc = subprocess.run(argv, check=False).returncode
            print(f"--> {name} retry: exit {rc}", flush=True)
            if rc == 0:
                flaky.append(name)
        print("::endgroup::", flush=True)
        if rc != 0:
            failed.append(name)
    print(f"FLAKY RUNS (failed once, passed on retry): {flaky or 'none'}", flush=True)
    print(f"FAILED RUNS: {failed or 'none'}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
