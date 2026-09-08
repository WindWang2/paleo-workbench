from __future__ import annotations

import logging
import math
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MAX_CACHE_SIZE = 16

# Bounded preview loaders (#1193). The engine's ``load_las_preview`` /
# ``load_xml_preview`` are PREVIEW loaders: whenever a file declares more
# rows than ``max_samples`` they decimate (min-max binning for LAS, uniform
# stride for XML). That is correct for rendering, dishonest for ML inference.
PREVIEW_MAX_SAMPLES = 100_000
# "Full resolution" for the engine contract = a max_samples ceiling no real
# well log can exceed (both engine paths keep every row when
# ``row_count <= max_samples``; ``None`` is not accepted by the engine API).
FULL_RESOLUTION_MAX_SAMPLES = 1 << 27


@dataclass(frozen=True)
class WellLogDecimationInfo:
    """Honest sampling record for one well-log load (#1193).

    ``original_row_count`` is the row count declared by the file header
    (LAS ``~ASCII`` rows / XML ``<data>`` rows; 0 when the header could not
    be inspected). ``returned_sample_count`` is what the loaded document
    actually carries. ``decimated`` is True only when the loader's sampling
    bound engaged (``original_row_count > max_samples``) — the small
    difference caused by null-depth row filtering alone is not decimation.
    """

    path: str
    loader: str  # "preview" | "full_resolution"
    max_samples: int
    original_row_count: int
    returned_sample_count: int
    decimated: bool
    sample_stride: int  # 1 = every row kept

    def as_dict(self) -> dict[str, Any]:
        return {
            "loader": self.loader,
            "max_samples": self.max_samples,
            "original_row_count": self.original_row_count,
            "returned_sample_count": self.returned_sample_count,
            "decimated": self.decimated,
            "sample_stride": self.sample_stride,
        }


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
# Full-resolution documents must never be served from (or evict) the preview
# cache: the cache key is (path, mtime), so sharing one cache would silently
# hand a decimated preview document to an ML caller that asked for every row.
#
# V4: the full-resolution cache has NO byte budget — WellLogCache bounds by
# entry count only, and a full-resolution document can carry millions of
# rows × dozens of curves. Its capacity is therefore deliberately tiny (2,
# not the preview cache's 16): the ML inference path consumes wells
# sequentially (one model run reads one well), so 2 entries cover the
# current + previous well while capping worst-case residency at two
# full-resolution documents instead of sixteen.
_FULL_RES_CACHE_SIZE = 2
_full_res_cache = WellLogCache(_FULL_RES_CACHE_SIZE)


class WellLogDataWithDepthUnit:
    """Duck-type wrapper: proxies WellLogData attributes + exposes ``depth_unit``.

    The engine's ``WellLogData`` has no depth-unit field (the ``~C`` block's
    ``DEPT.FT`` header unit is dropped by its loader), and pydantic rejects
    unknown setattr fields, so the detected unit rides along on a wrapper
    (same convention as ``WellLogDataWithMarkers`` in correlation_overlay).

    V6 §3: ``depth_unit`` may be ``None`` — an undeclared/unknown unit is a
    first-class state, never coerced to meters. ``depth_unit_declared``
    distinguishes a header-declared unit (True) from a unit the file never
    declared (False; ``depth_unit`` is then always None). Unit-dependent
    consumers must gate on :func:`paleo_workbench.workflow.well_science.require_depth_unit`.
    """

    __slots__ = ("_base", "depth_unit", "depth_unit_declared")

    def __init__(self, base: Any, depth_unit: str | None, *, depth_unit_declared: bool = True) -> None:
        object.__setattr__(self, "_base", base)
        object.__setattr__(self, "depth_unit", depth_unit)
        object.__setattr__(self, "depth_unit_declared", bool(depth_unit_declared))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._base, name)

    @property
    def base(self) -> Any:
        return self._base


def detect_depth_unit(path: str) -> str | None:
    """Return the depth-axis unit declared in the LAS ``~C`` block.

    Uses the engine's own header parser so the result matches what the
    preview/loaders see: the DEPT/DEPTH curve's unit (``DEPT.FT``). Returns
    ``"m"`` or ``"ft"`` when declared; ``None`` when the file is not LAS,
    could not be inspected, or declares no/unknown unit — V6 §3: absence is
    *unknown*, never a meters fallback. Use
    :func:`detect_depth_unit_info` when the declared-vs-absent distinction
    is needed.
    """
    return detect_depth_unit_info(path).unit


def detect_depth_unit_info(path: str) -> "DepthUnitInfo":
    """Classified depth unit of a well-log file (see :func:`detect_depth_unit`)."""
    from paleo_workbench.workflow.well_science import classify_depth_unit

    file_path = Path(path)
    if file_path.suffix.lower() == ".xml":
        # The XML well-log format carries no depth-unit metadata at all.
        return classify_depth_unit(None)
    try:
        from geoviz import inspect_las_file

        header = inspect_las_file(str(file_path), header_only=True)
    except Exception:
        return classify_depth_unit(None)
    try:
        raw = str(getattr(header.curves[header.depth_index], "unit", "") or "")
    except (IndexError, AttributeError):
        return classify_depth_unit(None)
    return classify_depth_unit(raw)


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


class WellLogLoadCancelled(Exception):
    """The load was cancelled at a cooperative checkpoint (#1224).

    Raised BEFORE the parse starts or BETWEEN phases — the engine's
    single-call LAS/XML parse itself is non-interruptible, so cancellation
    is honest only at phase boundaries, never pretended mid-parse.
    """


def _cancel_check(cancel) -> None:
    if cancel is None:
        return
    # token protocol: callable > object with is_cancelled() > truthy fallback
    if callable(cancel):
        cancelled = bool(cancel())
    elif hasattr(cancel, "is_cancelled"):
        cancelled = bool(cancel.is_cancelled())
    else:
        cancelled = bool(cancel)
    if cancelled:
        raise WellLogLoadCancelled("cancelled at a load checkpoint")


def load_well_log_from_path(
    path: str,
    *,
    max_samples: int = PREVIEW_MAX_SAMPLES,
    cancel=None,
) -> Any | None:
    """Return engine ``WellLogData`` for LAS or XML well log files.

    Uses the engine's bounded preview loader, which internally dispatches
    to the registered C++ LAS parser hook when available. Files with more
    rows than *max_samples* are decimated (preview semantics — see
    :func:`well_log_decimation_info` to inspect how much was dropped, and
    :func:`load_well_log_full_resolution` for ML/scientific callers that
    must not silently lose samples).
    Results are cached in a bounded LRU cache per (path, mtime).

    *cancel* (V8 M8, #1224): callable returning True / object with
    ``is_cancelled`` — checked before the parse and between the parse and
    the unit-inspect phase. The engine parse itself is one non-interruptible
    call; cancelling during it raises at the NEXT checkpoint, never
    mid-parse.
    """
    return _load_well_log(path, max_samples=max_samples, cache=_las_cache,
                          loader_label="preview", cancel=cancel)


def load_well_log_full_resolution(path: str, *, cancel=None) -> Any | None:
    """Load a well log WITHOUT preview decimation (#1193).

    The engine has no ``max_samples=None`` mode; both of its loaders keep
    every row whenever ``row_count <= max_samples``, so full resolution is
    requested with a ceiling no real well log can exceed
    (:data:`FULL_RESOLUTION_MAX_SAMPLES`). This is the loader scientific /
    ML inference paths must use — a decimated preview must never be sent to
    a model as though it were the complete log.
    """
    return _load_well_log(path, max_samples=FULL_RESOLUTION_MAX_SAMPLES,
                          cache=_full_res_cache, loader_label="full_resolution",
                          cancel=cancel)


def _returned_sample_count(well_log: Any) -> int:
    """Sample count of the loaded document (first curve's depth length)."""
    for curve in list(getattr(well_log, "curves", None) or []):
        depth = list(getattr(curve, "depth", None) or [])
        if depth:
            return len(depth)
    return 0


def _original_row_count(path: str) -> int:
    """Row count declared by the file (0 when not inspectable).

    Uses the engine's FULL header inspect: ``header_only=True`` skips the
    ASCII scan and always reports ``row_count=0``, which would hide
    decimation. The scan is O(rows) and only runs for explicit decimation
    queries — plain loads never call it.
    """
    file_path = Path(path)
    if file_path.suffix.lower() == ".xml":
        # The XML loader exposes no header-only row count; the full-resolution
        # load keeps every row, so the loaded document IS the original count.
        return 0
    try:
        from geoviz import inspect_las_file

        header = inspect_las_file(str(file_path))
        return int(getattr(header, "row_count", 0) or 0)
    except Exception:
        return 0


def well_log_decimation_info(
    path: str,
    well_log: Any = None,
    *,
    loader: str = "preview",
    max_samples: int = PREVIEW_MAX_SAMPLES,
) -> WellLogDecimationInfo | None:
    """Decimation record for *path* (optionally for an already-loaded doc).

    ``decimated`` reflects the loader's own criterion
    (``original_row_count > max_samples``). ``sample_stride`` is the
    decimation ratio the engine derives from that criterion (the fast LAS
    channel then preserves curve extrema inside that budget rather than
    sampling on a fixed grid — the ratio, not the grid, is the contract).
    """
    file_path = Path(path)
    if not file_path.is_file():
        return None
    if well_log is None:
        well_log = load_well_log_from_path(str(file_path), max_samples=max_samples)
    returned = _returned_sample_count(well_log) if well_log is not None else 0
    original = _original_row_count(str(file_path))
    if loader == "full_resolution" and original == 0:
        # XML exposes no header row count; the full-resolution load keeps
        # every row, so the loaded document IS the original count.
        original = returned
    decimated = bool(original > max_samples)
    stride = max(1, math.ceil(original / max_samples)) if original > 0 else 1
    return WellLogDecimationInfo(
        path=str(file_path),
        loader=loader,
        max_samples=max_samples,
        original_row_count=original,
        returned_sample_count=returned,
        decimated=decimated,
        sample_stride=stride,
    )


def _load_well_log(path: str, *, max_samples: int, cache: WellLogCache, loader_label: str, cancel=None) -> Any | None:
    file_path = Path(path)
    if not file_path.is_file():
        return None

    try:
        mtime = file_path.stat().st_mtime
    except OSError:
        return None

    cache_key = (str(file_path), mtime)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        from geoviz import load_las_preview, load_xml_preview
    except Exception:
        return None

    # Cooperative checkpoint #1: refuse to START an expensive parse for a
    # request that is already cancelled (#1224 — the slot is released
    # without burning the parse).
    _cancel_check(cancel)

    try:
        if file_path.suffix.lower() == ".xml":
            result = load_xml_preview(
                str(file_path),
                max_curves=30,
                max_samples=max_samples,
            )
        else:
            result = load_las_preview(
                str(file_path),
                max_curves=30,
                max_samples=max_samples,
                fast=True,
            )

        # Cooperative checkpoint #2: the parse finished, but the unit
        # inspect + wrap phases are still ahead — a cancelled request stops
        # here instead of completing work nobody waits for.
        _cancel_check(cancel)

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
            depth_info = detect_depth_unit_info(str(file_path))
            if depth_info.unit is not None:
                # Wrap whenever the unit is KNOWN — including meters
                # (review R2-P0: meters-wrapped files used to load bare and
                # every V6 unit gate then failed closed on properly declared
                # data). Only truly undeclared/unrecognized units stay bare
                # (unknown is a first-class state, never coerced to "m").
                result = WellLogDataWithDepthUnit(
                    result,
                    depth_info.unit,
                    depth_unit_declared=depth_info.declared,
                )
            cache.put(cache_key, result)
        return result
    except WellLogLoadCancelled:
        raise  # cancellation is a first-class outcome, never a load failure
    except Exception as exc:
        # #1193: distinguish corrupt/unreadable files in logs (was silent).
        logger.warning("could not load well log %s: %s: %s", path, type(exc).__name__, exc)
        return None
