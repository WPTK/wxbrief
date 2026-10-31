"""Regenerate ``wxbrief/i18n/keys.py`` from the English catalog.

Run after adding or removing keys in ``wxbrief/i18n/locales/en.toml``::

    python scripts/gen_keys.py

``tests/test_i18n.py`` fails if the constants and the catalog disagree, so a forgotten run is caught in CI.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wxbrief.i18n import Translator  # noqa: E402


def render(keys: list[str]) -> str:
    """The text of ``keys.py`` for a sorted list of dotted keys."""
    names = [key.upper().replace(".", "_") for key in keys]
    if len(set(names)) != len(names):
        raise SystemExit("two catalog keys map to the same constant name")
    lines = [
        '"""Catalog key constants. A test asserts these equal the keys of ``locales/en.toml`` exactly."""',
        "",
        "from __future__ import annotations",
        "",
        "",
        "class K:",
        '    """Dotted catalog keys, one constant per key (``K.WIND_CALM == "wind.calm"``)."""',
        "",
    ]
    previous = None
    for key, name in zip(keys, names, strict=True):
        group = key.split(".")[0]
        if previous is not None and group != previous:
            lines.append("")
        previous = group
        lines.append(f'    {name} = "{key}"')
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    keys = sorted(Translator.load("en").keys)
    target = ROOT / "wxbrief" / "i18n" / "keys.py"
    target.write_bytes(render(keys).encode("utf-8"))
    print(f"wrote {len(keys)} keys to {target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
