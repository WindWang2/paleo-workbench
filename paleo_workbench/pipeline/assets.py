"""18b: bind project resources to PredictionTask.input_refs."""

from __future__ import annotations

from typing import Any

from paleo_workbench.prediction.adapters import MockPredictionAdapter
from paleo_workbench.project.models import PredictionTask, ProjectDocument

WELL_KEY = "well_log_resource_ids"
SEISMIC_KEY = "seismic_resource_ids"


def suggest_assets_for_demo(
    project: ProjectDocument,
    *,
    max_wells: int = 5,
    max_seismic: int = 1,
) -> dict[str, Any]:
    wells = sorted(
        (r for r in project.resources if r.type == "well_log"),
        key=lambda r: (r.name or "", r.id),
    )
    seismics = sorted(
        (r for r in project.resources if r.type == "seismic"),
        key=lambda r: (r.name or "", r.id),
    )
    return {
        "well_log_ids": [r.id for r in wells[:max_wells]],
        "seismic_ids": [r.id for r in seismics[:max_seismic]],
    }


def bind_prediction_assets(
    project: ProjectDocument,
    task: PredictionTask,
    *,
    well_log_ids: list[str] | None = None,
    seismic_ids: list[str] | None = None,
) -> PredictionTask:
    """Mutate task.input_refs; filter to existing resource ids of correct type."""
    by_id = {r.id: r for r in project.resources}
    refs = dict(task.input_refs or {})

    if well_log_ids is not None:
        refs[WELL_KEY] = [
            rid
            for rid in well_log_ids
            if rid in by_id and by_id[rid].type == "well_log"
        ]
    if seismic_ids is not None:
        refs[SEISMIC_KEY] = [
            rid
            for rid in seismic_ids
            if rid in by_id and by_id[rid].type == "seismic"
        ]
    task.input_refs = refs
    return task


def ensure_demo_prediction(
    project: ProjectDocument,
    *,
    seed: int = 0,
) -> PredictionTask:
    """Ensure one mock prediction task exists and is bound to demo assets.

    If the latest task already has well/seismic refs, return it.
    Elif the latest task is unbound, bind suggested assets.
    Else create via MockPredictionAdapter (empty factor ids) and bind.
    """
    suggestion = suggest_assets_for_demo(project)
    if project.prediction_tasks:
        task = project.prediction_tasks[-1]
        has_refs = bool(
            (task.input_refs or {}).get(WELL_KEY)
            or (task.input_refs or {}).get(SEISMIC_KEY)
        )
        if has_refs:
            return task
        return bind_prediction_assets(
            project,
            task,
            well_log_ids=suggestion["well_log_ids"],
            seismic_ids=suggestion["seismic_ids"],
        )

    task = MockPredictionAdapter().run(project, [], seed)
    return bind_prediction_assets(
        project,
        task,
        well_log_ids=suggestion["well_log_ids"],
        seismic_ids=suggestion["seismic_ids"],
    )
