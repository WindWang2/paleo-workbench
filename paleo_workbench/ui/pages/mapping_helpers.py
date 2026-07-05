from __future__ import annotations

from typing import Any


def field_value(source: Any, name: str, default: Any = None) -> Any:
    if source is None:
        return default
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


def active_map_document(map_documents: list | tuple | None):
    if not map_documents:
        return None
    return map_documents[-1]
