# Decoding

How a raw METAR becomes a `Metar`, what the parser promises, and how to add a test report. The architecture and the
session plan live in [plan.md](plan.md); this page covers the decoder as built in S1 (the body) and S2a (the tail and the
remarks). TAF decoding arrives in S2b.

## Pipeline

```
raw text --tokenize--> Token list --metar.py state machine--> Metar --derived.py--> Metar (+ ceiling, category, flags)
                          |  body groups      groups/*.py                              \--> render/*  (highlight, phrases, plain, richtext, json)
                          |  tail groups      groups/tail.py -> trend, colorstate, runwaystate, recentwx, windshear, seastate
                          \  after RMK        remarks.py
```

Everything under `wxbrief/decode/` is language-neutral: enums, numbers and aware datetimes, no English words.
`decode/tables.py` maps codes to catalog keys (`wx.phenomenon.RA`); `render/phrases.py` is the only module that turns
keys into sentences.

## Tokenizer

`tokenize(raw)` splits on whitespace (`re.finditer(r"\S+")`), so `Token.start`/`Token.end` index the original string and
`raw[start:end].upper() == text`. A trailing `=` (the report terminator) is split into its own `TERMINATOR` token.
Every non-whitespace character belongs to exactly one token; the highlighter and the fuzz test rely on that.

`Cursor` walks the tokens: `peek(offset)`, `take(kind)`, `mark()`, `reset(mark)`. `take` tags the token with a
`SemanticKind`; `reset` rewinds the position and forgets the tags, so a group parser can back out of a partial match
(`1 1/2SM` needs two tokens).

## The never-raise contract

`parse_metar(raw, reference)` never raises, whatever it is given.

* Each group parser runs inside a guard. A parser that fails (or has a bug) rewinds, counts as "no match", and adds a
  `parser_error` warning; the next candidate section gets the token.
* A token no section accepts becomes `UNKNOWN` with an `unknown_token` `ParseWarning` and parsing continues with the
  next token. A trend body that cannot place one of its tokens does the same for that token only and carries on.
* The remarks driver (`remarks.py`) cannot reject a token: whatever no pattern claims becomes `FreeText`. If it fails
  outright, the remaining tokens stay plain `REMARK` tokens and one `parser_error` warning is added.
* If the driver itself fails, `_failsafe` returns every token as `UNKNOWN` with one warning.
* A report starting with `TAF` is not decoded (S2b): one `unsupported_report` warning, tokens kept.
* Regexes use unambiguous alternations (fixed-width codes, no nested repeats), so junk input cannot cause
  catastrophic backtracking. The one repeating shape, weather timing (`DZB04E37RAB37`), is scanned in explicit steps.
  `tests/test_fuzz.py` has a timing test over long runs of group-like text, including every tail and remark shape.

`ParseWarning.code` is a stable id (`unknown_token`, `invalid_day`, `invalid_time`, `parser_error`,
`unsupported_report`); `render/phrases.describe_warning` turns it into text through the catalog.

## Section order and tolerance

Sections: type, station, time, wind, wind variation, visibility, then RVR/weather/sky in any order, temperature and
dew point, pressure, then the tail. A token is offered to the current section and every later one, so missing groups
are skipped. A token for an earlier section (a second wind group, say) is unknown, except modifiers (`AUTO`, `COR`,
`NIL`, ...), which may appear anywhere up to the pressure (`METAR COR EGLL 311020Z`).

A four-character word is only taken as the station when a day/time group follows it, when it follows `METAR`/`SPECI`, or
when it is the only token; otherwise `THIS IS NOT A REPORT` would report a station called `THIS`.

`detect.py` scores flavor (US, ICAO, mixed, unknown) and the `military` flag from the tokens themselves, never from the
station prefix. Only the body is scored (four-digit numbers in US remarks such as `WSHFT 1715` do not count). A colour
state in the remarks (`RMK YLO1 YLO1`, as RAF stations send it) also sets `military` once the remarks are decoded.

## Tail groups

Between the pressure and `RMK`, `groups/tail.py` offers each token to the group parsers in turn; the first that
recognises it decodes one group and tags its tokens. `Metar.tail_index` is the index in `Metar.tokens` of the first
tail token (`None` without a tail), `Metar.tail_tokens` slices them (terminator excluded).

| Group | Parser | Model on `Metar` | Token kinds |
|---|---|---|---|
| `NOSIG`, `BECMG ...`, `TEMPO ...` | `trend.py` | `trends: tuple[Trend]` | keyword and `FM`/`TL`/`AT` times `TREND`; body elements `WIND`, `VISIBILITY`, `WEATHER`, `SKY`, `COLOR_STATE`; a token the body cannot place `UNKNOWN` |
| `BLU`, `BLU+`, `YLO1 YLO1`, `GRN WHT TEMPO GRN`, `BLACKRED`, `///` | `colorstate.py` | `color_state: ColorStateGroup`, `computed_color_state` | `COLOR_STATE`; `BECMG`/`TEMPO` inside the group `TREND` |
| `R24L/290255`, `R06R/CLRD62`, `88290192`, `R/SNOCLO` | `runwaystate.py` | `runway_states: tuple[RunwayState]` | `RUNWAY_STATE` |
| `RERA`, `RETSRA`, `RESHRA` | `recentwx.py` | `recent_weather: tuple[RecentWeather]` | `RECENT_WEATHER` |
| `WS ALL RWY`, `WS R24L`, `WS RWY 24L` | `windshear.py` | `wind_shear: tuple[WindShearRunway]` | `WIND_SHEAR` |
| `W15/S3`, `W15/H10` | `seastate.py` | `sea_state: SeaState` | `SEA_STATE` |

**Trends.** A trend body is read left to right with the same parsers as the report body: time qualifiers (`FM1130`,
`TL1230`, `AT1200`, kept as hour and minute and resolved to the occurrence nearest the observation, hour 24 rolling
over), then wind, visibility or `CAVOK`, weather or `NSW`, sky and a colour state. The elements land in
`ForecastElements` (`wind`, `visibility`, `weather`, `sky`, `color_state`; anything empty means unchanged), the same
shape a TAF period will use. The body ends at the next trend keyword, `RMK`, the terminator, or a token that begins
another tail group (`RESHRA`, `WS`, a sea or runway state). A second wind or colour in one body is `UNKNOWN`.

**Colour-state groups.** A group is the current state followed by forecast states: a bare code expects that state,
`BECMG`/`TEMPO` before a code qualify it (`GRN WHT TEMPO GRN` is Green, then White expected, temporarily Green). A trend
keyword belongs to the colour group only when a colour code follows it, so `BLU TEMPO YLO` is one group while
`BLU TEMPO 5000 -RA` is a group and a weather trend. A group may begin with a keyword (`TEMPO YLO`, `current` is
`None`). `BLACK` before a code means the airfield is closed for non-weather reasons; a bare `BLACK` has `code=None`.
`///` in the colour position (German AUTO reports: `... Q1033 ///`, accepted only after the pressure) is a state that was not reported. The `+` suffix
(`BLU+`, seen on Bundeswehr reports) is kept as `plus`; its meaning is not defined in the NATO tables we could find,
so it is displayed as reported and not interpreted. RAF and Dutch stations differ in position: UK military reports
put the group after `RMK`, where `remarks.py` parses it with the same function (`ColorStateRemark`) and the decoder
copies it to `Metar.color_state`.

**Runway state.** `R24L/290255` is runway, then six characters: deposit (`0` clear and dry ... `9` frozen ruts),
extent (`1` up to 10 %, `2` 11-25 %, `5` 26-50 %, `9` 51-100 %), depth (`00` under 1 mm, `01`-`90` mm, `92`-`97`
10-35 cm, `98` 40 cm or more, `99` runway not operational, `//` not significant), braking (`00`-`90` coefficient,
`91`-`95` poor to good, `99` unreliable). `/` means not reported (`None` in the model). Runway 88 is all runways,
99 a repeat of the previous report. The older eight-digit form (`88290192`) is the same six characters behind a
two-digit runway (`51`-`86` is the right-hand runway `01R`-`36R`); `R06R/CLRD62` means contamination cleared with
braking 0.62; `R/SNOCLO` and `SNOCLO` mean the aerodrome is closed by snow. These forms are only looked for in
non-US reports (the same token in a US-flavour report stays unknown).

**Recent weather.** `RE` plus a weather group, read in two-letter steps (`RETSRA` is a thunderstorm with rain that has
ended since the last report). **Wind shear:** `WS` needs `ALL RWY` or at least one runway; a bare `WS` is unknown.
**Sea state:** `W15/S3` is a water temperature and a state-of-sea code 0-9 (WMO 3700), `W15/H10` a wave height in
decimetres.

## Remarks

`remarks.py` decodes everything after `RMK` into `Metar.remarks: tuple[Remark]` (`Metar.remarks_raw` still holds the
verbatim text and `Metar.remarks_tokens` the tokens). The driver offers each position to the parsers in order; the first
that recognises a group decodes it and tags its tokens (`PRESSURE` for `SLP177` and `53011`, `TEMPERATURE` for the
T-group and the 6- and 24-hour extremes, `WIND` for `PK WND`, `VISIBILITY`, `WEATHER` for lightning, timing and
precipitation amounts, `SKY` for ceilings and cloud groups; plain codes such as `AO2` and `$` stay `REMARK`).
Consecutive tokens nobody claims form one `FreeText` remark. `Metar.remarks_of(SeaLevelPressure)` selects a variant.

| Group | Variant | Notes |
|---|---|---|
| `AO1`, `AO2` | `AutomatedStationType` | `AO2` has a precipitation discriminator |
| `PK WND 28045/1547` | `PeakWind` | direction, speed, time (`RemarkTime`: minute, optional hour) |
| `WSHFT 1715`, `WSHFT 30 FROPA` | `WindShift` | `frontal_passage` |
| `TWR VIS 2`, `SFC VIS 3/4` | `TowerVisibility`, `SurfaceVisibility` | statute miles, `1 1/2` is two tokens |
| `VIS 3/4V1 1/2` | `VariableVisibility` | |
| `VIS NE 2 1/2`, `VIS 3/4 RWY11` | `SectorVisibility` | |
| `FRQ LTG CG NE`, `OCNL LTGICCG OHD` | `Lightning` | frequency, types, trailing location words |
| `RAB07E45`, `TSB0159E30`, `DZB04E37RAB37` | `WeatherTiming` | one `TimingSegment` per weather type |
| `CIG 013V017`, `CIG 017 RWY11` | `VariableCeiling`, `SecondaryCeiling` | |
| `PRESRR`, `PRESFR` | `PressureRapidChange` | |
| `SLP177`, `SLPNO` | `SeaLevelPressure` | 5xx-9xx are 95x-99x hPa, 0xx-4xx are 100x-104x |
| `P0003`, `60009`, `70015` | `HourlyPrecipitation`, `PeriodPrecipitation`, `DailyPrecipitation` | inches; `0000` is a trace; the period is 6 h at 00/06/12/18Z and 3 h at 03/09/15/21Z |
| `T02330200` | `PreciseTemperature` | tenths of a degree, sign digit first |
| `10233`, `20189` | `MaxTemperature6Hour`, `MinTemperature6Hour` | the leading digit is the kind (1 max, 2 min), not a duration |
| `400461006` | `DailyTemperatureExtremes` | |
| `53011` | `PressureTendency` | character 0-8, net direction, change in hPa |
| `RVRNO`, `PWINO`, `PNO`, `FZRANO`, `TSNO`, `VISNO RWY11`, `CHINO` | `SensorStatus` | |
| `$` | `MaintenanceIndicator` | |
| `4/012`, `SNINCR 2/10` | `SnowDepth`, `SnowIncrease` | inches |
| `8/208` | `CloudTypes` | low, middle and high cloud type codes |
| `GR 1 3/4`, `GR LESS THAN 1/4` | `HailSize` | |
| `DENSITY ALT 2500FT` | `DensityAltitude` | |
| `SC5AC2`, `AC1 AC TR` | `CloudOpacity` | Canadian layers by type and eighths; `TR` is a trace |
| `A3007`, `A30.06` | `AltimeterSetting` | Asian stations add it to ICAO reports |
| `QFE756/1008`, `QNH766` | `StationPressure` | Russian reports, mmHg and/or hPa |
| `RWY17L 02008KT`, `R06/31003MPS` | `RunwayWind` | |
| `WIND 2600FT 19040KT` | `WindAtHeight` | Norwegian reports |
| `RED BECMG AMB` | `ColorStateRemark` | UK military, same grammar as the tail |
| anything else | `FreeText` | |

Context: the period of the `6RRRR` group needs the report time (`remarks.synoptic_hour` rounds to the nearest hour, so
a `:56` report belongs to the next hour); everything else is read from the tokens alone. A malformed group (an hour of
25 in a timing, `SLP17`, `59000`) is not decoded and stays free text.

`FreeText` is shown with the words the catalog knows spelled out (`DSNT NE-E` becomes "distant northeast to east";
`B25` and `E1230` become begin and end times). Words it does not know are shown as written, and the plain decode lists
them in a "Remarks (not decoded)" row, so that row only appears when something stayed undecoded.

### Adding a remark variant

1. Add a frozen dataclass subclassing `Remark` in `decode/model.py`.
2. Add a parser `_name(cur, _ctx) -> Remark | None` in `decode/remarks.py`: peek, return `None` without consuming when the
   shape does not match, otherwise `take` each token with the right `SemanticKind` and return the variant. Put it in
   `_PARSERS` before any parser that could claim the same token.
3. Add the sentence: a `case` in `phrases.describe_remark`, with keys under `[remark]` in `locales/en.toml`, then
   `python scripts/gen_keys.py`. Reuse `measure.py` for numbers.
4. Add a row to `CASES` in `tests/test_remarks.py` (a test fails until every variant has one) and a sentence in
   `tests/test_phrases_tail.py`; add a real or hand-written fixture and regenerate the goldens.

## Colour states

The thresholds are in `decode/colorstate.py`; `computed_color_state(ceiling_ft, visibility_m)` returns the best state
whose cloud-base and visibility minimums both hold (the worse of the two decides, a value exactly on a minimum earns the
better state):

| State | Cloud base (ft) | Visibility (m) |
|---|---|---|
| `BLU` | 2,500 | 8,000 |
| `WHT` | 1,500 | 5,000 |
| `GRN` | 700 | 3,700 |
| `YLO1` | 500 | 2,500 |
| `YLO2` | 300 | 1,600 |
| `AMB` | 200 | 800 |
| `RED` | below AMB | below AMB |

Source: the UK Met Office colour state register (https://reference.metoffice.gov.uk/aviation/UKAerodromeColourStates,
entries `BLU` to `RED`) and the table in the Wikipedia article "Colour state" give these figures. The metar-taf-decode
reference file `international.md` lists `YLO1` as 700 ft / 3.7 km, which would collide with `GRN`; that is not what the
register says. 47 saved military reports from German, Dutch and UK fields carry a colour state and all 47 recompute to
the reported colour with this table (`tests/test_colorstate.py`), including both yellows.

Notes: plain `YLO` is the single yellow of older tables and has the `YLO2` minimums (it matches a computed `YLO1` or
`YLO2`). The "ceiling" is the lowest broken, overcast or vertical-visibility layer; the UK register counts scattered
cloud (3/8 or more) as the lowest significant layer, so a UK field with `SCT` below 2,500 ft can report a worse colour
than we compute. `Metar.computed_color_state` is filled only when the report carries a colour state; the plain decode
shows it as "Color state (computed)" when it differs from the reported one or the report gave none (`///`).

## Flags

`derived.compute_flags` adds, to the S1 set: `WIND_SHEAR` (a `WS` group), `COLOR_BELOW_GRN` (the current reported state
is `YLO`, `YLO1`, `YLO2`, `AMB` or `RED`), `RAPID_PRESSURE_CHANGE` (`PRESRR`/`PRESFR`), `RUNWAY_CONTAMINATED` (a runway
state that is not cleared and has frost, snow, slush, ice, compacted snow or frozen ruts, or `SNOCLO`; wet and damp do
not count), `MAINTENANCE` (`$`), `VOLCANIC_ASH` (`VA` in present weather, recent weather or a trend) and
`MISSING_DATA` (a sensor-out remark, `SLPNO`, `//` weather, `////` visibility, an unspecified wind speed or a cloud
layer with an unknown amount or height).

## Reference time

Reports carry only `DDHHMMZ`. `resolve_day_time(day, hour, minute, reference)` returns the candidate in the previous,
current or next month nearest to `reference` (ties go to the earlier one; hour 24 rolls over; an impossible day or time
gives `None` plus a warning). `parse_metar(raw, reference)` takes the reference; fixtures use the timestamp in the file
name and `wxbrief decode --date YYYY-MM-DD` uses noon UTC of that date (default: now). Times are shown as UTC; station
local time needs the station database (S3). Trend times (`FM1130`) have no day: `resolve_clock_time` picks the
yesterday, today or tomorrow that puts them nearest the observation.

## Flight category

`flightcat.py` follows paragraph `700-FLIGHT-RULES` of the COBOL decoder:

| | ceiling | visibility |
|---|---|---|
| LIFR | below 500 ft | below 1 SM |
| IFR | below 1,000 ft | below 3 SM |
| MVFR | up to 3,000 ft | up to 5 SM |
| VFR | otherwise | otherwise |

The ceiling is the lowest broken, overcast or vertical-visibility layer with a known height. Metres convert at 1609.34;
`9999` and `CAVOK` count as 10 SM. If one component is missing the category comes from the other; with neither, it is
`None`. A sky made only of `//////` placeholders says nothing (it is not a clear sky), while `FEW`, `SCT` and the
clear-sky codes leave no ceiling.

`tests/test_flightcat.py` checks our category against the AWC `fltCat` of every saved report (1,248 reports in five
batches). Genuine disagreements are covered by named rules in `PARITY_RULES`, each with its reason, and a test fails if
a rule covers no report or hides an agreement: AWC gives no category for German AUTO reports whose sky is `//////`
(we classify from the visibility alone, as the missing-component rule says) and for the `9999NDV` reports of Greenland.

## Cross-check against AWC's fields

`tests/test_awc_crosscheck.py` compares the decoded remarks with the structured fields AWC publishes for the same
report: `slp`, `presTend`, `maxT`, `minT`, `maxT24`, `minT24`, `precip`, `pcp6hr`, `pcp3hr`, `pcp24hr`, `snow`, the
T-group against `temp`/`dewp`, and the present-weather groups against `wxString`. They agree on every saved report
except the cases in `EXCEPTIONS`, each investigated: Norwegian `RMK WIND 2600FT 19040KT` reports for which AWC invents
`maxT`/`minT`, a pressure tendency of 0.0 hPa that AWC leaves empty, and AWC adding a recent `RESHRA` to `wxString`.
`pcp3hr`, `pcp24hr` and `snow` were not populated in any saved batch, so those decoders are covered by unit tests only.

## Adding a fixture

Fixtures live in `tests/fixtures/reports/<region>/` as a pair: `<ICAO>_<yyyymmddhhmm>[_handwritten-<note>].txt` holding
one raw report, and `<same name>.golden.json` holding `render.jsonout.to_dict` of the decode. The timestamp in the name
is the reference time for the day-of-month group. Regions so far: `us`, `canada`, `uk` (civil and RAF), `france`,
`germany` (civil and military), `netherlands`, `norway`, `russia`, `india`, `japan`, `australia`, `brazil`,
`antarctica` and `world`.

1. Real reports come from the AWC API: `https://aviationweather.gov/api/data/metar?ids=KDEN,EGLL&format=json&hours=3`
   with an honest `User-Agent` (`wxbrief-dev/0.1 (+https://github.com/WPTK/wxbrief)`), a few requests at most. Save the
   JSON batch under `tests/fixtures/awc/` (it feeds the flight-category parity test and the AWC cross-check) and write
   the `rawOb` text and the `reportTime` (as `yyyymmddhhmm`) into the fixture file name. Real fixtures must appear in a
   saved batch: a test checks.
2. Hand-written reports (a group the live data lacks) put `handwritten-<note>` after the timestamp.
3. Generate the golden with `python -m pytest tests/test_goldens.py --update-goldens`, then read it against the raw text:
   `git diff` shows each field. A golden you did not review is not a test. After an intended decoder change, rerun with
   `--update-goldens` and review the whole diff.
4. Files are `-text` in `.gitattributes`; keep LF endings.

## Fuzzing

`tests/test_fuzz.py` runs 2,000 examples per property: arbitrary text, text made of report characters, real
reports mutated token by token (dropped, duplicated, truncated, garbled, swapped), and a random run of remark tokens of
every shape after `RMK`. For each it asserts no exception, tokens in bounds, ordered and non-overlapping with
`raw[start:end].upper() == text`, every non-whitespace character covered, and that plain, JSON and Rich rendering
succeed. `WXBRIEF_FUZZ_EXAMPLES=40000 python -m pytest tests/test_fuzz.py` searches deeper.

## Units

`UnitsMode` (`us`, `metric`, `mixed`) only affects rendering: the model keeps what the report said. `us` and `metric`
put that system first and keep the reported value in parentheses when it differs; `mixed` (the CLI default) shows the
reported value first and the other system in parentheses. Unit symbols are never translated. Remarks use the same
modes: precipitation, snow and hail in inches, runway deposit depth in millimetres, pressures in hPa (sea-level pressure
and tendencies keep their tenth).

## Known limits

* Temperatures and times stay UTC / as reported until the station database (S3).
* Only English phrases exist (S7 adds es, fr, de, pt); `FreeText` word decoding is English-only.
* `933RRR` (water equivalent of snow), `931SSS`, `I1xxx` ice accretion and other additive groups not listed above
  stay `FreeText`; the plain decode lists them under "Remarks (not decoded)".
* Trend and colour-state groups are read from METAR reports only; forecasts are S2b.
