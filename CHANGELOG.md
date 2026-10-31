# Changelog

## 0.1.0 - 2026-10-31

### Added

- Add the `decode` command with a hand-written METAR and SPECI decoder and plain, colour, Discord and JSON output (#1)
- Decode METAR remarks, trends, colour states, runway state, recent weather, wind shear and sea state (#2)
- Decode TAFs (amendments, cancellations, change groups, temperature extremes) and split pasted blobs into reports (#17)
- Add the `get` command to fetch the latest METAR and TAF from aviationweather.gov, with a polling budget, a disk cache and a config file (#16)
- Add the aviation colorways, flight-category and colour-state colours, and `--theme` for the command line (#20)
- Add the terminal UI with a station list, decoded detail pane, station search, paste-and-decode, clipboard copy and help (#21)
- Add `t` and `T` to change and preview colorways, and remember the choice (#23)
- Add the TAF timeline with a period cursor, the grid layout, `v` to switch layouts and the offline `--demo` (#24)
- Add Spanish, French, German and Portuguese text, `--lang` and a Settings screen (#25)
- Add `g`, `u` and `z` to cycle glyph sets, units and the time mode, and mark a station where AWC's flight category differs from the decoded one (#26)
- Add a layout that stays usable down to 60 columns by 20 rows (#26)
