"""Chrome themes (Textual Theme objects) and the semantic token palette."""

from __future__ import annotations

from wxbrief.ui.themes.aviation import AVIATION_THEMES
from wxbrief.ui.themes.semantic import BUILTIN_THEME_NAMES, SEMANTIC_DEFAULTS, semantic_variables

# The order ``t`` cycles through: the aviation themes, then the curated built-ins.
THEME_CYCLE: tuple[str, ...] = (*(theme.name for theme in AVIATION_THEMES), *BUILTIN_THEME_NAMES)

__all__ = ["AVIATION_THEMES", "BUILTIN_THEME_NAMES", "SEMANTIC_DEFAULTS", "THEME_CYCLE", "semantic_variables"]
