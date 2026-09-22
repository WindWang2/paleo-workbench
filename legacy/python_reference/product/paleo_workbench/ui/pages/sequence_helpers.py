from __future__ import annotations

from typing import Any


def field_value(source: Any, name: str, default: Any = "") -> Any:
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)
