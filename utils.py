"""Shared pure numeric helpers.

This module contains only stateless, side-effect-free utility functions.
No DB, no I/O, no framework dependencies.
"""

from __future__ import annotations

import math
from typing import Any


def safe_float(value: Any, default: float = 0.0) -> float:
    """Safely convert *value* to float, returning *default* on failure."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(result) or math.isinf(result):
        return default
    return result


def safe_int(value: Any, default: int = 0) -> int:
    """Safely convert *value* to int, returning *default* on failure."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
