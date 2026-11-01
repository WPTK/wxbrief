"""``python -m uat_kit.faultproxy --fixtures tests/fixtures/awc``: run until Ctrl+C, print the environment to use."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .server import FaultProxy, load_awc_payloads


def main() -> None:
    ap = argparse.ArgumentParser(prog="faultproxy")
    ap.add_argument("--fixtures", type=Path, required=True)
    ap.add_argument("--dir", type=Path)
    ap.add_argument("--host", default="aviationweather.gov")
    ap.add_argument("--proxy-port", type=int, default=0)
    ap.add_argument("--control-port", type=int, default=0)
    a = ap.parse_args()
    with FaultProxy(
        load_awc_payloads(a.fixtures),
        host=a.host,
        directory=a.dir,
        proxy_port=a.proxy_port,
        control_port=a.control_port,
    ) as fp:
        print(json.dumps({"env": fp.env(), "control": fp.control_url, "ca": str(fp.ca.ca_pem)}, indent=2), flush=True)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


main()
