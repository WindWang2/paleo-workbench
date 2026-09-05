from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MAX_CACHE_SIZE = 16


class WellLogCache:
    """Thread-safe bounded LRU cache for parsed well-log documents (#1041).

    GUI-thread cache hits (``is_well_log_cached`` + the synchronous fast path
    in ``load_well_log_from_path``) race worker-thread inserts and evictions
    (``WellLogLoadWorker`` / ``CorrelationLoadWorker`` / prediction loaders),
    so every entry operation — lookup, insert, LRU reorder, eviction, clear —
    runs under one re-entrant lock. Values are never ``None``: the loader
    only caches successfully parsed documents, which keeps ``get``'s
    miss sentinel unambiguous.
    """

    def __init__(self, max_entries: int = _MAX_CACHE_SIZE) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        self._lock = threading.RLock()
        self._max_entries = int(max_entries)
        self._entries: OrderedDict[tuple[str, float], Any] = OrderedDict()

    @property
    def max_entries(self) -> int:
        return self._max_entries

    def contains(self, key: tuple[str, float]) -> bool:
        with self._lock:
            return key in self._entries

    def get(self, key: tuple[str, float]) -> Any | None:
        """Return the cached value (promoting it to most-recent), or None."""
        with self._lock:
            value = self._entries.get(key)
            if value is not None:
                self._entries.move_to_end(key)
            return value

    def put(self, key: tuple[str, float], value: Any) -> None:
        if value is None:
            return
        with self._lock:
            self._entries[key] = value
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def evict(self, key: tuple[str, float]) -> bool:
        """Drop one entry explicitly (e.g. the file changed on disk)."""
        with self._lock:
            return self._entries.pop(key, None) is not None

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


_las_cache = WellLogCache(_MAX_CACHE_SIZE)


class WellLogDataWithDepthUnit:
    """Duck-type wrapper: proxies WellLogData attributes + exposes ``depth_unit``.

    The engine's ``WellLogData`` has no depth-unit field (the ``~C`` block's
    ``DEPT.FT`` header unit is dropped by its loader), and pydantic rejects
    unknown setattr fields, so the detected unit rides along on a wrapper
    (same convention as ``WellLogDataWithMarkers`` in correlation_overlay).
    """

    __slots__ = ("_base", "depth_unit")

    def __init__(self, base: Any, depth_unit: str) -> None:
        object.__setattr__(self, "_base", base)
        object.__setattr__(self, "depth_unit", depth_unit)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._base, name)

    @property
    def base(self) -> Any:
        return self._base


_FT_UNITS = frozenset({"FT", "F", "FEET", "FOOT"})
_M_UNITS = frozenset({"M", "METER", "METERS", "MTR", "MTRS"})


def detect_depth_unit(path: str) -> str:
    """Return the LAS depth-axis unit ("m" or "ft") declared in ``~C``.

    Uses the engine's own header parser so the result matches what the
    preview/loaders see: the DEPT/DEPTH curve's unit (``DEPT.FT``). Returns
    "m" when the file is not LAS or the unit is not declared.
    """
    file_path = Path(path)
    if file_path.suffix.lower() == ".xml":
        return "m"
    try:
        from geoviz import inspect_las_file

        header = inspect_las_file(str(file_path), header_only=True)
    except Exception:
        return "m"
    try:
        unit = str(getattr(header.curves[header.depth_index], "unit", "") or "").strip().upper()
    except (IndexError, AttributeError):
        return "m"
    if unit in _FT_UNITS:
        return "ft"
    if unit in _M_UNITS:
        return "m"
    return "m"


def is_well_log_cached(path: str) -> bool:
    """True when a load result for *path* is already in the LRU cache.

    Cheap stat-key check without parsing, so callers can keep the synchronous
    fast path on a cache hit and defer only cold parses to a worker thread
    (#842).
    """
    if not path:
        return False
    file_path = Path(path)
    try:
        mtime = file_path.stat().st_mtime
    except OSError:
        return False
    return _las_cache.contains((str(file_path), mtime))


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
    cached = _las_cache.get(cache_key)
    if cached is not None:
        return cached

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
            # #1193: preview decimation is for display — never let it reach
            # inference silently. Flag carriers warn here; the prediction
            # provider records the flags in its result diagnostics.
            if bool(getattr(result, "decimated", False)):
                logger.warning(
                    "well log %s is decimated for preview (%s of %s rows); "
                    "not full resolution",
                    file_path.name,
                    sum(len(getattr(c, "depth", []) or []) for c in (getattr(result, "curves", []) or [])[:1]),
                    getattr(result, "total_rows", "?"),
                )
            depth_unit = detect_depth_unit(str(file_path))
            if depth_unit != "m":
                result = WellLogDataWithDepthUnit(result, depth_unit)
            _las_cache.put(cache_key, result)
        return result
    except Exception as exc:
        # #1193: distinguish corrupt/unreadable files in logs (was silent).
        logger.warning("could not load well log %s: %s: %s", path, type(exc).__name__, exc)
        return None
