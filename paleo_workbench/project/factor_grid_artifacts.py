"""Project-lifecycle bridge for persisted single-factor grid artifacts.

Interpolation deliberately leaves a completed grid on its ``FactorMapTask`` until the
project has a concrete save location.  At that point this module atomically moves the
large numerical payload into the project's managed artifact layout and leaves compact
metadata on the task.  Keeping this transition outside the renderer and interpolation
modules makes save/reopen, catalog registration, and legacy migration deterministic.
"""

from __future__ import annotations

import os
import threading
from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from paleo_workbench.catalog.grid_artifact import read_grid_artifact, write_grid_artifact
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
    "store_live_factor_grid",
]


# These fields are the sizeable numerical payload.  All remaining task parameters are
# algorithm/input metadata and must survive migration unchanged.
GRID_ARRAY_PARAMETER_KEYS = frozenset({"grid_x", "grid_y", "grid_z", "grid_var"})

# ---------------------------------------------------------------------------
# Live FactorGrid cache — entry-count LRU *and* byte budget.
#
# Env overrides (documented defaults):
#   PALEO_LIVE_FACTOR_GRIDS_MAX         max entries (default 64)
#   PALEO_LIVE_FACTOR_GRIDS_MAX_BYTES   max payload bytes (default 256 MiB)
#
# Arrays are stored writeable=False.  Get returns a shell sharing those
# immutable buffers (no full defensive copy).  Callers that need a mutable
# buffer use FactorGridResult.copied().
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
# 256 MiB default: ~16× 1024² float32 grids, or many smaller ones.
_LIVE_FACTOR_GRIDS_MAX_BYTES = _env_bytes(
    "PALEO_LIVE_FACTOR_GRIDS_MAX_BYTES", 256 * 1024 * 1024
)

_LIVE_FACTOR_GRIDS: OrderedDict[str, FactorGridResult] = OrderedDict()
_LIVE_FACTOR_GRID_BYTES: dict[str, int] = {}
_LIVE_FACTOR_GRIDS_TOTAL_BYTES = 0
_LIVE_FACTOR_GRIDS_LOCK = threading.RLock()

# Geometry pool: shared frozen grid_x/grid_y for identical axes across factors.
_GEOMETRY_POOL: OrderedDict[str, tuple[np.ndarray, np.ndarray]] = OrderedDict()
_GEOMETRY_POOL_MAX = 32


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
    """Own a C-contiguous copy and mark read-only."""
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
    """Ensure the cached instance holds frozen contiguous arrays (possibly shared axes)."""
    geometry_id = None
    if isinstance(result.algorithm_parameters, dict):
        geometry_id = result.algorithm_parameters.get("geometry_id")
    gx, gy = intern_grid_axes(result.grid_x, result.grid_y, geometry_id=geometry_id)
    gz = _freeze_array(np.ascontiguousarray(result.grid_z, dtype=np.float32))
    var = None
    if result.variance_grid is not None:
        var = _freeze_array(
            np.ascontiguousarray(result.variance_grid, dtype=np.float32)
        )
    # Rebuild through constructor so statistics stay consistent; arrays already
    # float32/float64 so _finalise owns via copy then we re-freeze below.
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
    # _finalise may have re-copied; freeze again.
    sealed.grid_z = _freeze_array(sealed.grid_z)
    sealed.grid_x = gx  # keep shared geometry
    sealed.grid_y = gy
    if sealed.variance_grid is not None:
        sealed.variance_grid = _freeze_array(sealed.variance_grid)
    return sealed


def _evict_until_fit(additional_bytes: int = 0) -> None:
    """Evict LRU entries until under entry and byte limits (caller holds lock)."""
    global _LIVE_FACTOR_GRIDS_TOTAL_BYTES
    while _LIVE_FACTOR_GRIDS and (
        len(_LIVE_FACTOR_GRIDS) > _LIVE_FACTOR_GRIDS_MAX
        or _LIVE_FACTOR_GRIDS_TOTAL_BYTES + additional_bytes
        > _LIVE_FACTOR_GRIDS_MAX_BYTES
    ):
        # If only one entry and it alone exceeds budget, still keep it (must store).
        if (
            len(_LIVE_FACTOR_GRIDS) == 1
            and additional_bytes > 0
            and _LIVE_FACTOR_GRIDS_TOTAL_BYTES + additional_bytes
            > _LIVE_FACTOR_GRIDS_MAX_BYTES
        ):
            # Drop the existing one to make room for the new insert.
            pass
        elif (
            len(_LIVE_FACTOR_GRIDS) <= _LIVE_FACTOR_GRIDS_MAX
            and _LIVE_FACTOR_GRIDS_TOTAL_BYTES + additional_bytes
            <= _LIVE_FACTOR_GRIDS_MAX_BYTES
        ):
            break
        old_key, _old = _LIVE_FACTOR_GRIDS.popitem(last=False)
        old_bytes = _LIVE_FACTOR_GRID_BYTES.pop(old_key, 0)
        _LIVE_FACTOR_GRIDS_TOTAL_BYTES = max(
            0, _LIVE_FACTOR_GRIDS_TOTAL_BYTES - old_bytes
        )


def store_live_factor_grid(task_id: str, result: FactorGridResult) -> None:
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
        _evict_until_fit(nbytes)
        _LIVE_FACTOR_GRIDS[key] = sealed
        _LIVE_FACTOR_GRIDS.move_to_end(key)
        _LIVE_FACTOR_GRID_BYTES[key] = nbytes
        _LIVE_FACTOR_GRIDS_TOTAL_BYTES += nbytes
        # Hard entry cap after insert
        while len(_LIVE_FACTOR_GRIDS) > _LIVE_FACTOR_GRIDS_MAX:
            old_key, _ = _LIVE_FACTOR_GRIDS.popitem(last=False)
            old_bytes = _LIVE_FACTOR_GRID_BYTES.pop(old_key, 0)
            _LIVE_FACTOR_GRIDS_TOTAL_BYTES = max(
                0, _LIVE_FACTOR_GRIDS_TOTAL_BYTES - old_bytes
            )


def clear_live_factor_grid(task_id: str | None) -> None:
    """Drop a live grid (e.g. after externalisation or re-interpolation)."""
    global _LIVE_FACTOR_GRIDS_TOTAL_BYTES
    if not task_id:
        return
    key = str(task_id)
    with _LIVE_FACTOR_GRIDS_LOCK:
        if key in _LIVE_FACTOR_GRIDS:
            del _LIVE_FACTOR_GRIDS[key]
            old_bytes = _LIVE_FACTOR_GRID_BYTES.pop(key, 0)
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
        }


def factor_grid_result_for_task(
    task: "FactorMapTask",
    *,
    crs: str | None = None,
    copy: bool = False,
) -> FactorGridResult:
    """Return a task's grid without triggering interpolation.

    Resolution order:
    1. Managed NPZ artifact (authoritative after project save)
    2. In-session live FactorGridResult (post-interpolation, pre-save)
    3. Legacy inline ``parameters`` lists / arrays

    By default live-cache hits return a lightweight shell that *shares* the
    frozen ndarray buffers (no O(grid) defensive copy).  Pass ``copy=True``
    or call ``.copied()`` when a mutable private buffer is required.
    """
    artifact_path = getattr(task, "grid_artifact_path", None)
    if artifact_path:
        return read_grid_artifact(artifact_path)
    key = str(getattr(task, "id", "") or "")
    with _LIVE_FACTOR_GRIDS_LOCK:
        live = _LIVE_FACTOR_GRIDS.get(key)
        if live is not None:
            _LIVE_FACTOR_GRIDS.move_to_end(key)
    if live is not None:
        shell = FactorGridResult(
            grid_z=live.grid_z,  # frozen shared
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
        # Re-freeze after _finalise (which may re-copy writable buffers).
        shell.grid_z = live.grid_z if shell.grid_z is live.grid_z else _freeze_array(shell.grid_z)
        shell.grid_x = live.grid_x
        shell.grid_y = live.grid_y
        if live.variance_grid is not None:
            shell.variance_grid = live.variance_grid
        if copy:
            return shell.copied()
        return shell
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
    """Externalize completed inline grids and return the tasks that changed.

    A task is rewritten when it has an inline ``grid_z`` payload *or* a live
    in-session grid.  Thus a save after reopen does not rewrite immutable
    catalog-backed data, while a new interpolation overwrites the deterministic
    sidecar and deliberately clears the old catalog-version reference so the
    controller registers a fresh intermediate.
    """
    path = Path(project_path)
    destination = ensure_artifact_layout(path) / "factor_maps"
    changed: list["FactorMapTask"] = []
    for task in project.factor_map_tasks:
        parameters = dict(task.parameters or {})
        task_id = str(getattr(task, "id", "") or "")
        with _LIVE_FACTOR_GRIDS_LOCK:
            has_live = task_id in _LIVE_FACTOR_GRIDS
        has_inline = parameters.get("grid_z") is not None
        if not has_inline and not has_live:
            continue
        result = factor_grid_result_for_task(
            task, crs=project.coordinate.project_crs or None
        )
        artifact = write_grid_artifact(result, destination, task.id)
        task.grid_artifact_path = artifact.resolve().as_posix()
        task.grid_artifact_version_id = None
        task.parameters = {
            key: value
            for key, value in parameters.items()
            if key not in GRID_ARRAY_PARAMETER_KEYS
        }
        clear_live_factor_grid(task_id)
        changed.append(task)
    return changed
