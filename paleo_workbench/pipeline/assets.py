"""18b contract stubs — implement in Phase 18b."""

from __future__ import annotations

from typing import Any

from paleo_workbench.project.models import PredictionTask, ProjectDocument


def bind_prediction_assets(
    project: ProjectDocument,
    task: PredictionTask,
    *,
    well_log_ids: list[str] | None = None,
    seismic_ids: list[str] | None = None,
) -> PredictionTask:
    raise NotImplementedError("Phase 18b: bind_prediction_assets")


def suggest_assets_for_demo(project: ProjectDocument) -> dict[str, Any]:
    raise NotImplementedError("Phase 18b: suggest_assets_for_demo")
