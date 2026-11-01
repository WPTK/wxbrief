# Changelog

## 0.3.0 - 2026-10-31

### Changed

- Give a flight category or colour state only when ceiling, sky and visibility are known, and read `BLU+` as visibility 8 km or more with no low ceiling (#74, #139, #36)
- Mark data as stale or offline, drop a held forecast the feed no longer lists, and keep open screens current after every poll (#77, #171, #181)
- Re-use unchanged AWC responses with conditional requests so polling stays polite (#81)
- Choose the sun or moon glyph from solar elevation, not a fixed clock window (#45)
- Lead the decode of a cancelled TAF with the cancellation and drop its forecast groups (#184)
- Show an expired TAF as expired, and keep it out of the `C` copy (#77, #190)
- Simplify Settings to the four rows Enter changes, and show the copy confirmation as a one-row toast (#202)
- Say "No report yet" for a station with no report, and show one line for it in `wxbrief get` (#147, #202)
- Keep the hovered timeline hour a preview, and pin an hour only by click or key (#170)

### Added

- Add a "What wxbrief is not" notice to the README, `--help` and the help screen (#81)
- Add a notice when the terminal is too small to lay out the screen (#73)
- Add the TAF Flags row, with tornado, funnel cloud and squall flags, and the TAF decode warnings (#190)
- Add an animated demo recorded from the real app to the README (#80)

### Fixed

- Fix wrapped, clipped and overlapping layouts at small terminal sizes (#73, #140, #169, #202)
- Fix three TAF decoder and Discord edge cases, and wind, runway visual range, gust and cumulonimbus decoding (#34, #74, #139)
- Fix the station list and grid not keeping the selected item in view after a resize (#170, #181)
- Drop numeric admin codes from station regions (#147)

## 0.2.0 - 2026-10-31

### Changed

- Show the footer keys for the focused pane, with `a` visible in the narrow footer (#32)
- Show the station count once, in the title of the list and the grid, and drop "1/N" from the detail header (#32)
- Show an expired TAF as `TAF expired` instead of `no TAF` on grid cards (#31)

### Added

- Add hour labels and the zone name to the mini timeline on grid cards (#31)

### Fixed

- Fix the copy keys on the station detail screen opened from the grid (#32)

## 0.1.0 - 2026-10-31

### Added

- Add the `decode` command with a hand-written METAR and SPECI decoder and plain and colour output (#1)
- Decode METAR remarks, trends, colour states, runway state, recent weather, wind shear and sea state (#2)
- Decode TAFs (amendments, cancellations, change groups, temperature extremes) split pasted blobs into reports, and add Discord and JSON output (#17)
- Add the `get` command to fetch the latest METAR and TAF from aviationweather.gov, with a polling budget, a disk cache and a config file (#16)
- Add the aviation colorways, flight-category and colour-state colours, and `--theme` for the command line (#20)
- Add the terminal UI with a station list, decoded detail pane, station search, paste-and-decode, clipboard copy and help (#21)
- Add `t` and `T` to change and preview colorways, and remember the choice (#23)
- Add the TAF timeline with a period cursor, the grid layout, `v` to switch layouts and the offline `--demo` (#24)
- Add Spanish, French, German and Portuguese text, `--lang` and a Settings screen (#25)
- Add `g`, `u` and `z` to cycle glyph sets, units and the time mode, and mark a station where AWC's flight category differs from the decoded one (#26)
- Tighten the spacing and footer on short and narrow terminals (#26)
- Add standalone binaries for Windows, Linux and macOS, a wheel, SHA256SUMS and build provenance (#27)
