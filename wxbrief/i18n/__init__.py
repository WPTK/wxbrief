"""Translation catalogs and the Translator (typed end to end; mypy strict).

Catalogs are TOML files in ``locales/`` with dotted semantic keys and ``str.format`` placeholders. A table whose
keys are plural categories (``one``/``other``) is a plural entry. Lookup falls back from ``pt-BR`` to ``pt`` to
``en``, and a key missing everywhere comes back as itself so a gap is visible rather than fatal.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources

from wxbrief.i18n.numbers import ENGLISH, NumberFormat
from wxbrief.i18n.plurals import CATEGORIES, plural_category

DEFAULT_LANGUAGE = "en"
LANGUAGES = ("en", "es", "fr", "de", "pt")  # the catalogs that ship, in the order a picker lists them
_LANG_CODE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")

type Entry = str | dict[str, str]


@dataclass(frozen=True)
class Catalog:
    """One flattened language file."""

    lang: str
    entries: dict[str, Entry]
    meta: dict[str, object]


def lower_first(text: str) -> str:
    """Lowercase the first character unless the word is an acronym (``CAVOK``) or starts a unit or number."""
    if len(text) > 1 and (text[1].isupper() or not text[0].isalpha()):
        return text
    return text[:1].lower() + text[1:]


class _Params(dict[str, object]):
    """``format_map`` helper that leaves unknown placeholders visible instead of raising."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _is_plural_table(table: Mapping[str, object]) -> bool:
    return (
        "other" in table
        and all(key in CATEGORIES for key in table)
        and all(isinstance(value, str) for value in table.values())
    )


def _flatten(prefix: str, table: Mapping[str, object], out: dict[str, Entry]) -> None:
    for key, value in table.items():
        dotted = f"{prefix}.{key}" if prefix else key
        if isinstance(value, str):
            out[dotted] = value
        elif isinstance(value, dict):
            if _is_plural_table(value):
                out[dotted] = {str(k): str(v) for k, v in value.items()}
            else:
                _flatten(dotted, value, out)


def parse_catalog(lang: str, text: str) -> Catalog:
    """Parse TOML text into a flat catalog; the ``[meta]`` table is kept apart from the entries."""
    data = tomllib.loads(text)
    meta = dict(data.pop("meta", {}))
    entries: dict[str, Entry] = {}
    _flatten("", data, entries)
    return Catalog(lang, entries, meta)


def _read_catalog(lang: str) -> Catalog | None:
    if not _LANG_CODE.match(lang):
        return None
    resource = resources.files("wxbrief.i18n").joinpath("locales", f"{lang}.toml")
    if not resource.is_file():
        return None
    return parse_catalog(lang, resource.read_text(encoding="utf-8"))


def fallback_chain(lang: str) -> list[str]:
    """``pt-BR`` -> ``["pt-BR", "pt", "en"]``; ``en`` -> ``["en"]``."""
    code = lang.replace("_", "-")
    chain: list[str] = []
    parts = code.split("-")
    for end in range(len(parts), 0, -1):
        name = "-".join(parts[:end])
        if name and name not in chain:
            chain.append(name)
    if DEFAULT_LANGUAGE not in chain:
        chain.append(DEFAULT_LANGUAGE)
    return chain


def resolve_language(code: str) -> str | None:
    """The catalog that serves ``code`` (``pt-BR`` -> ``pt``, ``DE`` -> ``de``), or ``None`` when there is none."""
    parts = code.strip().replace("_", "-").split("-")
    parts[0] = parts[0].lower()
    for end in range(len(parts), 0, -1):
        name = "-".join(parts[:end])
        if _read_catalog(name) is not None:
            return name
    return None


class Translator:
    """Looks up catalog keys and fills in their placeholders."""

    def __init__(self, catalogs: list[Catalog]) -> None:
        if not catalogs:
            raise ValueError("a Translator needs at least one catalog")
        self._catalogs = catalogs

    @classmethod
    def load(cls, lang: str = DEFAULT_LANGUAGE) -> Translator:
        """Load ``lang`` and its fallbacks; the English catalog is always the last resort."""
        catalogs = [cat for name in fallback_chain(lang) if (cat := _read_catalog(name)) is not None]
        if not catalogs or catalogs[-1].lang != DEFAULT_LANGUAGE:
            english = _read_catalog(DEFAULT_LANGUAGE)
            if english is None:
                raise FileNotFoundError("the English catalog is missing from the installation")
            catalogs.append(english)
        return cls(catalogs)

    @property
    def lang(self) -> str:
        return self._catalogs[0].lang

    @property
    def meta(self) -> dict[str, object]:
        return self._catalogs[0].meta

    @property
    def numbers(self) -> NumberFormat:
        """The primary catalog's number format (English separators when it names none)."""
        meta = self._catalogs[0].meta
        return NumberFormat.from_meta(meta) if meta else ENGLISH

    @property
    def language_name(self) -> str:
        """The language's own name (``Deutsch``) from the catalog's ``[meta]``."""
        return str(self._catalogs[0].meta.get("language", self.lang))

    def lower_first(self, text: str) -> str:
        """``lower_first``, unless the language capitalises nouns mid-sentence (``keep_case`` in ``[meta]``)."""
        return text if self._catalogs[0].meta.get("keep_case") is True else lower_first(text)

    @property
    def keys(self) -> frozenset[str]:
        """Every key of the primary catalog."""
        return frozenset(self._catalogs[0].entries)

    def _entry(self, key: str) -> Entry | None:
        for catalog in self._catalogs:
            entry = catalog.entries.get(key)
            if entry is not None:
                return entry
        return None

    @staticmethod
    def _fill(template: str, params: Mapping[str, object]) -> str:
        try:
            return template.format_map(_Params(params))
        except (ValueError, IndexError, KeyError, AttributeError):
            return template

    def t(self, key: str, **params: object) -> str:
        """Translate ``key``; a plural entry resolves to its ``other`` form."""
        entry = self._entry(key)
        if entry is None:
            return key
        template = entry if isinstance(entry, str) else entry["other"]
        return self._fill(template, params)

    def plural(self, key: str, n: float, **params: object) -> str:
        """Translate a plural entry for the count ``n`` (available to the template as ``{n}``)."""
        entry = self._entry(key)
        if entry is None:
            return key
        if isinstance(entry, str):
            return self._fill(entry, {"n": n, **params})
        rule = str(self._catalogs[0].meta.get("plural_rule", "one_other"))
        template = entry.get(plural_category(rule, n), entry["other"])
        return self._fill(template, {"n": n, **params})
