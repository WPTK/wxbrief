# Known-bad traceability (tests/uat/test_knownbad_live.py)

Each report from Bill's 0.3.0 session, the issue it became, and the live (fake-feed, real exe) test that separates the
0.3.0 release exe (red) from main (green). Measured 2026-11-01: candidate = main 9a15066, 0.3.0 sha256 6ff78a2c...

Run: `WXBRIEF_UAT_KNOWNBAD=1 WXBRIEF_PTY_EXE=<exe> pytest tests/uat/test_knownbad_live.py -n 4`.
Select the named nightly journey with `-m J13b_single_reset`; all live tests carry `-m uat_live` on request
(`J13b_single_reset` is the only one marked so far). Not run in ci.yml (skipped without the env vars).

| Report | Issue | Distinguishing test (red on 0.3.0, green on main) | Expected red on BOTH builds |
| --- | --- | --- | --- |
| One dropped request leaves an error for a whole interval | #219 | `test_J13b_single_reset`, `test_blips_in_cycle_two_then_ok_stay_quiet[reset]`, `test_taf_failure_is_retried_without_pressing_anything` | none |
| `--demo` gives no sign it is demo data | #221 | `test_221_demo_label_stays_when_a_feed_is_reachable` | none |
| Repeated `r` stacks identical toasts | #222 | `test_222_repeated_refresh_in_live_shows_one_toast`, `test_222_repeated_refresh_in_demo_with_a_feed_shows_one_toast` | none |
| Red `offline` beside green `fresh` | #223 | `test_j13b_metar_ok_taf_fails_three_cycles_never_offline_beside_fresh[reset]` and `[drop:60]`, `test_real_outage_is_visible_then_recovers` | none |
| Keys 1/2/3 appear to do nothing (absent section) | #224 | `test_224_absent_section_is_explained_not_silent` | none |
| Click moves focus into the detail pane | #225 | `test_225_click_keeps_focus_on_the_list_in_live` | none |
| Keys 1 and 2 give no visible change when all sections fit | #245 | none (build-blind by nature: the app has no fix yet) | `test_j7b_keys_1_2_3_always_visibly_do_something_when_all_sections_fit` (6 cases); EXPECTED RED until #245 is fixed |

Notes
- J13b with a TAF `5xx` (`[5xx]`) passes on both builds: a 5xx is not a transport error and 0.3.0 never said offline for it.
  Bill's report reproduces only with a dropped connection (`reset`, `drop`), so those are the distinguishing cases.
- J7b is deliberately not `xfail`: the file is skipped in CI, so nothing goes red there. When the known-bad run is added to a
  workflow, mark it `xfail(strict=True, reason="#245")` at that point so the fix turns it into an error to remove the mark.
- Passing on both builds and so not distinguishing: `test_live_mode_does_not_say_demo`, J13b[5xx], blip `[5xx]`.
