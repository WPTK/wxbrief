"""NATO colour states: the threshold table and the state a ceiling and visibility compute to.

Each state is the best one whose cloud-base AND visibility minimums both hold; the worse of the two decides.

======  ===========  ==========
State   Cloud base   Visibility
======  ===========  ==========
BLU     2,500 ft     8,000 m
WHT     1,500 ft     5,000 m
GRN     700 ft       3,700 m
YLO1    500 ft       2,500 m
YLO2    300 ft       1,600 m
AMB     200 ft       800 m
RED     below AMB    below AMB
======  ===========  ==========

Source: the UK Met Office aerodrome colour state register (https://reference.metoffice.gov.uk/aviation/
UKAerodromeColourStates, entries BLU to RED) and the table in the Wikipedia article "Colour state". Both agree on every
figure above. A value exactly on a minimum earns the better state ("at least"). Two caveats are documented in
``docs/decoding.md``: the cloud amount that counts as a ceiling differs by country (five oktas or more in the US and
much of Europe, three or more in the UK, Belgium, France and the Netherlands) and ``computed_color_state`` takes the
caller's ceiling, which this decoder defines as the lowest broken or overcast layer; plain ``YLO`` is the single yellow
of older tables and has the YLO2 minimums.
"""

from __future__ import annotations

from dataclasses import dataclass

from wxbrief.decode.model import ColorCode, ColorState, Visibility


@dataclass(frozen=True)
class ColorMinimums:
    """The minimums of one colour state."""

    code: ColorCode
    ceiling_ft: int
    visibility_m: int


# Best to worst. ``RED`` has no minimums: it is whatever falls below AMB.
THRESHOLDS: tuple[ColorMinimums, ...] = (
    ColorMinimums(ColorCode.BLU, 2500, 8000),
    ColorMinimums(ColorCode.WHT, 1500, 5000),
    ColorMinimums(ColorCode.GRN, 700, 3700),
    ColorMinimums(ColorCode.YLO1, 500, 2500),
    ColorMinimums(ColorCode.YLO2, 300, 1600),
    ColorMinimums(ColorCode.AMB, 200, 800),
)

# ``BLU+`` (Bundeswehr reports): visibility of 8 km or more and no ceiling below 20,000 ft. The figure comes from a
# community source, not an official table.
BLU_PLUS_CEILING_FT = 20000

BELOW_GRN = frozenset({ColorCode.YLO, ColorCode.YLO1, ColorCode.YLO2, ColorCode.AMB, ColorCode.RED})


def computed_color_state(ceiling_ft: float | None, visibility_m: float | None) -> ColorCode | None:
    """The best colour state whose cloud-base and visibility minimums both hold.

    ``None`` for a component means it is unknown or imposes no limit (no ceiling): it never lowers the state, and
    ``math.inf`` is the same thing. With both ``None`` there is nothing to compute and the result is ``None``.
    Anything below the AMB minimums is ``RED``.
    """
    if ceiling_ft is None and visibility_m is None:
        return None
    for row in THRESHOLDS:
        ceiling_ok = ceiling_ft is None or ceiling_ft >= row.ceiling_ft
        visibility_ok = visibility_m is None or visibility_m >= row.visibility_m
        if ceiling_ok and visibility_ok:
            return row.code
    return ColorCode.RED


def visibility_meters(visibility: Visibility | None) -> float | None:
    """Prevailing visibility in metres for a colour state, or ``None`` when the report gives none."""
    if visibility is None or visibility.not_reported:
        return None
    if visibility.cavok or visibility.unlimited:
        return 10000.0
    if visibility.distance is None:
        return None
    return visibility.distance.meters


def is_below_green(state: ColorState | None) -> bool:
    """Whether a reported state is worse than GRN (a bare or ``BLACK``-only state is not a weather state)."""
    return state is not None and state.code in BELOW_GRN


def reported_matches_computed(
    reported: ColorState | None, computed: ColorCode | None, ceiling_ft: float | None = None
) -> bool | None:
    """Whether the reported colour agrees with the computed one; ``None`` if either is missing.

    ``BLU+`` is BLU for the visibility threshold and also needs no ceiling below 20,000 ft: ``ceiling_ft`` is the
    lowest BKN/OVC base (``None`` when unknown or none, which never contradicts it).

    Plain ``YLO`` agrees with a computed YLO1 or YLO2: older tables had a single yellow and reports differ on which
    they mean.
    """
    if reported is None or reported.code is None or computed is None:
        return None
    if reported.code is ColorCode.YLO:
        return computed in (ColorCode.YLO1, ColorCode.YLO2)
    if reported.plus and reported.code is ColorCode.BLU:
        return computed is ColorCode.BLU and (ceiling_ft is None or ceiling_ft >= BLU_PLUS_CEILING_FT)
    return reported.code is computed
