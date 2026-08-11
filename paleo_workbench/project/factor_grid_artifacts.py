"""Project-lifecycle bridge for persisted single-factor grid artifacts.

Interpolation deliberately leaves a completed grid on its ``FactorMapTask`` until the
project has a concrete save location.  At that point this module atomically moves the
large numerical payload into the project's managed artifact layout and leaves compact
metadata on the task.  Keeping this transition outside the renderer and interpolation
modules makes save/reopen, catalog registration, and legacy migration deterministic.
"""

from __future__ import annotations

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
    "persist_factor_grid_artifacts",
    "store_live_factor_grid",
]


# These fields are the sizeable numerical payload.  All remaining task parameters are
# algorithm/input metadata and must survive migration unchanged.
GRID_ARRAY_PARAMETER_KEYS = frozenset({"grid_x", "grid_y", "grid_z", "grid_var"})

# In-session single source of truth for completed grids.  Avoids re-coercing nested
# Python lists into float32 when contour / native render runs before project save.
# Keyed by FactorMapTask.id; never persisted.  Bounded LRU so abandoned tasks cannot
# retain multi-megabyte grids indefinitely; re-interpolation / save still clear entries.
_LIVE_FACTOR_GRIDS: OrderedDict[str, FactorGridResult] = OrderedDict()
_LIVE_FACTOR_GRIDS_LOCK = threading.RLock()
_LIVE_FACTOR_GRIDS_MAX = 64


def store_live_factor_grid(task_id: str, result: FactorGridResult) -> None:
    """Register the canonical ndarray grid for an in-memory task."""
    if not task_id:
        return
    if not isinstance(result, FactorGridResult):
        raise TypeError("result must be a FactorGridResult")
    key = str(task_id)
    with _LIVE_FACTOR_GRIDS_LOCK:
        if key in _LIVE_FACTOR_GRIDS:
            _LIVE_FACTOR_GRIDS.move_to_end(key)
        _LIVE_FACTOR_GRIDS[key] = result
        while len(_LIVE_FACTOR_GRIDS) > _LIVE_FACTOR_GRIDS_MAX:
            _LIVE_FACTOR_GRIDS.popitem(last=False)


def clear_live_factor_grid(task_id: str | None) -> None:
    """Drop a live grid (e.g. after externalisation or re-interpolation)."""
    if task_id:
        with _LIVE_FACTOR_GRIDS_LOCK:
            _LIVE_FACTOR_GRIDS.pop(str(task_id), None)


def factor_grid_result_for_task(
    task: "FactorMapTask",
    *,
    crs: str | None = None,
) -> FactorGridResult:
    """Return a task's grid without triggering interpolation.

    Resolution order:
    1. Managed NPZ artifact (authoritative after project save)
    2. In-session live FactorGridResult (post-interpolation, pre-save)
    3. Legacy inline ``parameters`` lists / arrays
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
        # Always return a defensive shell so consumers cannot mutate the cache.
        return FactorGridResult(
            grid_z=np.array(live.grid_z, copy=True, order="C"),
            grid_x=np.array(live.grid_x, copy=True, order="C"),
            grid_y=np.array(live.grid_y, copy=True, order="C"),
            factor_name=live.factor_name,
            algorithm_id=live.algorithm_id,
            algorithm_parameters=dict(live.algorithm_parameters),
            crs=crs if crs is not None else live.crs,
            unit=live.unit,
            generator_version=live.generator_version,
            source_refs=list(live.source_refs),
            run_ref=live.run_ref,
            created_at=live.created_at,
            variance_grid=(
                None
                if live.variance_grid is None
                else np.array(live.variance_grid, copy=True, order="C")
            ),
            boundary=list(live.boundary) if live.boundary is not None else None,
        )
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
