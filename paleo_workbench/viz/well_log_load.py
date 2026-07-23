from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Any

_MAX_CACHE_SIZE = 16
_las_cache: OrderedDict[tuple[str, float], Any] = OrderedDict()


def load_well_log_from_path(path: str) -> Any | None:
    """Return engine ``WellLogData`` for LAS or XML well log files.

    Uses the engine's bounded preview loader, which internally dispatches
    to the registered C++ LAS parser hook when available.
    Results are cached in a bounded LRU cache per (path, mtime).
    """
    file_path = Path(path)
    if not file_path.is_file():
        return None

    try:
        mtime = file_path.stat().st_mtime
    except OSError:
        return None

    cache_key = (str(file_path), mtime)
    if cache_key in _las_cache:
        _las_cache.move_to_end(cache_key)
        return _las_cache[cache_key]

    try:
        from geoviz import load_las_preview, load_xml_preview
    except Exception:
        return None

    try:
        if file_path.suffix.lower() == ".xml":
            result = load_xml_preview(
                str(file_path),
                max_curves=30,
                max_samples=100_000,
            )
        else:
            result = load_las_preview(
                str(file_path),
                max_curves=30,
                max_samples=100_000,
                fast=True,
            )

        if result is not None:
            _las_cache[cache_key] = result
            _las_cache.move_to_end(cache_key)
            while len(_las_cache) > _MAX_CACHE_SIZE:
                _las_cache.popitem(last=False)
        return result
    except Exception:
        return None
