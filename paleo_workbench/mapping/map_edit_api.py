"""Geometry façade for the mapping editor.

Python implementation first; optional map_edit_core C++ extension later.
"""

from __future__ import annotations

from typing import Any


def hit_test(
    records: list[dict[str, Any]] | None,
    x: float,
    y: float,
    tolerance: float = 0.0,
) -> str | None:
    """Return the feature id under (x, y), or None.

    Stub for Task 3 — full spatial hit-test arrives with select/move tools.
    """
    return None
