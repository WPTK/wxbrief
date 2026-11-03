# wxbrief red-team findings: decoders and AWC client

Branch `claude/audit-redteam-ed0969`, audited at `38705ca`. Findings only: nothing under `wxbrief/` was changed and
no issue was filed. (The task text says `src/`; the package lives in `wxbrief/`.)

**Verdict: the decoders and the AWC client are in good shape.** Eight low-severity defects were verified, none above
P3, and none that mis-decodes a well-formed report. 1,292 real reports in the corpus agree with two independent
decoders on temperature, dew point, wind, clouds and altimeter. 3,000+ grammar-built METARs and 1,500 grammar-built
TAFs decode to exactly the facts they were built from. Every finding below is on malformed or implausible input that is
accepted without a warning, or on pasted-text splitting.

## How it was done

- Read: `decode/metar.py`, `taf.py`, `times.py`, `timeline.py`, `flightcat.py`, `split.py`, `groups/{visibility,wind,pressure,tafgroups}.py`, `data/awc.py`, `data/poll.py`; `gh issue list` (all 268 issues) so known items were skipped.
- Grammar: `tests/fuzz/grammar.py` builds METAR/SPECI/TAF text plus the facts it encodes, with the station prefix drawn independently of the unit system.
- Differential: `avwx-engine 1.9.10` and `metar-taf-parser-mivek 1.13.1` in a scratch venv at `%TEMP%\rtvenv`. They are not project dependencies; `tests/fuzz/test_rt_differential.py` skips unless they import (`tests/fuzz/requirements-redteam.txt`).
- Not decoded by the repo, so not tested: PIREP, SIGMET, AIRMET. The CLI and the feed parser take METAR, SPECI and TAF only.
- Determinism: every hypothesis test uses `derandomize=True`, `database=None`. `WXBRIEF_RT_EXAMPLES` (default 400) raises the count.

## Result

```
python -m pytest tests/fuzz -q          195 passed, 1 skipped, 24 xfailed      (14 s)
python -m pytest tests -n 4 -m "not pty" --ignore=tests/uat_realterm
                                        2748 passed, 24 skipped, 30 xfailed    (177 s)
```

30 xfailed = 24 from `tests/fuzz` (strict, ids RT-01..RT-08) + 6 that were already in the suite. The skip is the
differential module, which needs the scratch-venv packages. With the scratch venv: `2 passed`.
Every xfail was also run with `--runxfail` and fails for the reason given below.

## Verified findings

| id | priority / label | where | summary |
|----|------------------|-------|---------|
| RT-01 | P4 `decoder` | `wxbrief/decode/groups/wind.py:11,32` | gust at or below the mean wind accepted, no warning |
| RT-02 | P4 `decoder` `data` | `wxbrief/decode/groups/pressure.py:24-39` | impossible pressure (`A0000`, `A9999`, `Q0000`, `Q9999`) accepted, no warning |
| RT-03 | P4 `data` | `wxbrief/data/awc.py:71` | `Retry-After` read with `float()`: `1e3`, `1_0`, `+5`, `.5` are honoured |
| RT-04 | P4 `decoder` | `wxbrief/decode/taf.py:293-300` | `FM` groups out of time order, and a `BECMG` window ending after the valid period, are not warned |
| RT-05 | P3 `decoder` | `wxbrief/decode/taf.py:142-158`, `times.py:112` | TAF valid period of 72 h, or starting 14 days after issue, accepted silently |
| RT-06 | P4 `ui` `decoder` | `wxbrief/decode/split.py:92,164` | a pasted Markdown fence becomes two junk "reports" |
| RT-07 | P4 `decoder` | `wxbrief/decode/split.py:92` | two reports on one line without `METAR`/`SPECI`/`TAF` become one; the second is lost as unknown tokens |
| RT-08 | P4 `decoder` | `wxbrief/decode/groups/tafgroups.py:42,133` | `PROB10`, `PROB50`, `PROB90` accepted; Annex 3 has `PROB30` and `PROB40` only |

RT-05 is the only P3: a TAF whose valid period is wrong by weeks still gets a green timeline and a "valid" badge, so
the expiry logic (#88, #186) works from a wrong end time.

### RT-01 wind gust not above the mean wind

- Raw: `KDEN 311853Z 18012G10KT 10SM CLR 12/10 A2992`
- Expected: a warning, or the gust dropped. FMH-1 and Annex 3 report a gust only when it exceeds the mean speed (by 10 kt for a US report).
- Actual: `Wind(direction=180, speed=12 KT, gust=10 KT)`, `Flag.GUSTS` set, `warnings == ()`. Same for `G12`, `G00`.
- Test: `tests/fuzz/test_rt_traps.py::test_rt01_a_gust_not_above_the_mean_wind_is_flagged[18012G10KT]`
- Output with `--runxfail`: `assert (() or Speed(value=10, unit=KT) is None)` fails.

### RT-02 impossible pressure accepted

- Raw: `KDEN 311853Z 18012KT 10SM CLR 12/10 A0000` (also `A9999`, `A0100`, `Q0000`, `Q0001`, `Q9999`)
- Expected: a warning or no altimeter; plausible range is roughly 27.00 to 32.00 inHg and 850 to 1090 hPa.
- Actual: `altimeters=(Pressure(0.0 INHG),)` / `(Pressure(99.99 INHG),)` / `(Pressure(0 HPA),)`, no warning. The value reaches the display and the Discord text.
- Test: `test_rt02_an_impossible_pressure_is_not_accepted_silently[A0000]`

### RT-03 Retry-After is parsed with float()

- Payload: `HTTP/1.1 429` with `Retry-After: 1e3` (or `1_0`, `+5`, `.5`, `5.`)
- Expected: RFC 9110 allows `1*DIGIT` or an HTTP date. Anything else gets `DEFAULT_RETRY_AFTER` (60 s). The code already rejects `nan`, `inf` and `1e999`, so the intent is clear.
- Actual: `1e3` gives 1000 s, `1_0` gives 10 s, `+5` gives 5 s. Harmless in practice (the wait is capped at 3600 s and a real server sends digits), so P4.
- Test: `tests/fuzz/test_rt_awc.py::test_rt03_retry_after_is_delta_seconds_or_an_http_date_only[1e3]`
- Output: `assert 1000.0 == 60.0`.

### RT-04 TAF change groups outside order or outside the valid period

- Raw A: `TAF KDEN 312320Z 0100/0124 18010KT P6SM SCT050 FM011200 18010KT FM010600 18005KT`
  Decoded: BASE ends 12:00, FM 12:00 to 00:00, FM 06:00 to 00:00. `warnings == ()`. The second FM starts before the first.
- Raw B: `TAF KDEN 312320Z 0100/0103 18010KT P6SM SCT050 BECMG 0102/0104 BKN010`
  Decoded: BECMG 02:00 to 03:00, `becoming_end` 04:00, one hour past the valid period. `warnings == ()`. `_check_inside_period` only tests the group *start*.
- Expected: `outside_period` (or a new code) for both.
- Tests: `test_rt04_fm_groups_out_of_time_order_are_warned`, `test_rt04_becmg_window_ending_after_the_valid_period_is_warned`

### RT-05 implausible TAF valid period

- Raw A: `TAF KDEN 012320Z 0200/0500 ...` issued 2026-11-01: valid 2026-11-02 00:00 to 2026-11-05 00:00 (72 h; Annex 3 allows 30 h at most). No warning.
- Raw B: `TAF KDEN 012320Z 1500/1600 ...`: valid from 2026-11-15, 14 days after issue. No warning.
- Raw C: `TAF KDEN 282320Z 2900/0106 ...` issued 2027-02-28 (no 29 Feb 2027): resolved to 2027-03-29 to 2027-04-01. No warning.
- Expected: a warning when the span exceeds 30 h, or the start is more than about a day after the issue time. `resolve_day_time_after` allows a 7-day horizon (`times.py:112`) and `resolve_day_time` picks the nearest month with no bound.
- Tests: `tests/fuzz/test_rt_time.py::test_rt05_an_implausible_valid_period_is_warned[...]` (three parameters)

### RT-06 a Markdown fence is decoded as reports

- Raw: ```` ```\nKDEN 311853Z 18012KT 10SM CLR 12/10 A2992\n``` ````
- Expected: one report. The fence lines are not weather.
- Actual: `parse_any` returns three `Metar` objects; two are the bare fences with `station=None`. Pasting a Discord message back into the paste screen shows them. (#46 fixed the copy side only.)
- Test: `tests/fuzz/test_rt_traps.py::test_rt06_a_pasted_markdown_fence_is_not_a_report`
- Output: `assert 3 == 1`.

### RT-07 two reports on one line without keywords

- Raw: `KDEN 311853Z 18012KT 10SM CLR 12/10 A2992 KJFK 311851Z 18012KT 10SM CLR 12/10 A2992`
- Expected: two reports, KDEN and KJFK. The `split.py` docstring splits mid-line only at `METAR`/`SPECI`/`TAF`, so this is a documented limit, not a regression.
- Actual: one `Metar` for KDEN; `KJFK 311851Z 18012KT 10SM CLR 12/10` are six `unknown_token` warnings. The user sees warnings but not a second station.
- Test: `test_rt07_two_reports_on_one_line_without_keywords_are_two_reports`

### RT-08 PROB groups other than 30 and 40

- Raw: `TAF KDEN 312320Z 0100/0124 18010KT P6SM SCT050 PROB50 0112/0118 TSRA`
- Expected: a warning. Decoded as `PROB 50`, no warning. `_PROB = ^PROB(\d{2})$` (`tafgroups.py:42`) takes any two digits, and `starts_change_group` takes `PROB[1-9]0`.
- Tests: `test_rt08_only_prob30_and_prob40_exist[PROB10|PROB50|PROB90]`

## Checked and correct (regression tests added)

- **Tokens beat station prefixes**: `SM`/`A####` on K, P, C, E, R and U stations read as miles and inHg; metres/`Q####` on K and C stations read as metres and hPa; `CAVOK` is 10 km everywhere. 7 stations by 2 unit systems.
- **NATO colour states** `BLU WHT GRN YLO YLO1 YLO2 AMB RED` on K, E, C stations: parsed, `military=True`, no warnings. `BLACK` alone is a closed state with no colour; `BLACKBLU` keeps both. A station called `KRED` is not a colour.
- **T-group** (`T01231045` = 12.3 / -4.5, both sign digits, `T00000000`): exact. The body `12/M05` stays as reported; the T-group is its own remark (Discord output prefers it).
- **6-hour extremes** `1sTTT`/`2sTTT`, **24-hour** `4TTTTTTTT`, **tendency** `5appp` (a = 0 to 8, 99.9 hPa), **SLP###** (`SLP000` is 1000.0, `SLP499` is 1049.9, `SLP500` is 950.0, `SLP982` is 998.2, `SLPNO`), **PK WND** with and without hour, **WSHFT** with `FROPA`, **FZRANO/TSNO/RVRNO/PNO/PWINO/VISNO/CHINO**, **`$`**, **RERA/RETS/REFZRA**.
- **Flight category**: only `BKN`, `OVC`, `VV` set a ceiling; `FEW002 SCT004` is VFR; `OVC000` and `VV002` are LIFR; the lowest layer wins in any order; `BKN///` gives no badge. Fractions `M1/4SM`, `1/2SM`, `1 1/2SM`, `2 3/4SM`, `P6SM`; boundaries at 1, 3, 5 SM and 500, 1000, 3000 ft; metres via 1609.34 (`1609` LIFR, `1610` IFR, `4828/4829`, `8046/8047`).
- **TAF inheritance**: `TEMPO`/`PROB` inherit wind, visibility and cloud they do not state and replace the whole cloud list when they state one; `BECMG` merges over the prevailing state; `FM` does not inherit; a `CAVOK` base under a `TEMPO` visibility is spelled out as 10 km, no weather, no cloud.
- **Day-first DDHHMMZ**: `312355Z` read on the 1st is the 31st of the previous month; across year end; `292355Z` read on 1 March 2028 is 29 Feb 2028 and on 1 March 2027 is 29 Jan 2027; `312355Z` on 1 May is 31 March (no 31 April); hour `24`; day `00`/`32` and minute `60` warn. A property test over 2000 to 2040 shows any report up to 27 days old resolves to the exact instant.
- **DST and zones**: references in `America/New_York` and `Europe/London` at the spring-forward gap and both folds of the fall-back hour, and a fixed -05:00 offset, give the same result as the same instant in UTC. A naive reference is read as UTC (documented).
- **AWC client**: 204 with and without a body, 204 with a JSON content type, BOM `[]` all return `[]`. 429 with absent, empty, `0`, negative, `nan`, `inf`, huge, text, list and padded values returns `RateLimited` bounded to 0 to 3600 s; an HTTP date in the past or naive never goes negative; a future date is honoured. Empty 200, whitespace, `null`, `{}`, HTML, truncated JSON, 100,000 nested `[`, a 10,000-digit number, Latin-1 bytes, 400, 404 and 301 all raise `ClientError`, never `JSONDecodeError`. The same statuses over real TLS through the repo's fake AWC (`FaultProxy`: `204`, `429:42`, `empty200`, `badjson`, `502`, `drop:20`) behave the same.
- **Poller**: `RateLimited(0)` does not hammer the server; `backoff_delay` still applies to the failing track.
- **Differential**: 1,292 corpus reports against mivek: temperature, dew point, wind speed, direction, gust, cloud layers agree. Only differences were mivek's (`COR` before the station, `R06/000062` runway state) and one report that carries both `Q1023` and `A3024` (1023 vs 1024 hPa, consistent). avwx's flight rules disagree on `VV000` and on `CAVOK` with MPS wind; wxbrief matches the FAA rule there.

## Ideas that did not reproduce, or are judgement calls

- **200 with an empty body** raises `ClientError("response is not JSON")` rather than returning `[]`. I could not confirm that the live AWC ever answers that way (its documented empty answer is 204), so it is not filed. If it does, the user sees an offline-style error instead of "no reports".
- **`M00` temperature** loses its sign (`Temperature(0)`); FMH-1 means -0.5 to 0. Deliberate (`tests/test_phrases_tail.py:551`) and the T-group carries the sign, so not filed. No freezing flag is derived from the body temperature.
- **`010305Z` read at 23:58 on the 31st** resolves to 1st of the same month (30 days earlier): 3 h 7 min ahead of the reference is just past `FUTURE_TOLERANCE` (3 h). By design (#53); mentioned for the edge.
- **Remarks left as free text** (not an error): `SFC VIS M1/4`, `VIRGA SW`, `DSNT TS SW MOV E`, `FEW V SCT`, `TCU SW`, `931RRR` snowfall, `WND 18V24`, `TORNADO B1355 5 NE MOV E`. All reach the output verbatim.
- **Station `BLU`** (three letters, no ICAO prefix) is read as a colour state. Not a real station.
- **`27100KT`** is read as 271 degrees at 0 kt. A 3-digit speed needs `270100KT`; malformed input.
- **Year rollover with a stale reference**: reading `312355Z` against a reference two months old gives the right 31st; there is no failure mode found there.
- **Fuzz for crashes** was already covered by `tests/test_fuzz.py` and `tests/test_hypothesis_feeds.py`; nothing new surfaced when the grammar was run through `render_plain` (not added, to avoid duplication).

## FMH-1 / ICAO Annex 3 compliance

| Item | Status | Note |
|------|--------|------|
| Report type METAR / SPECI / COR / AUTO / NIL | pass | |
| Station, DDHHMMZ, hour 24, impossible stamps | pass | month/year/leap resolution checked |
| Wind direction, speed, VRB, calm, 3-digit speed | pass | `P49KT` above-limit flag too |
| Wind gust must exceed mean wind | **fail** | RT-01 |
| Wind variation `dddVddd` | pass | |
| Visibility SM with fractions, `M`/`P` prefixes | pass | |
| Visibility metres, `9999`, `0000`, minimum / `NDV` | pass | |
| `CAVOK` | pass | spelled out as 10 km, no weather, no cloud |
| RVR (`R04R/P2000N`, `V` ranges, `FT`/`M`, `U/D/N`) | pass | |
| Present weather: intensity, descriptors, phenomena, `VC` | pass | sampled, not exhaustive |
| Sky cover, `VV`, `CB`/`TCU`, `///` heights, `NSC`/`NCD`/`SKC`/`CLR` | pass | |
| Ceiling = lowest `BKN`/`OVC`/`VV` | pass | |
| Temperature / dew point, `M` prefix, missing `//` | pass | `M00` sign lost, see above |
| Altimeter `A####`, `Q####`, `QNH####INS` | pass | |
| Altimeter plausibility | **fail** | RT-02 |
| Trend `NOSIG`, `BECMG`, `TEMPO`, `FM`, `TL`, `AT` | pass | corpus goldens |
| NATO colour states incl. `BLACK`, `+`, forecast changes | pass | |
| Runway state, wind shear `WS RWY`, sea state | pass | |
| Remarks: `AO1/AO2`, `SLP`, `T`, `1/2/4/5/6/7`, `P`, `PK WND`, `WSHFT`, sensor `NO` | pass | |
| Remarks: `931RRR` snowfall, `VIRGA`, sector `CB`/`TCU`/`ACSL` | not implemented | kept as free text |
| TAF header, `AMD`/`COR`/`CNL`/`NIL`, valid period | pass | |
| TAF valid period at most 30 h | **fail** | RT-05 |
| TAF `FM`, `BECMG`, `TEMPO` inside the valid period, in order | **fail** | RT-04 (start checked, end and order not) |
| TAF `PROB30` / `PROB40` only | **fail** | RT-08 |
| TAF `TX`/`TN`, `QNH`, icing `6`, turbulence `5`, `WS` | pass | |
| Retry and rate-limit handling of the AWC API (204, 429, bad body) | pass | RT-03 aside |
| PIREP, SIGMET, AIRMET | not implemented | out of scope for wxbrief |

## Reproducing

```bash
python -m pytest tests/fuzz -q -p no:cacheprovider            # 195 passed, 1 skipped, 24 xfailed
python -m pytest tests/fuzz --runxfail -q --tb=short          # shows each finding failing
# differential, with the scratch venv:
PYTHONPATH=. <venv>/Scripts/python -m pytest tests/fuzz/test_rt_differential.py -q -p no:cacheprovider
```

Files added: `tests/fuzz/{grammar,test_rt_grammar,test_rt_traps,test_rt_time,test_rt_awc,test_rt_differential}.py`,
`tests/fuzz/requirements-redteam.txt`, `audit/redteam-findings.md`.
