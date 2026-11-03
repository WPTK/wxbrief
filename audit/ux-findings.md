# UX / TUI audit findings

Scope: Textual app, widgets and screens (`wxbrief/ui`, `wxbrief/app.py`). Tests only, under `tests/ux/`; no product
source changed; no issues filed. Excluded as already covered: #264 journeys J1-J24, #246 manual real-terminal UAT, and
open issues such as #236, #238, #247/#234, #248, #257, #259-#262. Every defect below has a strict `xfail` test whose
reason is the finding id, so the suite stays green and flips red (XPASS) when a fix lands.

Run: `python -m pytest tests/ux -q -rxX` (add `-m "not slow"` to skip the 10-example hypothesis monkey test).
Snapshots: `tests/ux/__snapshots__/test_screens/` (12 SVGs: long METAR, 40 stations, empty, offline error, each at
80x24, 120x40, 200x60). Regenerate with `--snapshot-update`.

## Verified defects

### UX-01 - An observation 55 to 75 minutes old is labelled "fresh"
- Priority / domain: P3 `data` `ui`
- Where: `wxbrief/data/poll.py:31` (`STALE_AFTER = timedelta(minutes=75)`), `:39-43` (`freshness`); consumed at
  `wxbrief/ui/widgets/station_list.py:98`, `wxbrief/ui/widgets/detail.py:47`, `wxbrief/ui/widgets/status_bar.py:58`.
- Repro: `tests/ux/test_feed_age.py::test_an_observation_older_than_55_minutes_is_not_called_fresh`. Or run the app with a
  METAR observed 67 minutes ago.
- Expected: routine METARs are issued about hourly, so past roughly 55 minutes the next one is overdue; the pane should
  stop saying "fresh" (or add an "overdue" step).
- Actual: header reads `Observed 05:34 MDT, 1 h 07 min ago  ● fresh` and the status bar `● fresh`; it turns `◐ stale`
  only at 75 minutes.
- Output: `freshness(OBS, OBS + 56 min)` returns `Freshness.FRESH` (strict xfail "UX-01").

### UX-02 - No feed-age state: nothing tells the user that polls stopped succeeding
- Priority / domain: P3 `ui` `data`
- Where: `wxbrief/ui/widgets/status_bar.py:77-84` (only `next poll m:ss` and `req n/100`), `wxbrief/state.py:276-291`
  (`record_error` only shows an error from the second consecutive network failure), `wxbrief/data/poll.py:49,124`
  (`time.monotonic` is used for scheduling only; `fetched` is never exposed).
- Today: there is no LIVE / STALE (300 s) / OFFLINE feed indicator. The only age shown is the observation age (UX-01)
  and "saved data from N min ago" once offline. A feed that answers but returns an old report, a hung request, or a
  single dropped fetch shows `fresh` / `next poll 0:00` with no sign that the last good fetch was minutes ago.
- Repro: `tests/ux/test_feed_age.py::test_status_bar_reports_feed_age_when_polls_stop_succeeding` (clock advanced 400 s
  after a successful cycle; status bar shows no age or stale wording).
- Expected: a visible "last updated N min ago" / LIVE-STALE-OFFLINE state driven by a monotonic clock, so wall-clock
  jumps (#238) cannot fake it.
- Confirmed working today: offline needs two consecutive transport failures, then reads
  `offline, showing saved data from N min ago` (`test_offline_needs_two_network_failures_then_shows`).

### UX-03 - `$` (maintenance) and SPECI are visible only after opening a station
- Priority / domain: P3 `ui`
- Where: chip is drawn in `wxbrief/ui/widgets/detail.py:61-71` (`FlagsRow`); the list row built at
  `wxbrief/ui/widgets/station_list.py:98-124` and the card at `wxbrief/ui/widgets/station_card.py:60-85` carry no flag.
- Repro: `tests/ux/test_feed_age.py::test_station_list_row_marks_maintenance_and_special_reports`; positive controls
  `test_maintenance_flag_shows_as_a_chip_in_the_detail_pane` and `test_special_report_is_a_chip_in_the_detail_pane` pass.
- Expected: the list and grid, where the pilot scans, mark `$` (sensors may be unreliable) and an unscheduled SPECI.
- Actual: row text is `● KDEN  LIFR  32005KT 1/4SM`; the `$` station `KJFK` looks identical to a healthy one.

### UX-04 - Emoji glyph set marks fresh / stale / missing by colour alone
- Priority / domain: P3 `accessibility` `ui`
- Where: `wxbrief/ui/glyphs.py:22` (`fresh="🟢", stale="🟠", missing="⚪"`), used in list rows
  (`station_list.py:98-103`) and cards, where there is no word beside the mark.
- Repro: `tests/ux/test_hazard_hierarchy.py::test_freshness_marks_differ_in_shape_not_only_colour[emoji]`.
- Expected: shapes differ (as in `ascii` `* ! -` and `unicode` `● ◐ ○`, which pass).
- Actual: three circles that differ only in colour.

### UX-05 - TAF timeline "temporary" row names its category by colour only
- Priority / domain: P3 `accessibility` `render`
- Where: `wxbrief/ui/widgets/taf_timeline.py:29,249-253` and `wxbrief/ui/widgets/station_card.py:44-46`: the row under
  the strip is `▀` blocks coloured with the TEMPO/PROB worst category; the main row prints a letter (`V`, `M`, `I`, `L`).
- Repro: `tests/ux/test_hazard_hierarchy.py::test_timeline_overlay_row_has_a_non_colour_category_marker`.
- Expected: a letter (or distinct glyph per category) so IFR vs LIFR vs MVFR can be told apart without colour.
- Actual: row 3 of the widget contains no alphabetic character; the hatched BECMG cells have the same property.

### UX-06 - Ctrl+P command palette lists none of the app's own commands
- Priority / domain: P3 `ui`
- Where: `wxbrief/app.py:90` binds the palette; `get_system_commands` is not overridden.
- Repro: `tests/ux/test_focus_graph.py::test_command_palette_offers_the_apps_own_commands`. The palette opens and closes
  with focus restored (that test passes).
- Actual titles: `Theme, Quit, Keys, Maximize, Screenshot`. Missing: Add station, Refresh, Paste, Settings, Help,
  List/grid, units / time / glyph cycling. `Keys` opens Textual's own help panel next to the app's `?` Help, and
  `Screenshot` writes an SVG into the working directory.

### UX-07 - Dark-theme category colours are close under protan / deutan colour vision
- Priority / domain: P4 `accessibility`
- Where: `wxbrief/ui/themes/semantic.py:25-30` (`FLIGHT_CATEGORY_COLORS` dark values).
- Repro: `tests/ux/test_hazard_hierarchy.py::test_category_fills_stay_distinct_under_colour_blindness[textual-dark-deutan|protan]`
  (Machado 2009 simulation, CIE76 dE below 10: VFR/IFR 9.9 for deutan, MVFR/LIFR 9.0 for protan).
- Mitigated: every badge carries the code text (`test_badge_carries_the_category_name_not_only_a_colour` passes), so
  this matters only where colour is the sole cue (UX-05). Light theme passes all three simulations.

### UX-08 - No-report screen keeps an orphan "Raw" heading; empty list still offers "d Remove"
- Priority / domain: P4 `ui`
- Where: `wxbrief/ui/widgets/detail.py:184-190, 202` (`#raw-title` is shown whenever the pane has an entry, while
  `RawReport` hides itself when nothing is held, `detail.py:90`); key bar built in `briefing.py:41-57` /
  `station_list.py` bindings.
- Repro: `tests/ux/test_screens.py::test_no_orphan_section_heading_when_nothing_is_held[error|empty]`; see snapshots
  `test_briefing_snapshot[*-error]` and `[*-empty]`.
- Actual (error, 120x40): `KDEN ... No report yet. Press r to refresh.` followed by a lone `Raw` heading over blank
  space. Empty list key bar: `a Add  d Remove  v List/grid ...` with nothing to remove.

### UX-09 - Station-list name column zig-zags
- Priority / domain: P4 `ui`
- Where: `wxbrief/ui/widgets/station_list.py:120-124` appends the conditions unpadded, then the station name.
- Repro: `tests/ux/test_screens.py::test_station_list_name_column_is_aligned` (name starts at column 28 for
  `08005KT 10SM` and 31 for `13015G27KT 10SM`).

### UX-10 - Decoded table: the flight-category row starts one column right of the others
- Priority / domain: P4 `render`
- Where: `wxbrief/ui/widgets/detail.py:116-128`; the badge (`style.py:48-51`) is padded with a space on each side and
  the hanging indent does not compensate.
- Repro: `tests/ux/test_screens.py::test_decoded_values_start_in_one_column` (`Station` and `Wind` at column 25,
  `Flight category` at 26).

## Latent, not user-visible today

- `wxbrief/ui/widgets/detail.py:113` `DecodedTable._fill` calls `self.clear(columns=True)` on every redraw (30 s tick,
  each poll, theme / unit change, resize). `DataTable.clear` resets `cursor_coordinate` and the table's own scroll.
  Not a defect now: the table is created with `cursor_type="none"` (`detail.py:102`) and `height: auto`, so the
  `DetailPane` is the only scroller. It becomes one the moment the table gets a visible cursor. No xfail is filed because
  the behaviour cannot be observed.

## Monkey test result

`tests/ux/test_refresh_state_machine.py` (hypothesis `RuleBasedStateMachine` driving `Pilot`; rules: 20 keys, four
terminal sizes 80x24 to 200x60, pane scrolling, `redraw_screens`, a repeated poll of unchanged rows; 10 examples of 14
steps, marked `slow`). Invariants: no exception in the app, list highlight equals the selected station, and a refresh
leaves list scroll, pane scroll, TAF cursor, focus, table cursor and table scroll unchanged. Found no violation. Direct
probes agree: pane scrolled to its maximum, the selected station's METAR replaced by a longer one, and the grid
scrolled by hand all keep their position across a refresh.

## Already good

- Every flight-category badge prints its code (`VFR`, `MVFR`, `IFR`, `LIFR`, `--`) in all tested themes; hazard colours
  keep red = IFR, green = VFR, and the light theme is distinct under all three colour-vision simulations.
- ASCII and Unicode freshness marks differ in shape; the header and status bar also spell `fresh` / `stale`.
- Raw-line highlighting: for all 144 saved reports every token span indexes its own text and carries its kind's style
  (`tests/ux/test_token_alignment.py`); unknown groups are coloured and listed as decoder warnings.
- Focus: Tab and Shift+Tab form a closed, reversible cycle through list, pane, remarks, forecast timeline and groups;
  `?` opens Help from every stop and focus comes back; Esc leaves the pane; `v` toggles list / grid and returns focus;
  Ctrl+P opens and closes with focus restored.
- Refresh stability: no scroll, focus or cursor loss on redraw (see monkey test).
- Long METAR (the longest saved, LTFM) keeps every group visible and wrapped at 80x24, 120x40 and 200x60; 26 stations
  keep the highlight inside the list on `j` and, below 90 columns, show the `n/N` position in the status bar.
- Offline: two consecutive network failures show `offline, showing saved data from N min ago`; one does not.
