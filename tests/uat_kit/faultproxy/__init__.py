"""faultproxy: a CONNECT proxy plus a local TLS server that stands in for a real HTTPS API, with injectable faults.

Generic on purpose (no project imports): give it a host name and a payload per path and point an UNMODIFIED program at
it with ``HTTPS_PROXY`` and ``SSL_CERT_FILE``. See ``server.py`` for the control channel and the fault modes.
"""

from .certs import TestCA
from .server import Behavior, FaultProxy, parse_behavior

__all__ = ["Behavior", "FaultProxy", "TestCA", "parse_behavior"]
