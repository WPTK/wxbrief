"""Tokenizer and cursor.

A report is split on whitespace into ``Token`` objects whose offsets index the original string, so the raw text can
always be rebuilt and highlighted. A trailing ``=`` (the report terminator) is split off as its own token.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from wxbrief.decode.model import SemanticKind

_WORD = re.compile(r"\S+")


@dataclass(frozen=True)
class Token:
    """A whitespace-delimited piece of the report: uppercase ``text`` at ``raw[start:end]``."""

    text: str
    start: int
    end: int
    kind: SemanticKind = SemanticKind.UNKNOWN


def tokenize(raw: str) -> list[Token]:
    """Split ``raw`` into tokens; every non-whitespace character lands in exactly one token."""
    tokens: list[Token] = []
    for match in _WORD.finditer(raw):
        start, end = match.span()
        stem = match.group().rstrip("=")
        if not stem:  # nothing but terminator characters
            tokens.append(Token(raw[start:end].upper(), start, end, SemanticKind.TERMINATOR))
            continue
        cut = start + len(stem)
        tokens.append(Token(raw[start:cut].upper(), start, cut))
        if cut < end:
            tokens.append(Token(raw[cut:end].upper(), cut, end, SemanticKind.TERMINATOR))
    return tokens


class Cursor:
    """A position over a token list with the tagging needed by multi-token groups (``1 1/2SM``).

    ``take`` consumes the next token and records its kind. ``mark``/``reset`` let a group parser back out of a
    partial match, restoring both the position and the kinds of the tokens it had consumed.
    """

    def __init__(self, tokens: list[Token]) -> None:
        self._tokens = tokens
        self._kinds = [tok.kind for tok in tokens]
        self.pos = 0

    def __len__(self) -> int:
        return len(self._tokens)

    @property
    def at_end(self) -> bool:
        return self.pos >= len(self._tokens)

    def peek(self, offset: int = 0) -> Token | None:
        """The token ``offset`` places ahead, or ``None`` past the end."""
        index = self.pos + offset
        if 0 <= index < len(self._tokens):
            return self._tokens[index]
        return None

    def take(self, kind: SemanticKind = SemanticKind.UNKNOWN) -> Token:
        """Consume the next token and tag it with ``kind``."""
        token = self._tokens[self.pos]
        self._kinds[self.pos] = kind
        self.pos += 1
        return token

    def mark(self) -> int:
        return self.pos

    def reset(self, mark: int) -> None:
        """Rewind to ``mark``, forgetting the kinds given to anything consumed since."""
        for index in range(mark, self.pos):
            self._kinds[index] = self._tokens[index].kind
        self.pos = mark

    def kind_at(self, index: int) -> SemanticKind:
        return self._kinds[index]

    def token_at(self, index: int) -> Token:
        return self._tokens[index]

    def tagged(self) -> tuple[Token, ...]:
        """All tokens with the kinds assigned so far."""
        return tuple(replace(tok, kind=kind) for tok, kind in zip(self._tokens, self._kinds, strict=True))
