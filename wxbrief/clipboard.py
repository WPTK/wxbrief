"""Copy text to the clipboard: pyperclip first, the terminal's OSC 52 sequence as the fallback, a toast either way."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from wxbrief.i18n import Translator
from wxbrief.i18n.keys import K

if TYPE_CHECKING:
    from textual.app import App


def _pyperclip_copy(text: str) -> None:
    import pyperclip

    pyperclip.copy(text)


def copy_text(app: App[Any], text: str, what: str, t: Translator) -> bool:
    """Put ``text`` on the clipboard and tell the user. ``True`` unless both routes failed."""
    title = t.t(K.UI_CLIPBOARD_TITLE)
    try:
        _pyperclip_copy(text)
    except Exception:  # pyperclip raises its own exception type when no clipboard tool exists
        try:
            app.copy_to_clipboard(text)  # OSC 52: the terminal may ignore it, and we cannot tell
        except Exception as exc:
            app.notify(t.t(K.UI_CLIPBOARD_FAILED, what=what, error=exc), severity="error", title=title)
            return False
        app.notify(t.t(K.UI_CLIPBOARD_COPIED_TERMINAL, what=what), title=title)
        return True
    app.notify(t.t(K.UI_CLIPBOARD_COPIED, what=what), title=title)
    return True
