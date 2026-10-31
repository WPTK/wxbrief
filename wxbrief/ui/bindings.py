"""Key bindings whose footer labels come from the catalog.

``bind`` builds a ``Binding`` whose description is the English text and whose ``id`` is the catalog key. ``relabel``
swaps the description for the active language on a live widget, screen or app, so a language change shows in the footer
at once. English lives only in ``locales/en.toml``.
"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import replace
from functools import cache
from typing import Any

from textual.binding import Binding
from textual.dom import DOMNode, NoScreen

from wxbrief.i18n import Translator


@cache
def _english() -> Translator:
    return Translator.load("en")


def bind(key: str, action: str, label: str, *, show: bool = True, priority: bool = False) -> Binding:
    """A binding labelled by the catalog key ``label`` (one of the ``K.UI_BINDING_*`` constants)."""
    return Binding(key, action, _english().t(label), show=show, priority=priority, id=label)


def relabel(node: DOMNode, translator: Translator) -> None:
    """Put the translator's footer labels on the node's own bindings."""
    table = node._bindings.key_to_bindings
    for key, bindings in table.items():
        table[key] = [
            replace(item, description=translator.t(item.id)) if item.id and item.id.startswith("ui.binding.") else item
            for item in bindings
        ]
    with suppress(NoScreen):  # not mounted yet: the footer reads the new labels when it first draws
        node.refresh_bindings()


def translator_of(node: DOMNode) -> Translator:
    """The running app's translator (English when the app has none, as in a bare test app)."""
    context = getattr(node.app, "ctx", None)
    return context.translator if context is not None else _english()


def localize(node: DOMNode) -> None:
    """Relabel one node with the running app's language; call it from ``on_mount``."""
    relabel(node, translator_of(node))


def relabel_tree(app: Any, translator: Translator) -> None:
    """Relabel the app, every screen on the stack and every widget on them."""
    relabel(app, translator)
    for screen in app.screen_stack:
        relabel(screen, translator)
        for widget in screen.walk_children():
            relabel(widget, translator)
