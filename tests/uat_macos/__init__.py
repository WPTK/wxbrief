"""uat_macos: real keys, real mouse clicks, window screenshots and screen read-back for Terminal.app and iTerm2.

Vendored from the eyewall S4 spike (see README.md). Same shape as ``uat_kit.Terminal``: an argv in, screen text and
PNGs out. Runs only on a macOS host with the permissions that ``scripts/grant_tcc.sh`` sets up.
"""

from .driver import MacTerminal, cell_center, unavailable_reason

__all__ = ["MacTerminal", "cell_center", "unavailable_reason"]
