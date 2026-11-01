"""Copy text to the clipboard: pyperclip, or the terminal's OSC 52 sequence (first over SSH), a toast either way."""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING, Any

from wxbrief.i18n import Translator
from wxbrief.i18n.keys import K

if TYPE_CHECKING:
    from textual.app import App


def _plain(text: str) -> str:
    return text.replace("\r\n", "\n").rstrip()


def _pyperclip_copy(text: str) -> None:
    import pyperclip

    pyperclip.copy(text)
    if sys.platform.startswith("linux"):
        # pyperclip's xclip route never checks the exit status, so with a dead DISPLAY the copy "works" and nothing
        # is on the clipboard. Read it back; a mismatch raises, which sends the caller to the terminal route.
        if _plain(pyperclip.paste()) != _plain(text):
            raise RuntimeError("the clipboard tool did not take the text")


def _over_ssh() -> bool:
    """Whether this process runs on the far end of an SSH session, where the clipboard that counts is the user's."""
    return bool(os.environ.get("SSH_TTY") or os.environ.get("SSH_CONNECTION"))


def copy_text(app: App[Any], text: str, what: str, t: Translator) -> bool:
    """Put ``text`` on the clipboard and tell the user. ``True`` unless both routes failed.

    Over SSH pyperclip would fill the remote machine's clipboard without an error, so the terminal route (OSC 52,
    which reaches the user's own clipboard) goes first there.
    """
    if not _over_ssh():
        try:
            _pyperclip_copy(text)
        except Exception:  # pyperclip raises its own exception type when no clipboard tool exists
            pass
        else:
            app.notify(t.t(K.UI_CLIPBOARD_COPIED, what=what))
            return True
    try:
        app.copy_to_clipboard(text)  # OSC 52: the terminal may ignore it, and we cannot tell
    except Exception as exc:
        app.notify(t.t(K.UI_CLIPBOARD_FAILED, what=what, error=exc), severity="error")
        return False
    app.notify(t.t(K.UI_CLIPBOARD_COPIED_TERMINAL, what=what))
    return True
