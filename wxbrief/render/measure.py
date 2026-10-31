"""Formatting of measured quantities per ``UnitsMode``.

Unit symbols (kt, SM, hPa ...) are never translated, so this module needs no catalog. Digits and separators are
English for now; the i18n session routes them through the catalog's ``[meta]`` table.

A report is in one system (US: knots, statute miles, feet, inHg, Fahrenheit-style; metric: m/s, metres, hPa, Celsius).
``US`` and ``METRIC`` modes show that system first and keep the reported value in parentheses when it differs;
``MIXED`` shows the reported value first and the other system in parentheses.
"""

from __future__ import annotations

from enum import Enum
from fractions import Fraction

from wxbrief.decode.units import (
    HPA_PER_INHG,
    METERS_PER_FOOT,
    Distance,
    DistanceUnit,
    Pressure,
    PressureUnit,
    Speed,
    SpeedUnit,
    Temperature,
    TemperatureUnit,
    UnitsMode,
)


class _System(Enum):
    US = "us"
    METRIC = "metric"


def _combine(units: UnitsMode, source: _System, us_text: str, metric_text: str) -> str:
    """Pick the primary text for ``units`` and add the other system in parentheses where it helps."""
    if units is UnitsMode.US:
        return f"{us_text} ({metric_text})" if source is _System.METRIC else us_text
    if units is UnitsMode.METRIC:
        return f"{metric_text} ({us_text})" if source is _System.US else metric_text
    if source is _System.US:
        return f"{us_text} ({metric_text})"
    return f"{metric_text} ({us_text})"


def format_int(value: float) -> str:
    """Whole number with a thousands separator (``3,000``)."""
    return f"{round(value):,}"


def format_decimal(value: float, places: int = 1) -> str:
    """``value`` with up to ``places`` decimals, trailing zeros dropped (``1.2``, ``10``)."""
    text = f"{value:.{places}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def format_miles(value: float, *, exact: bool) -> str:
    """Statute miles. Reported values are shown as written (fractions); converted ones as decimals above 1 SM."""
    if value == 0:
        return "0"
    if exact or value < 1:
        # A converted value is rounded to the nearest sixteenth and never shown as zero.
        fraction = Fraction(value).limit_denominator(16) if exact else Fraction(max(1, round(value * 16)), 16)
        whole, rest = divmod(fraction.numerator, fraction.denominator)
        if rest == 0:
            return str(whole)
        part = f"{rest}/{fraction.denominator}"
        return f"{whole} {part}" if whole else part
    if value >= 10:
        return str(round(value))
    return format_decimal(value, 1)


def format_visibility(distance: Distance, units: UnitsMode) -> str:
    """Visibility in the requested system."""
    source = _System.US if distance.unit is DistanceUnit.SM else _System.METRIC
    reported_us = distance.unit is DistanceUnit.SM
    us_text = f"{format_miles(distance.statute_miles, exact=reported_us)} SM"
    meters = distance.meters
    if distance.unit is DistanceUnit.KM or meters >= 1000:
        km = meters / 1000
        metric_text = f"{format_decimal(km, 1)} km"
    else:
        step = 1 if distance.unit is DistanceUnit.M else 10
        metric_text = f"{round(meters / step) * step} m"
    return _combine(units, source, us_text, metric_text)


def format_short_distance(distance: Distance, units: UnitsMode) -> str:
    """Cloud heights and RVR: feet or metres."""
    source = _System.US if distance.unit is DistanceUnit.FT else _System.METRIC
    if distance.unit is DistanceUnit.FT:
        us_text = f"{format_int(distance.value)} ft"
    else:
        us_text = f"{format_int(round(distance.feet / 10) * 10)} ft"
    if distance.unit is DistanceUnit.M:
        metric_text = f"{format_int(distance.value)} m"
    else:
        metric_text = f"{format_int(distance.meters)} m"
    return _combine(units, source, us_text, metric_text)


def format_speed(speed: Speed, units: UnitsMode) -> str:
    source = _System.US if speed.unit is SpeedUnit.KT else _System.METRIC
    us_text = f"{format_int(speed.value if speed.unit is SpeedUnit.KT else speed.knots)} kt"
    match speed.unit:
        case SpeedUnit.MPS:
            metric_text = f"{format_int(speed.value)} m/s"
        case SpeedUnit.KMH:
            metric_text = f"{format_int(speed.value)} km/h"
        case SpeedUnit.KT:
            metric_text = f"{format_int(speed.kmh)} km/h"
    return _combine(units, source, us_text, metric_text)


def format_pressure(pressure: Pressure, units: UnitsMode, *, precise: bool = False) -> str:
    """Altimeter or QNH; ``precise`` keeps the tenth of a hectopascal that sea-level pressure carries."""
    source = _System.US if pressure.unit is PressureUnit.INHG else _System.METRIC
    us_text = f"{pressure.inhg:.2f} inHg"
    metric_text = f"{pressure.hpa:.1f} hPa" if precise else f"{round(pressure.hpa)} hPa"
    return _combine(units, source, us_text, metric_text)


def format_pressure_change(hpa: float, units: UnitsMode) -> str:
    """A pressure difference reported in hectopascals (the 3-hour tendency)."""
    us_text = f"{hpa / HPA_PER_INHG:.2f} inHg"
    metric_text = f"{format_decimal(hpa, 1)} hPa"
    return _combine(units, _System.METRIC, us_text, metric_text)


def format_temperature(temperature: Temperature, units: UnitsMode, *, precise: bool = False) -> str:
    """Temperature; ``precise`` keeps the tenth of a degree of the T-group."""
    source = _System.METRIC if temperature.unit is TemperatureUnit.C else _System.US
    if precise:
        us_text = f"{temperature.fahrenheit:.1f} °F"
        metric_text = f"{temperature.celsius:.1f} °C"
    else:
        us_text = f"{round(temperature.fahrenheit)} °F"
        metric_text = f"{round(temperature.celsius)} °C"
    return _combine(units, source, us_text, metric_text)


MM_PER_INCH = 25.4
MM_PER_CM = 10


def format_inches(inches: float, units: UnitsMode) -> str:
    """A small length reported in inches (precipitation, snow depth, hail size)."""
    us_text = f"{format_decimal(inches, 2)} in"
    metric_text = f"{format_decimal(inches * MM_PER_INCH, 1)} mm"
    return _combine(units, _System.US, us_text, metric_text)


def format_millimeters(mm: float, units: UnitsMode) -> str:
    """A deposit depth reported in millimetres (shown in centimetres from 10 cm up)."""
    metric_text = f"{format_decimal(mm / MM_PER_CM, 1)} cm" if mm >= 100 else f"{format_decimal(mm, 1)} mm"
    us_text = f"{format_decimal(mm / MM_PER_INCH, 2)} in"
    return _combine(units, _System.METRIC, us_text, metric_text)


def format_wave_height(meters: float, units: UnitsMode) -> str:
    """Significant wave height reported in metres."""
    us_text = f"{format_decimal(meters / METERS_PER_FOOT, 1)} ft"
    metric_text = f"{format_decimal(meters, 1)} m"
    return _combine(units, _System.METRIC, us_text, metric_text)
