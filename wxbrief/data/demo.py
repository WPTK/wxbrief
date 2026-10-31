"""The bundled demo reports (``--demo``): one METAR and one TAF for each of ten stations, read from ``demo/*.txt``.

The reports are fixed, so the demo runs on a fixed clock (``DEMO_NOW``) at which every METAR is fresh and every TAF is
in force. A line starting with ``#`` is a comment (where the report came from). Nothing here touches the network, the
cache or the config.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import resources

from wxbrief.data.models import AwcMetar, AwcTaf
from wxbrief.decode.model import Metar, Taf
from wxbrief.decode.split import parse_any

DEMO_NOW = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)

# Display order: the stations of the design notes.
DEMO_ORDER = ("KDEN", "EGLL", "ETHB", "UUEE", "YSSY", "RJTT", "VIDP", "SBGR", "CYYZ", "NZSP")


@dataclass(frozen=True, slots=True)
class DemoStation:
    icao: str
    metar: Metar
    taf: Taf | None
    awc_metar: AwcMetar
    awc_taf: AwcTaf | None


def demo_text(icao: str) -> str:
    """The report text of one demo file with its comment lines removed."""
    path = resources.files("wxbrief.data").joinpath("demo", f"{icao}.txt")
    lines = path.read_text(encoding="utf-8").splitlines()
    return "\n".join(line for line in lines if not line.lstrip().startswith("#"))


def demo_ids() -> list[str]:
    """The ids that have a demo file, in display order."""
    folder = resources.files("wxbrief.data").joinpath("demo")
    present = {item.name.removesuffix(".txt") for item in folder.iterdir() if item.name.endswith(".txt")}
    return [icao for icao in DEMO_ORDER if icao in present] + sorted(present.difference(DEMO_ORDER))


def load_demo(reference: datetime = DEMO_NOW) -> list[DemoStation]:
    """Decode every demo file. A file without a METAR is skipped; the TAF is optional."""
    stations: list[DemoStation] = []
    for icao in demo_ids():
        decoded = parse_any(demo_text(icao), reference)
        metar = next((item for item in decoded if isinstance(item, Metar)), None)
        taf = next((item for item in decoded if isinstance(item, Taf)), None)
        if metar is None:
            continue
        observed = metar.observed
        stations.append(
            DemoStation(
                icao,
                metar,
                taf,
                AwcMetar(icao=icao, raw=metar.raw, observed=observed),
                AwcTaf(icao, taf.raw, taf.issue_time, taf.valid_from, taf.valid_to) if taf else None,
            )
        )
    return stations
