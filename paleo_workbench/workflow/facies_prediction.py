"""Shared facies prediction run (workbench side).

Uses LocalAssetPredictionAdapter (ISS-PRED-01) with asset binding and tags
workflow/target_horizon so prediction pages and mapping compile share context.
"""

from __future__ import annotations

from paleo_workbench.pipeline.assets import bind_prediction_assets, suggest_assets_for_demo
from paleo_workbench.prediction.adapters import LocalAssetPredictionAdapter
from paleo_workbench.project.models import PredictionTask, ProjectDocument
from paleo_workbench.workflow.stratigraphy import active_target_horizon


def run_facies_prediction(
    project: ProjectDocument,
    *,
    seed: int = 0,
    workflow: str,
    name_prefix: str,
) -> PredictionTask:
    """Create a complete facies PredictionTask bound to project assets.

    Uses factor-map ids when available; binds suggested demo assets and tags
    ``workflow``/``target_horizon`` into model_metadata and result_summary.
    """
    factor_ids = [
        task.id
        for task in project.factor_map_tasks
        if getattr(task, "status", "") == "complete"
    ]
    adapter = LocalAssetPredictionAdapter()
    task = adapter.run(project, factor_ids, seed=seed)
    suggestion = suggest_assets_for_demo(project)
    bind_prediction_assets(
        project,
        task,
        well_log_ids=suggestion["well_log_ids"],
        seismic_ids=suggestion["seismic_ids"],
    )
    horizon = active_target_horizon(project) or project.stratigraphy.target_horizon or ""
    task.name = f"{name_prefix} · {horizon or 'demo'}"
    meta = dict(task.model_metadata or {})
    meta["workflow"] = workflow
    meta["target_horizon"] = horizon
    meta["adapter"] = task.adapter_kind
    task.model_metadata = meta
    summary = dict(task.result_summary or {})
    summary["workflow"] = workflow
    summary["target_horizon"] = horizon
    task.result_summary = summary
    return task
