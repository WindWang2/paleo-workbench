"""Project-lifecycle bridge for persisted single-factor grid artifacts.

Architecture (Stage-3 artifact-first):

* **Unsaved:** ``FactorGridResult`` in the live byte-budget cache is the
  canonical numerical payload; ``FactorMapTask.parameters`` holds only small
  metadata (no full ``grid_x/y/z`` lists).
* **Saved:** atomic managed ``.factor_grid.npz`` is the on-disk source of truth;
  the task stores the artifact path + descriptor metadata.
* **Reopen:** artifact → one load → seal into the same bounded cache → shared
  read-only consumers.

Legacy projects that still embed inline ``parameters[grid_*]`` remain readable
and migrate to artifacts on the next project save (READ OLD / WRITE NEW).
"""

from __future__ import annotations

import os
import threading
from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from paleo_workbench.catalog.grid_artifact import (
    artifact_file_identity,
    read_grid_artifact,
    write_grid_artifact,
)
from paleo_workbench.project.paths import ensure_artifact_layout
from paleo_workbench.workflow.factor_grid_result import FactorGridResult

if TYPE_CHECKING:
    from paleo_workbench.project.models import FactorMapTask, ProjectDocument

__all__ = [
    "GRID_ARRAY_PARAMETER_KEYS",
    "clear_live_factor_grid",
    "factor_grid_result_for_task",
    "live_factor_grid_cache_stats",
    "persist_factor_grid_artifacts",
    "reset_artifact_load_counter",
    "store_live_factor_grid",
]


# These fields are the sizeable numerical payload.  All remaining task parameters are
# algorithm/input metadata and must survive migration unchanged.
GRID_ARRAY_PARAMETER_KEYS = frozenset({"grid_x", "grid_y", "grid_z", "grid_var"})

# ---------------------------------------------------------------------------
# Unified session cache — LIVE (post-interp) and PERSISTED (artifact-backed)
#
# Env overrides:
#   PALEO_LIVE_FACTOR_GRIDS_MAX         max entries (default 64)
#   PALEO_LIVE_FACTOR_GRIDS_MAX_BYTES   max payload bytes (default 256 MiB)
# ---------------------------------------------------------------------------


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def _env_bytes(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        text = str(raw).strip().lower()
        mult = 1
        if text.endswith("kb"):
            mult, text = 1024, text[:-2]
        elif text.endswith("mb"):
            mult, text = 1024 * 1024, text[:-2]
        elif text.endswith("gb"):
            mult, text = 1024 * 1024 * 1024, text[:-2]
        elif text.endswith("b"):
            text = text[:-1]
        return max(1024 * 1024, int(float(text) * mult))
    except ValueError:
        return default


_LIVE_FACTOR_GRIDS_MAX = _env_int("PALEO_LIVE_FACTOR_GRIDS_MAX", 64)
_LIVE_FACTOR_GRIDS_MAX_BYTES = _env_bytes(
    "PALEO_LIVE_FACTOR_GRIDS_MAX_BYTES", 256 * 1024 * 1024
)

_LIVE_FACTOR_GRIDS: OrderedDict[str, FactorGridResult] = OrderedDict()
_LIVE_FACTOR_GRID_BYTES: dict[str, int] = {}
# task_id → artifact identity when the entry was loaded from disk (None for live-only)
_LIVE_ARTIFACT_IDENTITY: dict[str, tuple[str, int, int] | None] = {}
_LIVE_FACTOR_GRIDS_TOTAL_BYTES = 0
_LIVE_FACTOR_GRIDS_LOCK = threading.RLock()

_GEOMETRY_POOL: OrderedDict[str, tuple[np.ndarray, np.ndarray]] = OrderedDict()
_GEOMETRY_POOL_MAX = 32

# Test instrumentation: physical artifact loads (not cache hits).
_ARTIFACT_PHYSICAL_LOADS = 0


def reset_artifact_load_counter() -> None:
    """Reset the physical artifact-load counter (tests / benchmarks)."""
    global _ARTIFACT_PHYSICAL_LOADS
    with _LIVE_FACTOR_GRIDS_LOCK:
        _ARTIFACT_PHYSICAL_LOADS = 0


def _array_nbytes(arr: np.ndarray | None) -> int:
    if arr is None:
        return 0
    return int(np.asarray(arr).nbytes)


def factor_grid_payload_bytes(result: FactorGridResult) -> int:
    """Byte weight of the large arrays held by a FactorGridResult."""
    return (
        _array_nbytes(result.grid_z)
        + _array_nbytes(result.grid_x)
        + _array_nbytes(result.grid_y)
        + _array_nbytes(result.variance_grid)
    )


def _freeze_array(arr: np.ndarray) -> np.ndarray:
    """Seal a C-contiguous buffer as read-only with at most one ownership copy.

    Already-frozen C-contiguous arrays are returned as-is (zero-copy).
    Owned writable C-contiguous arrays of a numeric dtype are sealed in place.
    """
    if not isinstance(arr, np.ndarray):
        arr = np.asarray(arr)
    if (
        arr.flags["C_CONTIGUOUS"]
        and not arr.flags["WRITEABLE"]
    ):
        return arr
    if arr.flags["C_CONTIGUOUS"] and arr.flags["OWNDATA"]:
        # Transfer ownership: mark read-only without allocating a second buffer.
        try:
            arr.setflags(write=False)
            return arr
        except ValueError:
            pass
    owned = np.array(arr, copy=True, order="C")
    owned.setflags(write=False)
    return owned


def intern_grid_axes(
    grid_x: np.ndarray, grid_y: np.ndarray, *, geometry_id: str | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Return shared frozen axes, deduplicating identical geometry across factors."""
    gx = np.ascontiguousarray(grid_x, dtype=np.float64)
    gy = np.ascontiguousarray(grid_y, dtype=np.float64)
    if geometry_id:
        key = geometry_id
    else:
        h = hash((gx.shape, gy.shape, gx.tobytes(), gy.tobytes()))
        key = f"axes:{h & 0xFFFFFFFFFFFFFFFF:x}"
    with _LIVE_FACTOR_GRIDS_LOCK:
        hit = _GEOMETRY_POOL.get(key)
        if hit is not None:
            _GEOMETRY_POOL.move_to_end(key)
            return hit
        frozen = (_freeze_array(gx), _freeze_array(gy))
        _GEOMETRY_POOL[key] = frozen
        while len(_GEOMETRY_POOL) > _GEOMETRY_POOL_MAX:
            _GEOMETRY_POOL.popitem(last=False)
        return frozen


def _seal_result_arrays(result: FactorGridResult) -> FactorGridResult:
    """Ensure the cached instance holds frozen contiguous arrays (minimal copies)."""
    geometry_id = None
    if isinstance(result.algorithm_parameters, dict):
        geometry_id = result.algorithm_parameters.get("geometry_id")
    gx, gy = intern_grid_axes(result.grid_x, result.grid_y, geometry_id=geometry_id)

    gz_src = result.grid_z
    if gz_src.dtype != np.float32 or not gz_src.flags["C_CONTIGUOUS"]:
        gz_src = np.ascontiguousarray(gz_src, dtype=np.float32)
    gz = _freeze_array(gz_src)

    var = None
    if result.variance_grid is not None:
        var_src = result.variance_grid
        if var_src.dtype != np.float32 or not var_src.flags["C_CONTIGUOUS"]:
            var_src = np.ascontiguousarray(var_src, dtype=np.float32)
        var = _freeze_array(var_src)

    sealed = FactorGridResult(
        grid_z=gz,
        grid_x=gx,
        grid_y=gy,
        factor_name=result.factor_name,
        algorithm_id=result.algorithm_id,
        algorithm_parameters=dict(result.algorithm_parameters),
        crs=result.crs,
        unit=result.unit,
        generator_version=result.generator_version,
        source_refs=list(result.source_refs),
        run_ref=result.run_ref,
        created_at=result.created_at,
        variance_grid=var,
        boundary=list(result.boundary) if result.boundary is not None else None,
    )
    # Preserve trusted statistics if the constructor re-scanned a sealed buffer
    # that already had matching stats (artifact load path).
    if (
        hasattr(result, "statistics")
        and result.statistics.total_count == sealed.statistics.total_count
        and result.statistics.valid_count == sealed.statistics.valid_count
    ):
        sealed.statistics = result.statistics
    # Re-point to shared frozen buffers in case _finalise re-wrapped.
    sealed.grid_z = gz if sealed.grid_z is gz else _freeze_array(sealed.grid_z)
    sealed.grid_x = gx
    sealed.grid_y = gy
    if sealed.variance_grid is not None and var is not None:
        sealed.variance_grid = var if sealed.variance_grid is var else _freeze_array(
            sealed.variance_grid
        )
    return sealed


def _evict_until_fit(additional_bytes: int = 0) -> None:
    """Evict LRU entries until under entry and byte limits (caller holds lock)."""
    global _LIVE_FACTOR_GRIDS_TOTAL_BYTES
    while _LIVE_FACTOR_GRIDS and (
        len(_LIVE_FACTOR_GRIDS) > _LIVE_FACTOR_GRIDS_MAX
        or _LIVE_FACTOR_GRIDS_TOTAL_BYTES + additional_bytes
        > _LIVE_FACTOR_GRIDS_MAX_BYTES
    ):
        if (
            len(_LIVE_FACTOR_GRIDS) <= _LIVE_FACTOR_GRIDS_MAX
            and _LIVE_FACTOR_GRIDS_TOTAL_BYTES + additional_bytes
            <= _LIVE_FACTOR_GRIDS_MAX_BYTES
        ):
            break
        old_key, _old = _LIVE_FACTOR_GRIDS.popitem(last=False)
        old_bytes = _LIVE_FACTOR_GRID_BYTES.pop(old_key, 0)
        _LIVE_ARTIFACT_IDENTITY.pop(old_key, None)
        _LIVE_FACTOR_GRIDS_TOTAL_BYTES = max(
            0, _LIVE_FACTOR_GRIDS_TOTAL_BYTES - old_bytes
        )


def store_live_factor_grid(
    task_id: str,
    result: FactorGridResult,
    *,
    artifact_identity: tuple[str, int, int] | None = None,
) -> None:
    """Register the canonical ndarray grid for an in-memory task (byte-aware LRU)."""
    global _LIVE_FACTOR_GRIDS_TOTAL_BYTES
    if not task_id:
        return
    if not isinstance(result, FactorGridResult):
        raise TypeError("result must be a FactorGridResult")
    key = str(task_id)
    sealed = _seal_result_arrays(result)
    nbytes = factor_grid_payload_bytes(sealed)
    with _LIVE_FACTOR_GRIDS_LOCK:
        if key in _LIVE_FACTOR_GRIDS:
            prev = _LIVE_FACTOR_GRID_BYTES.pop(key, 0)
            _LIVE_FACTOR_GRIDS_TOTAL_BYTES = max(
                0, _LIVE_FACTOR_GRIDS_TOTAL_BYTES - prev
            )
            del _LIVE_FACTOR_GRIDS[key]
            _LIVE_ARTIFACT_IDENTITY.pop(key, None)
        _evict_until_fit(nbytes)
        _LIVE_FACTOR_GRIDS[key] = sealed
        _LIVE_FACTOR_GRIDS.move_to_end(key)
        _LIVE_FACTOR_GRID_BYTES[key] = nbytes
        _LIVE_ARTIFACT_IDENTITY[key] = artifact_identity
        _LIVE_FACTOR_GRIDS_TOTAL_BYTES += nbytes
        while len(_LIVE_FACTOR_GRIDS) > _LIVE_FACTOR_GRIDS_MAX:
            old_key, _ = _LIVE_FACTOR_GRIDS.popitem(last=False)
            old_bytes = _LIVE_FACTOR_GRID_BYTES.pop(old_key, 0)
            _LIVE_ARTIFACT_IDENTITY.pop(old_key, None)
            _LIVE_FACTOR_GRIDS_TOTAL_BYTES = max(
                0, _LIVE_FACTOR_GRIDS_TOTAL_BYTES - old_bytes
            )


def clear_live_factor_grid(task_id: str | None) -> None:
    """Drop a live/persisted-cache entry (re-interpolation or after externalisation)."""
    global _LIVE_FACTOR_GRIDS_TOTAL_BYTES
    if not task_id:
        return
    key = str(task_id)
    with _LIVE_FACTOR_GRIDS_LOCK:
        if key in _LIVE_FACTOR_GRIDS:
            del _LIVE_FACTOR_GRIDS[key]
            old_bytes = _LIVE_FACTOR_GRID_BYTES.pop(key, 0)
            _LIVE_ARTIFACT_IDENTITY.pop(key, None)
            _LIVE_FACTOR_GRIDS_TOTAL_BYTES = max(
                0, _LIVE_FACTOR_GRIDS_TOTAL_BYTES - old_bytes
            )


def live_factor_grid_cache_stats() -> dict[str, int | float]:
    """Observability for tests / benchmarks."""
    with _LIVE_FACTOR_GRIDS_LOCK:
        return {
            "entries": len(_LIVE_FACTOR_GRIDS),
            "total_bytes": int(_LIVE_FACTOR_GRIDS_TOTAL_BYTES),
            "max_entries": int(_LIVE_FACTOR_GRIDS_MAX),
            "max_bytes": int(_LIVE_FACTOR_GRIDS_MAX_BYTES),
            "geometry_pool_entries": len(_GEOMETRY_POOL),
            "artifact_physical_loads": int(_ARTIFACT_PHYSICAL_LOADS),
        }


def _shell_from_live(
    live: FactorGridResult, *, crs: str | None, copy: bool
) -> FactorGridResult:
    shell = FactorGridResult(
        grid_z=live.grid_z,
        grid_x=live.grid_x,
        grid_y=live.grid_y,
        factor_name=live.factor_name,
        algorithm_id=live.algorithm_id,
        algorithm_parameters=dict(live.algorithm_parameters),
        crs=crs if crs is not None else live.crs,
        unit=live.unit,
        generator_version=live.generator_version,
        source_refs=list(live.source_refs),
        run_ref=live.run_ref,
        created_at=live.created_at,
        variance_grid=live.variance_grid,
        boundary=list(live.boundary) if live.boundary is not None else None,
    )
    shell.grid_z = live.grid_z if shell.grid_z is live.grid_z else _freeze_array(shell.grid_z)
    shell.grid_x = live.grid_x
    shell.grid_y = live.grid_y
    if live.variance_grid is not None:
        shell.variance_grid = live.variance_grid
    if (
        hasattr(live, "statistics")
        and live.statistics.total_count == shell.statistics.total_count
    ):
        shell.statistics = live.statistics
    if copy:
        return shell.copied()
    return shell


def factor_grid_result_for_task(
    task: "FactorMapTask",
    *,
    crs: str | None = None,
    copy: bool = False,
) -> FactorGridResult:
    """Return a task's grid without triggering interpolation.

    Resolution order:
    1. Managed NPZ artifact (authoritative after project save), via warm cache
    2. In-session live FactorGridResult (post-interpolation, pre-save)
    3. Legacy inline ``parameters`` lists / arrays

    Repeated reads of the same immutable artifact hit the session cache (no
    repeated decompress).  Pass ``copy=True`` or call ``.copied()`` for a
    mutable private buffer.
    """
    global _ARTIFACT_PHYSICAL_LOADS
    artifact_path = getattr(task, "grid_artifact_path", None)
    key = str(getattr(task, "id", "") or "")
    artifact_missing: FileNotFoundError | None = None

    if artifact_path:
        identity = None
        try:
            identity = artifact_file_identity(artifact_path)
        except FileNotFoundError as err:
            # The artifact disappeared while the task still references it —
            # e.g. a failed Save-As rolled back the staged artifacts tree even
            # though this session's live grid is still valid. Fall through to
            # the live/legacy resolution below instead of bricking every later
            # save; the next successful save re-externalizes the grid and
            # rewrites ``grid_artifact_path`` (self-healing).
            artifact_missing = err
        except OSError as err:
            raise FileNotFoundError(
                f"factor grid artifact not readable: {artifact_path}"
            ) from err
        if identity is not None:
            with _LIVE_FACTOR_GRIDS_LOCK:
                live = _LIVE_FACTOR_GRIDS.get(key)
                if live is not None and _LIVE_ARTIFACT_IDENTITY.get(key) == identity:
                    _LIVE_FACTOR_GRIDS.move_to_end(key)
                    cached = live
                else:
                    cached = None
            if cached is not None:
                return _shell_from_live(cached, crs=crs, copy=copy)
            # Physical load (once per identity).
            loaded = read_grid_artifact(artifact_path)
            with _LIVE_FACTOR_GRIDS_LOCK:
                _ARTIFACT_PHYSICAL_LOADS += 1
            store_live_factor_grid(key, loaded, artifact_identity=identity)
            with _LIVE_FACTOR_GRIDS_LOCK:
                live = _LIVE_FACTOR_GRIDS.get(key)
            if live is None:
                return loaded if not copy else loaded.copied()
            return _shell_from_live(live, crs=crs, copy=copy)

    with _LIVE_FACTOR_GRIDS_LOCK:
        live = _LIVE_FACTOR_GRIDS.get(key)
        if live is not None:
            _LIVE_FACTOR_GRIDS.move_to_end(key)
    if live is not None:
        return _shell_from_live(live, crs=crs, copy=copy)

    if artifact_missing is not None:
        # No live grid and no legacy inline payload: the artifact really is
        # gone. Surface the original loss instead of a confusing KeyError.
        raise artifact_missing

    return FactorGridResult.from_legacy_task_parameters(
        dict(task.parameters or {}),
        factor_name=task.factor_type or task.name,
        crs=crs,
        metadata=dict(getattr(task, "grid_metadata", None) or {}),
    )


def persist_factor_grid_artifacts(
    project: "ProjectDocument",
    project_path: Path | str,
) -> list["FactorMapTask"]:
    """Externalize completed grids and return the tasks that changed.

    A task is rewritten when it has an inline ``grid_z`` payload *or* a live
    in-session grid.  After write, the live entry is re-keyed as artifact-backed
    (same sealed buffers; identity updated) so reopen-style reads stay warm.
    """
    path = Path(project_path)
    destination = ensure_artifact_layout(path) / "factor_maps"
    changed: list["FactorMapTask"] = []
    for task in project.factor_map_tasks:
        parameters = dict(task.parameters or {})
        task_id = str(getattr(task, "id", "") or "")
        with _LIVE_FACTOR_GRIDS_LOCK:
            has_live = task_id in _LIVE_FACTOR_GRIDS
            live_identity = _LIVE_ARTIFACT_IDENTITY.get(task_id)
        has_inline = parameters.get("grid_z") is not None
        if not has_inline and not has_live:
            continue
        # Skip rewrite when the live entry already matches an on-disk artifact
        # (no new catalog churn). Catalog registration rehomes the path under
        # intermediate/, so identity may change while the sealed live buffer
        # is still the canonical content — preserve grid_artifact_version_id.
        existing_path = getattr(task, "grid_artifact_path", None)
        existing_version = getattr(task, "grid_artifact_version_id", None)
        if has_live and existing_path and not has_inline:
            skip = False
            try:
                path_identity = artifact_file_identity(existing_path)
            except OSError:
                path_identity = None
            if live_identity is not None and path_identity == live_identity:
                skip = True
            elif existing_version and path_identity is not None:
                # Managed catalog path still on disk; re-key live identity.
                skip = True
            if skip:
                if path_identity is not None and path_identity != live_identity:
                    with _LIVE_FACTOR_GRIDS_LOCK:
                        if task_id in _LIVE_FACTOR_GRIDS:
                            _LIVE_ARTIFACT_IDENTITY[task_id] = path_identity
                continue
        result = factor_grid_result_for_task(
            task, crs=project.coordinate.project_crs or None
        )
        artifact = write_grid_artifact(result, destination, task.id)
        task.grid_artifact_path = artifact.resolve().as_posix()
        task.grid_artifact_version_id = None
        # Strip any legacy inline arrays (READ OLD / WRITE NEW).
        task.parameters = {
            key: value
            for key, value in parameters.items()
            if key not in GRID_ARRAY_PARAMETER_KEYS
        }
        # Keep sealed arrays warm under the new artifact identity.
        try:
            identity = artifact_file_identity(artifact)
        except OSError:
            identity = None
        store_live_factor_grid(task_id, result, artifact_identity=identity)
        changed.append(task)
    return changed
