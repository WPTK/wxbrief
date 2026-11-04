# Changelog

## Unreleased

### Fixed

- Fix the UI screens: hand the keyboard back to the list after a narrow-terminal trip (#255), say "no TAF" in the detail pane and answer keys 1, 2 and 3 when a section is already on screen or a product is missing (#253, #245, #230), pin the station header while the report scrolls (#198), give the demo header "demo sample" instead of an age (#257), make clicks the same in the list and the grid and ignore the other buttons and drags (#232, #249), let a dismissed toast be raised again (#231), restart the offline count when the stations change (#233), add a legend to the grid (#201) and lift theme colours that fell below the contrast floor (#260)

## 0.4.0 - 2026-11-03

### Changed

- Revalidate stored AWC responses with `hishel` (RFC 9111, always asking the server, never reusing on `max-age`) and retry failed requests up to three times with `stamina`'s jittered backoff (#314)
- Use colour-blind-safe IFR and LIFR fills, show the Raw title only when a report is held, offer `d Remove` only with a station selected, and align the list's conditions and the category badge (#275, #276, #277, #278)
- Update the decoded table in place so a refresh keeps the cursor and scroll position (#326)

### Added

- Add the token-by-token view, with each raw token beside its decoded meaning, selectable from the keyboard (#319)
- Add a worst-case row per hour to the TAF timeline, with a raised mark that does not rely on colour (#320)
- Add the Ctrl+P route switcher: type `KDEN KORD KJFK` to add stations and select the first (#321)
- Add `wxbrief.calc`: airport lookup, density altitude, dew point spread and runway wind (#313)

### Fixed

- Warn when a TAF is valid for more than 30 hours or starts a day or more after it was issued, which also catches a 29 February that does not exist (#284)
- Drop a gust that is not above the mean wind, with a warning, in the report body, TAF groups and wind remarks (runway and height winds), and reject an altimeter or QNH outside 20.00-32.00 inHg or 850-1100 hPa, as unrecognised groups (#279, #280)
- Read `Retry-After` as whole seconds or an HTTP date only (#281)
- Warn about `FM` groups out of time order and, with a separate message, a `BECMG` that ends after the valid period (#282)
- Drop pasted Markdown code fences, split two keywordless reports on one line, and read only `PROB30` and `PROB40` as probabilities, so `PROB10`, `PROB20`, `PROB50` and the rest now warn (#286, #287, #289)
- Warn when a remark wind drops its gust, and split the TAF change-order warnings (#318)

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
- Return Esc from the detail pane to the station list, say "can't reach aviationweather.gov" instead of raw error text, and show one time-zone label on a grid card (#209)

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
