"""Seismic facies prediction workflow helpers (workbench side).

Runs mock adapter with seismic asset binding and tags target_horizon so the
prediction page / mapping compile share one stratigraphic context.
"""

from __future__ import annotations

from paleo_workbench.pipeline.assets import bind_prediction_assets, suggest_assets_for_demo
from paleo_workbench.prediction.adapters import MockPredictionAdapter
from paleo_workbench.project.models import PredictionTask, ProjectDocument
from paleo_workbench.workflow.stratigraphy import active_target_horizon


def run_seismic_facies_prediction(
    project: ProjectDocument,
    *,
    seed: int = 0,
) -> PredictionTask:
    """Create a complete seismic facies PredictionTask bound to project SEGY.

    Uses factor-map ids when available; always binds the first available seismic
    resource so SeismicView can load a real volume when present.
    """
    factor_ids = [
        task.id
        for task in project.factor_map_tasks
        if getattr(task, "status", "") == "complete"
    ]
    adapter = MockPredictionAdapter()
    task = adapter.run(project, factor_ids, seed=seed)
    suggestion = suggest_assets_for_demo(project)
    bind_prediction_assets(
        project,
        task,
        well_log_ids=suggestion["well_log_ids"],
        seismic_ids=suggestion["seismic_ids"],
    )
    horizon = active_target_horizon(project) or project.stratigraphy.target_horizon or ""
    task.name = f"地震相预测 · {horizon or 'demo'}"
    meta = dict(task.model_metadata or {})
    meta["workflow"] = "seismic_facies"
    meta["target_horizon"] = horizon
    task.model_metadata = meta
    summary = dict(task.result_summary or {})
    summary["workflow"] = "seismic_facies"
    summary["target_horizon"] = horizon
    task.result_summary = summary
    return task


# Labels aligned with geoviz_seismic.attribute_pipeline (subset for workbench UI)
SEISMIC_ATTRIBUTE_LABELS = (
    "振幅",
    "包络",
    "瞬时相位",
    "瞬时频率",
    "RMS振幅",
    "甜点",
)

SEISMIC_DISPLAY_MODES = ("vd", "wiggle")
