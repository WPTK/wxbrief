"""JSON-ready dictionaries for decoded reports (the form stored in golden files).

Enums become their member names, datetimes ISO 8601 strings, tuples lists, and tokens carry their kinds. A remark
also names its variant (``"variant": "SeaLevelPressure"``) because remarks are a union of many classes.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from wxbrief.decode.model import Remark


def _convert(value: object) -> Any:
    if isinstance(value, Enum):
        return value.name
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        converted = {field.name: _convert(getattr(value, field.name)) for field in fields(value)}
        if isinstance(value, Remark):
            return {"variant": type(value).__name__, **converted}  # remarks are a union: say which one this is
        return converted
    if isinstance(value, tuple | list):
        return [_convert(item) for item in value]
    return value


def to_dict(obj: object) -> dict[str, Any]:
    """Convert a decoded report (any frozen dataclass of the model) to plain JSON types."""
    converted = _convert(obj)
    if not isinstance(converted, dict):
        raise TypeError(f"expected a dataclass instance, got {type(obj).__name__}")
    return converted
