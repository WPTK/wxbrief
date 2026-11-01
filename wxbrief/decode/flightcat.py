"""FAA flight category from ceiling and visibility.

Thresholds are those of paragraph ``700-FLIGHT-RULES`` of the reference COBOL decoder:

* LIFR: ceiling below 500 ft, or visibility below 1 SM
* IFR: ceiling below 1,000 ft, or visibility below 3 SM
* MVFR: ceiling up to and including 3,000 ft, or visibility up to and including 5 SM
* VFR: everything else

The ceiling is the lowest broken, overcast or vertical-visibility layer. Metres convert to statute miles at
1609.34, and ``9999`` or ``CAVOK`` counts as 10 SM. A missing component is not assumed clear: the category is then
``None`` unless the known component alone forces IFR or LIFR.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

from wxbrief.decode.model import CloudLayer, FlightCategory, SkyCondition, Visibility

LIFR_CEILING_FT = 500
IFR_CEILING_FT = 1000
MVFR_CEILING_FT = 3000
LIFR_VISIBILITY_SM = 1
IFR_VISIBILITY_SM = 3
MVFR_VISIBILITY_SM = 5

UNLIMITED_VISIBILITY_SM = 10.0


def visibility_sm(visibility: Visibility | None) -> float | None:
    """Prevailing visibility in statute miles, or ``None`` when the report gives none."""
    if visibility is None or visibility.not_reported:
        return None
    if visibility.cavok or visibility.unlimited:
        return UNLIMITED_VISIBILITY_SM
    if visibility.distance is None:
        return None
    return visibility.distance.statute_miles


def lowest_ceiling(sky: Sequence[CloudLayer]) -> CloudLayer | None:
    """The lowest broken, overcast or vertical-visibility layer whose height is known."""
    candidates = [layer for layer in sky if layer.is_ceiling_layer and layer.base is not None]
    if not candidates:
        return None
    return min(candidates, key=lambda layer: layer.base.feet if layer.base is not None else math.inf)


def _could_lower(layer: CloudLayer, known_ft: float | None) -> bool:
    """Whether a layer of unknown amount or unknown height might sit below the known ceiling."""
    unknown = layer.base is None if layer.is_ceiling_layer else layer.cover is SkyCondition.UNKNOWN
    if not unknown:
        return False
    return layer.base is None or known_ft is None or layer.base.feet < known_ft


def ceiling_for_classification(sky: Sequence[CloudLayer], cavok: bool) -> float | None:
    """Ceiling for classification: feet, ``inf`` for a sky known to have none, ``None`` when unknown.

    A layer of unknown amount or height that might lower the ceiling makes it unknown, unless the known ceiling
    already forces IFR or LIFR.
    """
    layer = lowest_ceiling(sky)
    known_ft = layer.base.feet if layer is not None and layer.base is not None else None
    if any(_could_lower(candidate, known_ft) for candidate in sky):
        return known_ft if known_ft is not None and known_ft < IFR_CEILING_FT else None
    if known_ft is not None:
        return known_ft
    if cavok or any(candidate.cover is not SkyCondition.UNKNOWN for candidate in sky):
        return math.inf  # CAVOK, or layers/clear-sky codes that leave no ceiling
    return None  # no sky group, or only "//////" placeholders: the sensor reported nothing


def _band(ceil: float, vis: float) -> FlightCategory:
    if ceil < LIFR_CEILING_FT or vis < LIFR_VISIBILITY_SM:
        return FlightCategory.LIFR
    if ceil < IFR_CEILING_FT or vis < IFR_VISIBILITY_SM:
        return FlightCategory.IFR
    if ceil <= MVFR_CEILING_FT or vis <= MVFR_VISIBILITY_SM:
        return FlightCategory.MVFR
    return FlightCategory.VFR


def classify(ceiling_ft: float | None, visibility: float | None) -> FlightCategory | None:
    """Category for a ceiling in feet and a visibility in statute miles.

    ``math.inf`` is a known absence of limit (no ceiling, unlimited visibility); ``None`` is unknown. While a
    component is unknown the result is ``None``, unless the known component alone forces IFR or LIFR: unknown data
    never earns a VFR or MVFR badge.
    """
    if ceiling_ft is None and visibility is None:
        return None
    known = _band(math.inf if ceiling_ft is None else ceiling_ft, math.inf if visibility is None else visibility)
    if ceiling_ft is not None and visibility is not None:
        return known
    return known if known in (FlightCategory.IFR, FlightCategory.LIFR) else None


def flight_category(visibility: Visibility | None, sky: Sequence[CloudLayer]) -> FlightCategory | None:
    """Flight category of a decoded body, or ``None`` when neither visibility nor sky is available."""
    cavok = visibility is not None and visibility.cavok
    return classify(ceiling_for_classification(sky, cavok), visibility_sm(visibility))


def worst_of(categories: Iterable[FlightCategory | None]) -> FlightCategory | None:
    """The most restrictive category of those given (``LIFR`` is worst); ``None`` entries are ignored."""
    found = [category for category in categories if category is not None]
    return max(found, key=lambda category: category.rank) if found else None
