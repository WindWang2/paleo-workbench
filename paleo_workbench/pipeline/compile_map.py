"""18c contract stub — implement in Phase 18c."""

from __future__ import annotations

from paleo_workbench.project.models import PaleoMapDocument, ProjectDocument


def compile_map_draft(
    project: ProjectDocument,
    *,
    target_horizon: str | None = None,
    prediction_task_id: str | None = None,
    seed: int = 0,
) -> PaleoMapDocument:
    raise NotImplementedError("Phase 18c: compile_map_draft")
