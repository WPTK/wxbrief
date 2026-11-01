# win-realterm: drive a console app in a real Windows terminal (Windows Terminal, conhost, VS Code)

Source of truth: `tests/uat_realterm/` on branch `uat-realterm` of WPTK/wxbrief (copy of the scripts in `scripts\` here is
the spike snapshot only; use the repo). Test-only, no secrets, runs on the GitHub `windows-2025` and `windows-11-arm`
interactive runners (and on a Windows desktop). Result of the latest runs: `RESULT.md`.

## What it is

A Python driver (3.12, deps in `requirements.txt`: uiautomation, comtypes, mss, pillow, psutil) that

1. starts a real terminal window running your command (Windows Terminal portable zip, `conhost.exe`, or VS Code portable
   zip with its integrated terminal),
2. sends REAL input with `SendInput` (keys, mouse move/press/release/wheel, double click, drag),
3. reads the screen back: UI Automation `TextPattern` (WT, conhost) or select-all + copy to the clipboard (VS Code),
4. saves PNGs (screen rectangle, `PrintWindow`, whole desktop) and text,
5. tears everything down by PID.

The app under test needs no changes and no test hooks. Calls in: an app command line + a list of steps. Out: screen text
files, PNG files, a result JSON, an exit code.

## Calling it (what eyewall / earthwave do)

```powershell
pip install -r tests/uat_realterm/requirements.txt
# once per tool, pinned and hash-checked (pins.json):
python tests/uat_realterm/fetch.py wt     --dest $env:RUNNER_TEMP\tools\wt      # prints JSON with "exe"
python tests/uat_realterm/fetch.py vscode --dest $env:RUNNER_TEMP\tools\vscode  # (conhost is built in)

python tests/uat_realterm/drive.py wt --out out --tool-exe <wt exe> `
    --cmd "C:\path\myapp.exe --demo" --steps steps.json [--scheme light] [--medium-spawn] [--codepage 437] `
    [--font-pt 12] [--env NO_COLOR=1] [--first-frame "Ready"]
```

`steps.json`: a list, run in order. Matching is by screen text, never by fixed coordinates:

```json
[
  {"wait": "Stations \(10\)", "timeout": 30},
  {"keys": "2"},
  {"click": "UUEE"},
  {"wait": "4/10"},
  {"click": "KDEN", "button": "right"},
  {"click": "UUEE", "double": true},
  {"wheel": "UUEE", "notches": -3},
  {"drag": ["KDEN", "UUEE"]},
  {"hover": "UUEE"},
  {"key": "escape"},
  {"read": "after-gestures"},
  {"shot": "after-gestures"},
  {"expect": "UUEE"}, {"expect_not": "Traceback"},
  {"quit": "q"}
]
```

Outputs in `--out`: `result-<terminal>-drive.json` (every step with `ok`/`detail`), `<terminal>-drive-<tag>.txt` (screen
text), `<terminal>-drive-<tag>-{window,printwindow,desktop}.png`, `…-uia-tree.txt`. Exit code 0 when every `wait`/`expect`
passed and the app exited on `quit`.

As a library (Python): `import run_spike as rs, winterm as w`; `t = rs.WindowsTerminal(rep, exe, out, tool_exe, ...,
app_cmd="myapp.exe")`; `t.launch(); t.prepare_window(); t.read(); w.click_at(*t.rect_of("text"))`. `run_matrix.py` is a worked
example (code pages, font size, display scale, colour depth, gestures); `run_spike.py` is the minimal journey.

## Rules that cost hours to learn (see RESULT.md "Exact traps")

* Assert on content (`KDEN LIFR Denver`), never "the text changed". Wait for the complete first frame, not the first byte.
* No ALT-tap focus trick when the window is already foreground (VS Code menu bar eats the next key).
* WT: take the UIA element with the most text (`TermControl`). Unpackaged WT needs a launcher `.cmd` so the app's own flags
  are not parsed as WT options. WT portable: `.portable` file + `settings\settings.json` next to the exe.
* VS Code: no usable UIA tree. Read = clipboard (keybindings in the portable `data\user-data\User\keybindings.json`),
  geometry = measured with `probe_mouse.py`, first start about 45 s, close side bars and maximise the panel.
* Call `SetProcessDpiAwarenessContext(-4)`; the runner screen is 1024x768 at 96 dpi.

## Non-elevated (Medium integrity) runs

The runner user is an administrator and its processes are High. `medium.py` starts a process at Medium: a restricted
copy of the caller's token (Administrators deny-only, privileges stripped, owner = user, **default DACL = user + SYSTEM**,
integrity S-1-16-8192) through `CreateProcessAsUser` on `winsta0\default`. Without the default-DACL step Windows Terminal
fails to start its shell (`0xd0000022` ACCESS_DENIED), because the elevated token's default DACL names only Administrators.
`medium_exec.py LOG -- <command>` runs a whole command (the driver itself) at Medium and relays its log; `--medium-spawn`
starts only the terminal at Medium. Folders the Medium process uses must be writable by it (`run_all.py` grants
`Everyone:Modify` on the out, tools and workspace folders on the ephemeral runner). Integrity is proven, not assumed: the
driver reads the window owner's `TokenIntegrityLevel` and fails with `--require-medium` unless it is Medium; the result JSON
carries `integrity_window` and `integrity_driver`.

## Reuse notes

* One job per terminal: `.github/workflows/uat-realterm.yml` (workflow_dispatch only) plans a matrix from inputs
  `terminals`, `arm`, `runs`; `run_all.py` is the entry point it calls.
* Light profile is applied and PROVEN by pixels (`analyze_png`: most common colour of the central area, luminance > 0.7)
  before the app starts; the app is waited on only after that. A cell whose profile proof fails is not to be relied on.
* To reuse in another repo, vendor `tests/uat_realterm/` (it imports nothing from wxbrief) and point `--cmd` at your app.
