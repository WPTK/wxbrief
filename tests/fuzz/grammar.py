"""Hypothesis grammar for well-formed METAR/SPECI/TAF text, with the ground truth each draw was built from.

Every strategy returns a ``Draw``: the report text plus a dict of the facts that were encoded in it. Property tests
compare the decoder's output with those facts, so the oracle is the grammar itself, not another decoder.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hypothesis import strategies as st

US_STATIONS = ["KDEN", "KJFK", "KSEA", "PHNL", "PANC", "KLAX"]
CA_STATIONS = ["CYYZ", "CYUL", "CYVR"]
EU_STATIONS = ["EGLL", "EDDF", "LFPG", "EHAM", "LEMD"]
ASIA_STATIONS = ["RJTT", "VHHH", "ZBAA", "OMDB"]
ALL_STATIONS = US_STATIONS + CA_STATIONS + EU_STATIONS + ASIA_STATIONS


@dataclass
class Draw:
    text: str
    facts: dict[str, Any] = field(default_factory=dict)


def _fmt_temp(value: int) -> str:
    return f"M{-value:02d}" if value < 0 else f"{value:02d}"


@st.composite
def metar(draw: st.DrawFn, *, units: str | None = None) -> Draw:
    """A METAR in US (SM, A####) or ICAO (metres, Q####) units; ``units`` forces one of ``us``/``icao``."""
    system = units or draw(st.sampled_from(["us", "icao"]))
    # The station prefix is drawn independently of the unit system on purpose: tokens decide, not the prefix.
    station = draw(st.sampled_from(ALL_STATIONS))
    day, hour, minute = draw(st.integers(1, 28)), draw(st.integers(0, 23)), draw(st.integers(0, 59))
    parts = [draw(st.sampled_from(["METAR", "SPECI", ""])), station, f"{day:02d}{hour:02d}{minute:02d}Z"]
    facts: dict[str, Any] = {"station": station, "day": day, "hour": hour, "minute": minute, "system": system}
    if draw(st.booleans()):
        parts.append("AUTO")

    direction = draw(st.integers(0, 36)) * 10
    speed = draw(st.integers(0, 60))
    gust = draw(st.one_of(st.none(), st.integers(speed + 1, speed + 30))) if speed >= 3 else None
    unit = "KT" if system == "us" else draw(st.sampled_from(["KT", "MPS"]))
    if speed == 0 and gust is None:
        direction = 0
    if direction == 0 and speed != 0:
        direction = 360
    wind = "VRB" if (speed and speed < 7 and draw(st.booleans())) else f"{direction:03d}"
    wind_text = f"{wind}{speed:02d}" + (f"G{gust:02d}" if gust else "") + unit
    parts.append(wind_text)
    facts.update(wind_dir=None if wind == "VRB" else direction, wind_speed=speed, wind_gust=gust, wind_unit=unit)

    if system == "us":
        whole = draw(st.sampled_from([0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]))
        frac = draw(st.sampled_from(["", "1/4", "1/2", "3/4", "1/8", "3/8"])) if whole < 3 else ""
        if whole == 0 and not frac:
            frac = "1/2"
        if whole >= 10 and draw(st.booleans()):
            vis_text, vis_sm = "10SM", 10.0
        else:
            vis_text = f"{whole} {frac}SM" if whole and frac else (f"{frac}SM" if frac else f"{whole}SM")
            num, den = (int(x) for x in frac.split("/")) if frac else (0, 1)
            vis_sm = whole + num / den
        if not frac and whole >= 6 and draw(st.booleans()):
            vis_text, vis_sm = "P6SM", 6.0
        parts.append(vis_text)
        facts["vis_sm"] = vis_sm
        facts["vis_prefix"] = "P" if vis_text.startswith("P") else None
    else:
        if draw(st.booleans()) and draw(st.booleans()):
            parts.append("CAVOK")
            facts["cavok"] = True
            facts["vis_sm"] = 10.0
        else:
            metres = draw(
                st.sampled_from([0, 50, 100, 200, 350, 500, 800, 1200, 1600, 2400, 3000, 4800, 5000, 8000, 9999])
            )
            parts.append(f"{metres:04d}")
            facts["vis_m"] = metres

    if not facts.get("cavok"):
        layers: list[tuple[str, int | None]] = []
        for _ in range(draw(st.integers(0, 3))):
            cover = draw(st.sampled_from(["FEW", "SCT", "BKN", "OVC"]))
            layers.append((cover, draw(st.integers(1, 250))))  # height in hundreds of feet
        layers.sort(key=lambda layer: layer[1] or 0)
        use_vv = draw(st.integers(0, 12)) == 0
        if use_vv:
            layers = [("VV", draw(st.integers(0, 20)))]
        if not layers:
            parts.append(draw(st.sampled_from(["CLR", "SKC", "NSC"])))
        for cover, height in layers:
            parts.append(f"{cover}{height:03d}")
        facts["layers"] = layers

    temp = draw(st.integers(-40, 45))
    dew = draw(st.integers(temp - 15, temp))
    parts.append(f"{_fmt_temp(temp)}/{_fmt_temp(dew)}")
    facts.update(temp=temp, dew=dew)

    if system == "us":
        inhg = draw(st.integers(2850, 3100))
        parts.append(f"A{inhg:04d}")
        facts["alt_inhg"] = inhg / 100
    else:
        hpa = draw(st.integers(950, 1060))
        parts.append(f"Q{hpa:04d}")
        facts["qnh_hpa"] = hpa
    return Draw(" ".join(p for p in parts if p), facts)


@st.composite
def taf(draw: st.DrawFn) -> Draw:
    """A TAF with a base forecast and FM/BECMG/TEMPO/PROB groups in the modern DDHH/DDHH form."""
    station = draw(st.sampled_from(ALL_STATIONS))
    day = draw(st.integers(1, 27))
    hour = draw(st.sampled_from([0, 6, 12, 18]))
    start_total = day * 24 + hour
    end_total = start_total + 24

    def dh(total: int) -> str:
        return f"{total // 24:02d}{total % 24:02d}"

    parts = [
        "TAF",
        station,
        f"{day:02d}{hour:02d}20Z",
        f"{dh(start_total)}/{dh(end_total)}",
        "24010KT",
        "9999",
        "SCT040",
    ]
    groups: list[dict[str, Any]] = [{"change": "BASE"}]
    cursor = start_total
    for _ in range(draw(st.integers(0, 4))):
        kind = draw(st.sampled_from(["FM", "BECMG", "TEMPO", "PROB30", "PROB40", "PROB30 TEMPO", "PROB40 TEMPO"]))
        lo = cursor + draw(st.integers(1, 6))
        hi = min(lo + draw(st.integers(1, 6)), end_total)
        if lo >= end_total:
            break
        if kind == "FM":
            parts += [f"FM{dh(lo)}00", "18012KT", "3000", "BKN008"]
            cursor = lo
        else:
            parts += [*kind.split(), f"{dh(lo)}/{dh(hi)}", "4000", "-RA", "OVC015"]
            if kind == "BECMG":
                cursor = lo
        groups.append({"change": kind, "start": lo, "end": hi})
    return Draw(
        " ".join(parts), {"station": station, "day": day, "hour": hour, "start_total": start_total, "groups": groups}
    )
