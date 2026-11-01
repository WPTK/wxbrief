"""copy_text: pyperclip locally, the terminal's OSC 52 first over SSH."""

from __future__ import annotations

from typing import Any

import pytest

from wxbrief import clipboard
from wxbrief.i18n import Translator

T = Translator.load("en")


class FakeApp:
    def __init__(self) -> None:
        self.terminal: list[str] = []
        self.toasts: list[str] = []

    def copy_to_clipboard(self, text: str) -> None:
        self.terminal.append(text)

    def notify(self, message: str, **kwargs: Any) -> None:
        self.toasts.append(message)


@pytest.fixture
def pyperclip_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(clipboard, "_pyperclip_copy", calls.append)
    for name in ("SSH_TTY", "SSH_CONNECTION"):
        monkeypatch.delenv(name, raising=False)
    return calls


def test_locally_pyperclip_is_used(pyperclip_calls: list[str]) -> None:
    app = FakeApp()
    assert clipboard.copy_text(app, "hello", "METAR", T)  # type: ignore[arg-type]
    assert pyperclip_calls == ["hello"] and app.terminal == []


@pytest.mark.parametrize("variable", ["SSH_TTY", "SSH_CONNECTION"])
def test_over_ssh_the_terminal_route_goes_first(
    variable: str, pyperclip_calls: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(variable, "x")
    app = FakeApp()
    assert clipboard.copy_text(app, "hello", "METAR", T)  # type: ignore[arg-type]
    assert app.terminal == ["hello"] and pyperclip_calls == []


def test_without_a_clipboard_tool_the_terminal_route_is_the_fallback(
    pyperclip_calls: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(text: str) -> None:
        raise RuntimeError("no clipboard")

    monkeypatch.setattr(clipboard, "_pyperclip_copy", broken)
    app = FakeApp()
    assert clipboard.copy_text(app, "hello", "METAR", T)  # type: ignore[arg-type]
    assert app.terminal == ["hello"]


def test_a_copy_that_leaves_the_clipboard_unchanged_falls_back_to_the_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    import types

    fake = types.SimpleNamespace(copy=lambda text: None, paste=lambda: "the previous contents")  # a dead xclip
    monkeypatch.setitem(sys.modules, "pyperclip", fake)
    monkeypatch.setattr(sys, "platform", "linux")
    for name in ("SSH_TTY", "SSH_CONNECTION"):
        monkeypatch.delenv(name, raising=False)
    app = FakeApp()
    assert clipboard.copy_text(app, "hello", "METAR", T)  # type: ignore[arg-type]
    assert app.terminal == ["hello"]
    fake.paste = lambda: "hello\n"  # a tool that did take it
    app = FakeApp()
    assert clipboard.copy_text(app, "hello", "METAR", T)  # type: ignore[arg-type]
    assert app.terminal == []
