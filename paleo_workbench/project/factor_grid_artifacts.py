"""Project-lifecycle bridge for persisted single-factor grid artifacts.

Interpolation deliberately leaves a completed grid on its ``FactorMapTask`` until the
project has a concrete save location.  At that point this module atomically moves the
large numerical payload into the project's managed artifact layout and leaves compact
metadata on the task.  Keeping this transition outside the renderer and interpolation
modules makes save/reopen, catalog registration, and legacy migration deterministic.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from paleo_workbench.catalog.grid_artifact import read_grid_artifact, write_grid_artifact
from paleo_workbench.project.paths import ensure_artifact_layout
from paleo_workbench.workflow.factor_grid_result import FactorGridResult

if TYPE_CHECKING:
    from paleo_workbench.project.models import FactorMapTask, ProjectDocument

__all__ = [
    "GRID_ARRAY_PARAMETER_KEYS",
    "factor_grid_result_for_task",
    "persist_factor_grid_artifacts",
]


# These fields are the sizeable numerical payload.  All remaining task parameters are
# algorithm/input metadata and must survive migration unchanged.
GRID_ARRAY_PARAMETER_KEYS = frozenset({"grid_x", "grid_y", "grid_z", "grid_var"})


def factor_grid_result_for_task(
    task: "FactorMapTask",
    *,
    crs: str | None = None,
) -> FactorGridResult:
    """Return a task's grid without triggering interpolation.

    Managed artifacts are authoritative.  The inline form is read only as a legacy
    compatibility path; a normal project save migrates it out of the JSON document.
    """
    artifact_path = getattr(task, "grid_artifact_path", None)
    if artifact_path:
        return read_grid_artifact(artifact_path)
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

    A task is rewritten only when it actually has an inline ``grid_z`` payload.  Thus a
    save after reopen does not rewrite immutable catalog-backed data, while a new
    interpolation overwrites the deterministic sidecar and deliberately clears the old
    catalog-version reference so the controller registers a fresh intermediate.
    """
    path = Path(project_path)
    destination = ensure_artifact_layout(path) / "factor_maps"
    changed: list["FactorMapTask"] = []
    for task in project.factor_map_tasks:
        parameters = dict(task.parameters or {})
        if parameters.get("grid_z") is None:
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
        changed.append(task)
    return changed
