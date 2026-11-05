"""Run the install and quick-start commands of README.md in a clean directory (CI gate, issue #213).

Every command in a fenced block of the README, and the `pip install` command in the release table, must be covered by
a rule below: run as written, run with a stated substitution, or skipped with a stated reason. A README command that
no rule covers fails, and so does a rule that matches nothing in the README, so the README and the CI cannot drift.

    python scripts/readme_commands.py --wheel-dir dist

`--wheel-dir` holds the wheel built from this checkout. The release-download step is the only thing replaced: the
README's `pip install wxbrief-X.Y.Z-py3-none-any.whl` runs against the locally built wheel, and fails if the README
names a different version from `wxbrief/__init__.py`. `pipx install wxbrief` is replaced the same way (the version on
PyPI only exists after the tag), by a plain `pip install` of the wheel in a fresh venv.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
WIN = sys.platform == "win32"
DEMO_TIMEOUT = 60


@dataclass
class Rule:
    command: str  # the README command, exactly as written, without a trailing comment
    action: str  # run | run-substituted | skip
    note: str  # the substitution, or the reason for skipping
    matched: bool = False


RULES = [
    Rule("pipx install wxbrief", "run-substituted", "the locally built wheel replaces the PyPI download"),
    Rule("git clone https://github.com/WPTK/wxbrief.git", "run-substituted", "the URL is replaced by this checkout"),
    Rule("cd wxbrief", "run", ""),
    Rule("python -m venv .venv", "run", ""),
    Rule(
        ".venv/bin/python -m pip install -e .", "run-substituted", "Windows runs use .venv\\Scripts, as the README says"
    ),
    Rule(".venv/bin/wxbrief --version", "run-substituted", "Windows runs use .venv\\Scripts, as the README says"),
    Rule("wxbrief --demo", "run", "under a pseudo-terminal, then q; skipped on Windows (tests/pty covers ConPTY)"),
    Rule("wxbrief KDEN EGLL ETHB", "skip", "needs the live AWC feed; the fake-AWC suite covers it"),
    Rule("wxbrief", "skip", "needs saved stations and the live AWC feed"),
    Rule(
        'wxbrief decode "METAR KDEN 131453Z 06007KT 3/4SM BR OVC003 09/08 A3001"', "run", "installed from the checkout"
    ),
    Rule("wxbrief get KDEN EGLL --plain", "skip", "needs the live AWC feed; the fake-AWC suite covers it"),
    Rule('echo "METAR KDEN 131453Z 06007KT 3/4SM BR OVC003 09/08 A3001" | wxbrief decode --lang de', "run", ""),
    Rule(
        "pip install wxbrief-{version}-py3-none-any.whl",
        "run-substituted",
        "the locally built wheel replaces the download",
    ),
]

results: list[tuple[str, str, str]] = []
failures: list[str] = []


def fenced_commands(text: str) -> list[str]:
    """Every command line of every fenced `sh` block, trailing comments removed."""
    out: list[str] = []
    for block in re.findall(r"^```sh\n(.*?)^```", text, flags=re.S | re.M):
        for line in block.splitlines():
            line = re.sub(r"\s+#.*$", "", line).strip()
            if line:
                out.append(line)
    return out


def table_pip_commands(text: str) -> list[str]:
    return re.findall(r"`(pip install [^`]+)`", text)


def fail(msg: str) -> None:
    print(f"FAIL  {msg}")
    failures.append(msg)


def venv_dir(base: Path) -> Path:
    return base / ".venv" / ("Scripts" if WIN else "bin")


def shell(cmd: str, cwd: Path, env: dict[str, str], timeout: int = 600) -> subprocess.CompletedProcess[str]:
    bash = "/bin/bash"
    if WIN:  # Git for Windows' bash (on the runners), not the WSL launcher in System32
        git_bash = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
        bash = str(git_bash) if git_bash.is_file() else shutil.which("bash")
    return subprocess.run(
        [bash or "bash", "-c", cmd], cwd=cwd, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )  # fmt: skip


def run_demo(cwd: Path, env: dict[str, str]) -> tuple[bool, str]:
    """`wxbrief --demo` under a pseudo-terminal: it must draw something and quit on q with exit 0."""
    import pty
    import select
    import time

    pid, fd = pty.fork()
    if pid == 0:  # child
        os.chdir(cwd)
        os.execvpe("wxbrief", ["wxbrief", "--demo"], env)
    import fcntl
    import struct
    import termios

    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 100, 0, 0))
    seen = b""
    end = time.monotonic() + DEMO_TIMEOUT
    sent = False
    resend = 0.0
    status = None
    while time.monotonic() < end:
        r, _, _ = select.select([fd], [], [], 0.5)
        if r:
            try:
                data = os.read(fd, 65536)
            except OSError:
                data = b""
            if not data:
                break
            seen += data
        if not sent and b"KDEN" in seen:
            time.sleep(1)
            os.write(fd, b"q")
            sent = True
            resend = time.monotonic() + 5
        elif sent and time.monotonic() > resend:  # the first q can land before the app reads keys
            os.write(fd, b"q")
            resend = time.monotonic() + 5
        done, st = os.waitpid(pid, os.WNOHANG)
        if done:
            status = st
            break
    while status is None and sent and time.monotonic() < end:  # the pty closed (EOF): collect the exit status
        done, st = os.waitpid(pid, os.WNOHANG)
        if done:
            status = st
        else:
            time.sleep(0.2)
    if status is None:
        os.kill(pid, 9)
        os.waitpid(pid, 0)
        print(seen[-1500:].decode("utf-8", "replace"))
        return False, "did not quit after q" if sent else "never drew the demo stations"
    code = os.waitstatus_to_exitcode(status)
    return (sent and code == 0), f"exit {code}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wheel-dir", required=True, type=Path, help="folder with the wheel built from this checkout")
    args = ap.parse_args()

    text = README.read_text(encoding="utf-8")
    version = re.search(r'__version__ = "([^"]+)"', (ROOT / "wxbrief" / "__init__.py").read_text())
    assert version
    version = version.group(1)

    for rule in RULES:
        rule.command = rule.command.replace("{version}", version)
    by_cmd = {r.command: r for r in RULES}

    commands = fenced_commands(text) + table_pip_commands(text)
    if "On Windows the venv paths are `.venv\\Scripts\\python` and `.venv\\Scripts\\wxbrief`" not in text:
        fail("README no longer says how the venv paths differ on Windows; the Windows substitution is unjustified")
    if f"Version {version}." not in text:
        fail(f"README does not state 'Version {version}.' (wxbrief/__init__.py says {version})")
    for name in re.findall(r"`(wxbrief-[0-9][^`]*)`", text):
        if not name.startswith(f"wxbrief-{version}-"):
            fail(f"README lists release file {name}, which does not match version {version}")

    for cmd in commands:
        rule = by_cmd.get(cmd)
        if rule is None:
            fail(f"README command has no rule in scripts/readme_commands.py: {cmd}")
        else:
            rule.matched = True
    for rule in RULES:
        if not rule.matched:
            fail(f"rule matches nothing in the README (README changed?): {rule.command}")
    if failures:
        return 1

    base = Path(tempfile.mkdtemp(prefix="readme-run-"))
    work = base / "work"
    work.mkdir()
    env = os.environ.copy()
    env.update(WXBRIEF_CACHE_DIR=str(base / "cache"), NO_COLOR="1")
    for var in ("PYTHONPATH", "VIRTUAL_ENV", "WXBRIEF_CONFIG"):
        env.pop(var, None)
    cwd = work
    on_path = False

    for cmd in commands:
        rule = by_cmd[cmd]
        label = f"{cmd}"
        if rule.action == "skip":
            results.append((cmd, "skipped", rule.note))
            print(f"skip  {cmd}  ({rule.note})")
            continue
        if cmd.startswith("pip install wxbrief-") or cmd == "pipx install wxbrief":
            wheel_name = f"wxbrief-{version}-py3-none-any.whl" if cmd == "pipx install wxbrief" else cmd.split()[-1]
            wheels = list(args.wheel_dir.glob(wheel_name))
            if not wheels:
                built = [p.name for p in args.wheel_dir.iterdir()]
                fail(f"README names {wheel_name} but the build produced {built}")
                continue
            venv = base / ("pipx-venv" if cmd.startswith("pipx") else "wheel-venv")
            subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
            py = venv / ("Scripts" if WIN else "bin") / "python"
            proc = subprocess.run([str(py), "-m", "pip", "install", str(wheels[0])], capture_output=True, text=True)
            ok = proc.returncode == 0
            results.append((cmd, "ran" if ok else "FAILED", rule.note))
            print(("ok    " if ok else "FAIL  ") + cmd)
            if not ok:
                fail(f"{cmd}\n{proc.stdout[-1500:]}{proc.stderr[-1500:]}")
            continue
        if cmd.startswith("git clone "):
            run_cmd = f'git clone "{ROOT.as_posix()}" wxbrief'
        elif cmd.startswith("cd "):
            cwd = cwd / cmd.split()[1]
            results.append((cmd, "ran", ""))
            print(f"ok    {cmd}")
            continue
        elif cmd.startswith(".venv/bin/"):
            run_cmd = cmd.replace(".venv/bin/", ".venv/Scripts/" if WIN else ".venv/bin/")
        else:
            run_cmd = cmd
        if (cmd.startswith("wxbrief") or "| wxbrief" in cmd) and not on_path:
            env["PATH"] = str(venv_dir(cwd)) + os.pathsep + env["PATH"]
            on_path = True
        if cmd == "wxbrief --demo":
            if WIN:
                results.append((cmd, "skipped", "ConPTY is covered by tests/pty"))
                print(f"skip  {cmd}  (Windows)")
                continue
            ok, detail = run_demo(cwd, env)
            results.append((cmd, "ran" if ok else "FAILED", detail))
            print(("ok    " if ok else "FAIL  ") + f"{cmd}  ({detail})")
            if not ok:
                fail(f"{cmd}: {detail}")
            continue
        proc = shell(run_cmd, cwd, env)
        out = proc.stdout + proc.stderr
        ok = proc.returncode == 0
        if cmd.endswith("--version"):
            ok = ok and version in out
        if "decode" in cmd:
            ok = ok and "KDEN" in out and "Traceback" not in out
        results.append((cmd, "ran" if ok else "FAILED", rule.note))
        print(("ok    " if ok else "FAIL  ") + label)
        if not ok:
            fail(f"{cmd} (exit {proc.returncode})\n{out[-2000:]}")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    lines = ["| README command | Result | Note |", "| --- | --- | --- |"]
    lines += [f"| `{c.replace('|', chr(92) + '|')}` | {r} | {n} |" for c, r, n in results]
    print("\n" + "\n".join(lines))
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    shutil.rmtree(base, ignore_errors=True)
    if failures:
        print(f"\n{len(failures)} failure(s)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
