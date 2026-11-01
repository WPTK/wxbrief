# uat_macos: real input to Terminal.app and iTerm2

Drives the app in a real Terminal.app or iTerm2 window on a GitHub-hosted macOS runner. Keys and mouse clicks are real
events posted to the window server (`cliclick`), the screenshot is the window as drawn (`screencapture -l`), and the
screen text is read back through the terminal itself (AppleScript for Terminal.app, the `iterm2` Python API for
iTerm2). There is no `tmux send-keys` and no pty write anywhere.

The method comes from eyewall's S4 spike (`spike/s4-macos-input`, runs 4 to 6, PASS on macos-26, macos-15 and
macos-15-intel for both terminals). `MacTerminal` has the same shape as `uat_kit.Terminal`: an argv goes in (`run`), screen
text and PNGs come out (`wait_for_text`, `send_keys`, `click`, `click_text`, `resize`, `screen_text`, `settle`,
`wait_exit`, plus `screenshot`). The window is started once and runs one program after another, so iTerm2 is
launched once per job. `test_probe.py` runs a raw byte reader in the same window to show what the terminal sent for
an Esc key and for clicks at six cells, apart from the app.

## Run

`.github/workflows/uat-macos.yml` (`workflow_dispatch` only) runs `test_demo_journey.py` on macos-26, macos-15 and
macos-15-intel, in Terminal.app and iTerm2: launch, wait for text, keys 1/2/3, click a station, resize, quit, with
`--demo --no-config` and an isolated cache directory. Each cell uploads an artifact with a PNG and the screen text per
step, `pytest.txt`, `junit.xml`, the TCC grant logs and a last full-screen capture.

Locally the tests skip unless `WXBRIEF_UAT_MACOS` is `Terminal` or `iTerm2`, and `test_geometry.py` runs everywhere.

## How it works

1. `scripts/grant_tcc.sh` writes Accessibility, ScreenCapture, PostEvent and Apple Events grants into the TCC databases with
   `sudo sqlite3`, then `killall tccd`, then proves it with a System Events key press. The runner's responsible process
   is `/opt/hca/hosted-compute-agent`.
2. The driver starts the terminal, runs the app from a small `inner.sh` that publishes the terminal size (`stty size`)
   and the exit code, and sets the window to the requested cols x rows by measuring the cell size (no hard-coded font).
3. A click targets the centre of a cell. The cell size is worked out from the window width and height at two different
   sizes (Terminal.app's scroller makes `window width / cols` too big, which misses by 2 to 4 columns at column 60 to
   100); the grid starts after the 28 point title bar. `click_text` aims at the middle of a word, so a one-column miss
   still lands on it.

## Caveats (keep these true)

- **Depends on the hosted image**: SIP off and passwordless sudo, as on image 20261026-28. If GitHub changes either, or the
  responsible-process path, the grant step fails and the log says where. There is no fallback.
- **iTerm2 has one passing run per runner** in the spike, so its stability is less proven than Terminal.app's (three runs
  per runner). Treat a single iTerm2 failure as unconfirmed until it repeats. iTerm2 is not preinstalled
  (`brew install --cask iterm2`), needs its quarantine flag removed, and on macos-26 a local-network prompt appeared once;
  `scripts/dismiss_dialogs.py` clicks it through Accessibility.
- **Possible off-by-one click on macos-26 Terminal.app**: in two spike runs a list click landed one column left (5 vs 6)
  while the probe and button clicks were exact. The cause is unexplained and is being re-measured. Nothing here asserts
  an exact column for a click; the journey asserts the effect (the clicked station is selected).
- **No scripted-replay substitute**: replaying recorded bytes into a pty does not exercise Terminal.app or iTerm2 input
  handling and must not be reported as a macOS pass. A cell that cannot run is "not run", not "passed by replay".
- Display is 1x (1024x768). Retina scaling, other window positions, drag, scroll wheel, right click, modifier clicks and
  copy/paste are untested.
- Terminal.app read-back returns scrollback above the screen; the driver keeps the last `rows` lines, which relies on the
  app drawing its last row (wxbrief's footer does).
