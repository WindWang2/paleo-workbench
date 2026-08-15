from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Any

_MAX_CACHE_SIZE = 16
_las_cache: OrderedDict[tuple[str, float], Any] = OrderedDict()


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
            depth_unit = detect_depth_unit(str(file_path))
            if depth_unit != "m":
                result = WellLogDataWithDepthUnit(result, depth_unit)
            _las_cache[cache_key] = result
            _las_cache.move_to_end(cache_key)
            while len(_las_cache) > _MAX_CACHE_SIZE:
                _las_cache.popitem(last=False)
        return result
    except Exception:
        return None
