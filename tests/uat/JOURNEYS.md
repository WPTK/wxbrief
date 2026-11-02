# Journey coverage (plan J1 to J24)

Real input only: the program under the `uat_kit` terminal (pty on Linux, ConPTY on Windows), real key bytes, SGR mouse
with the pointer moved in before every click, and the fault proxy (`uat_kit.faultproxy`) for network states. The
program is `python -m wxbrief` (from `WXBRIEF_PTY_SRC` when set) or the built exe when `WXBRIEF_PTY_EXE` is set.
Linux and Windows only. The first column says what existed before this change; "added" means a test in
`test_real_journeys.py` (offline) or `test_real_journeys_net.py` (fault proxy, needs `openssl`).
Tests that take minutes carry `uat_live` and skip unless `WXBRIEF_UAT_LIVE=1`.

| J | Before | Added | Open defect (xfail strict, unless noted) |
| --- | --- | --- | --- |
| J1 | tests/pty/test_pty_journeys.py::test_startup_shows_list_with_first_station_selected (start only) | test_real_journeys.py::test_J1_first_run_add_denver_read_forecast_quit_and_the_station_is_back | |
| J2 | MISSING | test_J2_stations_on_the_command_line_are_for_this_run_only, test_J2_no_config_file_means_no_file_written | |
| J3 | tests/pty/test_pty_journeys.py::test_repeated_refresh_in_demo_shows_one_toast, ::test_demo_mode_is_visible_after_the_toast_has_gone (parts) | test_J3_demo_browse_ten_stations_keys_refresh_add_remove_theme_and_nothing_saved | |
| J4 | MISSING | test_J4_add_by_icao_iata_and_name_and_say_what_happened_otherwise | |
| J5 | MISSING | test_J5_remove_the_last_one_a_middle_one_then_all_of_them | |
| J6 | tests/pty/test_pty_journeys.py::test_grid_click_selects_a_card_and_it_sticks, ::test_enter_and_escape_round_trip, ::test_click_keeps_focus_on_the_list (parts) | test_J6_list_and_grid_keep_the_selection_clicks_select_and_enter_opens | |
| J7 | tests/uat/test_knownbad_live.py::test_224_absent_section_is_explained_not_silent (one case) | test_J7_keys_1_2_3_on_every_demo_station_never_do_nothing_silently, test_J7b_keys_1_2_3_when_all_sections_fit_on_screen | J7b: #245 |
| J8 | MISSING | test_J8_paste_decodes_a_metar_and_a_taf_and_says_so_for_junk | |
| J9 | tests/pty/test_pty_inventory.py::test_t_changes_colours, ::test_click_settings_option (parts) | test_J9_look_and_feel_changes_persist_and_survive_a_relaunch | |
| J10 | MISSING | test_J10_per_run_flags_apply_to_this_run_and_are_never_saved, test_J10_no_config_reads_and_writes_nothing | |
| J11 | tests/uat/test_knownbad_live.py::test_real_outage_is_visible_then_recovers (after the first run) | test_real_journeys_net.py::test_J11_first_run_with_the_network_down_says_why_within_5_seconds, ::test_J11_the_network_returns_and_the_data_arrives_without_a_restart | first: #236 |
| J12 | MISSING | test_J12_offline_with_a_warm_cache_shows_the_saved_data_and_recovers | |
| J13 | tests/uat/test_knownbad_live.py::test_J13b_single_reset, ::test_j13b_metar_ok_taf_fails_three_cycles_never_offline_beside_fresh, ::test_blips_in_cycle_two_then_ok_stay_quiet | test_J13_partial_failures_never_make_the_status_bar_contradict_itself, test_J13_a_429_with_retry_after_holds_the_product_then_recovers, test_J13_a_slow_answer_does_not_freeze_the_keys_or_contradict_the_bar | |
| J14 | tests/uat/test_knownbad_live.py::test_224_absent_section_is_explained_not_silent | test_J14_a_station_with_no_taf_says_so_in_the_detail_pane, ::key_3_on_a_station_with_no_taf_explains_it, ::a_station_with_a_taf_and_no_metar_says_so_for_key_2, ::a_station_with_no_report_at_all_says_so, ::old_data_is_called_stale_never_fresh | no-TAF case: #253 |
| J15 | MISSING | test_J15_a_twelve_minute_session_keeps_polling_politely_and_stays_steady (`uat_live`) | |
| J16 | tests/pty/test_pty_journeys.py::test_resize_keeps_the_selection, tests/pty/test_pty_compat.py::test_too_small_terminal_says_so_and_recovers | test_J16_resize_storm_keeps_the_selection_and_the_key_bar[list, grid] | list: #255; grid: #259 (non-strict, intermittent) |
| J17 | MISSING | test_J17_get_prints_both_reports_and_exits_zero, ::get_retries_once_when_the_first_request_fails, ::get_with_the_network_down_gives_a_plain_message | down: #254 |
| J18 | tests/pty/test_pty_compat.py::test_exit_leaves_the_terminal_clean (q only) | test_J18_ctrl_q_quits_and_ctrl_c_says_how, ::ctrl_c_hint_is_plain_text, ::signals_end_the_program_and_restore_the_terminal, ::kill_9_then_relaunch_recovers_the_config_and_the_cache | hint: #258 |
| J19 | tests/pty/test_pty_compat.py::test_help_lists_every_readme_key, tests/pty/test_pty_inventory.py (key and click inventories) | test_J19_every_key_bar_label_works_with_the_mouse_alone, ::clicking_quit_in_the_key_bar_quits | |
| J20 | MISSING | test_J20_a_config_and_cache_written_by_0_3_0_are_honoured (fixtures made by the 0.3.0 source) | |
| J21 | MISSING | test_J21_nothing_is_left_behind_outside_the_two_folders_and_removing_them_resets_the_app | |
| J22 | MISSING | MISSING: needs the built wheel, sdist and exe per OS cell; belongs to the packaging jobs (#211, #212), not to a pty test | |
| J23 | MISSING | test_J23_a_broken_local_environment_starts_the_app_and_never_shows_a_traceback, ::a_corrupt_config_is_said_out_loud | |
| J24 | tests/pty/test_pty_compat.py::test_no_color_draws_no_colour, ::test_colour_environments_start_and_quit, ::test_ascii_glyph_set_draws_only_ascii_symbols | test_J24_the_first_run_and_the_section_keys_work_when_the_terminal_is_poor | |

Observed, not filed: searching "Denver" ranks Denver/Centennial (KAPA) above Denver Intl (KDEN). No journey fails on it
(J1 picks KDEN by id).

## Extra checks (L1 to L7)

| L | Test | Open defect |
| --- | --- | --- |
| L1 | test_real_extras_net.py::test_L1_L2_a_failing_source_reaches_a_stated_state_with_a_way_to_retry (METAR and TAF x 5xx, bad JSON, empty list, dropped connection; `r` asks again). Slow answers are L3. The station database is bundled, so it has no remote failure to inject. | #262 (drop, empty list: 4 cases) |
| L2 | same test (no Error, Exception, Traceback or URL on screen), plus test_real_extras.py::test_L2_get_with_the_network_blocked_shows_no_internals | #254 |
| L3 | test_real_extras_net.py::test_L3_slow_data_updates_the_view_without_a_keypress (5 s; 20 s is `uat_live`) | |
| L4 | test_docs_flags.py (flags in README, `--help`, `decode --help`, `get --help`, each accepted). Keys are covered by tests/pty/test_pty_inventory.py and test_pty_compat.py::test_help_lists_every_readme_key. | #263 |
| L5 | test_contrast.py::test_L5_every_text_style_is_legible_in_every_theme (computed, 18 themes) | #260 (8 themes) |
| L6 | test_real_extras.py::test_L6_every_screen_at_every_size_holds_together and ::test_L6_the_empty_state_at_every_size at 80x24, 100x30, 120x40, 300x60 | 300x60: #261 |
| L7 | test_real_extras.py::test_L7_the_first_inputs_on_a_fresh_profile_each_change_the_screen (passes: all ten inputs change the screen) | |
