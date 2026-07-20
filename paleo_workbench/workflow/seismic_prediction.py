"""Seismic facies prediction workflow helpers (workbench side).

Uses LocalAssetPredictionAdapter (ISS-PRED-01) with seismic/LAS asset binding
and tags target_horizon so prediction page / mapping compile share context.
"""

from __future__ import annotations

from paleo_workbench.project.models import PredictionTask, ProjectDocument
from paleo_workbench.workflow.facies_prediction import run_facies_prediction


def run_seismic_facies_prediction(
    project: ProjectDocument,
    *,
    seed: int = 0,
) -> PredictionTask:
    """Create a complete seismic facies PredictionTask bound to project SEGY.

    Uses factor-map ids when available; always binds the first available seismic
    resource so SeismicView can load a real volume when present.
    """
    return run_facies_prediction(
        project,
        seed=seed,
        workflow="seismic_facies",
        name_prefix="地震相预测",
    )


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
