"""Copy text to the clipboard: pyperclip first, the terminal's OSC 52 sequence as the fallback, a toast either way."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from textual.app import App


def _pyperclip_copy(text: str) -> None:
    import pyperclip

    pyperclip.copy(text)


def copy_text(app: App[Any], text: str, what: str) -> bool:
    """Put ``text`` on the clipboard and tell the user. ``True`` unless both routes failed."""
    try:
        _pyperclip_copy(text)
    except Exception:  # pyperclip raises its own exception type when no clipboard tool exists
        try:
            app.copy_to_clipboard(text)  # OSC 52: the terminal may ignore it, and we cannot tell
        except Exception as exc:
            app.notify(f"Could not copy {what}: {exc}", severity="error", title="Clipboard")
            return False
        app.notify(f"Copied {what} (terminal clipboard)", title="Clipboard")
        return True
    app.notify(f"Copied {what}", title="Clipboard")
    return True
