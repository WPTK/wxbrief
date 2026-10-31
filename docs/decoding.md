# Decoding

How a raw METAR becomes a `Metar`, what the parser promises, and how to add a test report. The architecture and the
session plan live in [plan.md](plan.md); this page covers the decoder as built in S1.

## Pipeline

```
raw text --tokenize--> Token list --metar.py state machine--> Metar --derived.py--> Metar (+ ceiling, category, flags)
                                                                  \--> render/*  (highlight, phrases, plain, richtext, json)
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
  next token.
* If the driver itself fails, `_failsafe` returns every token as `UNKNOWN` with one warning.
* A report starting with `TAF` is not decoded (S2): one `unsupported_report` warning, tokens kept.
* Regexes use unambiguous alternations (fixed-width codes, no nested repeats), so junk input cannot cause
  catastrophic backtracking. `tests/test_fuzz.py` has a timing test for that.

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
station prefix. Only the body is scored (four-digit numbers in US remarks such as `WSHFT 1715` do not count).

## Tail groups (S2 picks these up)

Between the pressure and `RMK`, S1 only *recognises* groups, so highlighting works and nothing is reported as unknown.
`wxbrief/decode/groups/tail.py` documents the layout:

| Text | Kind |
|---|---|
| `NOSIG` | `TREND` |
| `BECMG`/`TEMPO` and every token after it up to the next trend keyword or `RMK` | `TREND` (a colour-state code inside is `COLOR_STATE`) |
| `RERA`, `RETSRA` ... | `RECENT_WEATHER` |
| `WS ALL RWY`, `WS R24L` | `WIND_SHEAR` |
| `W15/S3` | `SEA_STATE` |
| `BLU`, `YLO2`, `BLACK` ... | `COLOR_STATE` |
| `88290192`, `R24L/290255`, `R06R/CLRD62`, `R/SNOCLO` (not in US-flavor reports) | `RUNWAY_STATE` |
| `RMK` and everything after it | `REMARK` |

`Metar.tail_index` is the index in `Metar.tokens` of the first tail token (`None` without a tail), `Metar.remarks_index`
that of `RMK`; `Metar.tail_tokens` and `Metar.remarks_tokens` slice them (terminator excluded) and
`Metar.remarks_raw` is the verbatim text after `RMK`. Nothing is decoded: S2 adds model objects and replaces the
`TREND`-for-everything tagging where it needs finer kinds.

## Reference time

Reports carry only `DDHHMMZ`. `resolve_day_time(day, hour, minute, reference)` returns the candidate in the previous,
current or next month nearest to `reference` (ties go to the earlier one; hour 24 rolls over; an impossible day or time
gives `None` plus a warning). `parse_metar(raw, reference)` takes the reference; fixtures use the timestamp in the file
name and `wxbrief decode --date YYYY-MM-DD` uses noon UTC of that date (default: now). Times are shown as UTC; station
local time needs the station database (S3).

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
`None`. `tests/test_flightcat.py` checks our category against the AWC `fltCat` of every saved report; genuine
disagreements go in `PARITY_EXCEPTIONS` with a reason (none today).

## Adding a fixture

Fixtures live in `tests/fixtures/reports/<region>/` as a pair: `<ICAO>_<yyyymmddhhmm>[_handwritten-<note>].txt` holding
one raw report, and `<same name>.golden.json` holding `render.jsonout.to_dict` of the decode. The timestamp in the name
is the reference time for the day-of-month group.

1. Real reports come from the AWC API: `https://aviationweather.gov/api/data/metar?ids=KDEN,EGLL&format=json&hours=3`
   with an honest `User-Agent` (`wxbrief-dev/0.1 (+https://github.com/WPTK/wxbrief)`), a few requests at most. Save the
   JSON batch under `tests/fixtures/awc/` (it feeds the flight-category parity test) and write the `rawOb` text and the
   `reportTime` (as `yyyymmddhhmm`) into the fixture file name. Real fixtures must appear in a saved batch: a test checks.
2. Hand-written reports (a group the live data lacks) put `handwritten-<note>` after the timestamp.
3. Generate the golden with `python -m pytest tests/test_goldens.py --update-goldens`, then read it against the raw text:
   `git diff` shows each field. A golden you did not review is not a test. After an intended decoder change, rerun with
   `--update-goldens` and review the whole diff.
4. Files are `-text` in `.gitattributes`; keep LF endings.

## Fuzzing

`tests/test_fuzz.py` runs 2,000 examples per property: arbitrary text, text made of report characters, and real
reports mutated token by token (dropped, duplicated, truncated, garbled, swapped). For each it asserts no exception,
tokens in bounds, ordered and non-overlapping with `raw[start:end].upper() == text`, every non-whitespace character
covered, and that plain, JSON and Rich rendering succeed. `WXBRIEF_FUZZ_EXAMPLES=40000 python -m pytest tests/test_fuzz.py`
searches deeper.

## Units

`UnitsMode` (`us`, `metric`, `mixed`) only affects rendering: the model keeps what the report said. `us` and `metric`
put that system first and keep the reported value in parentheses when it differs; `mixed` (the CLI default) shows the
reported value first and the other system in parentheses. Unit symbols are never translated.
