"""Prediction service module.

The previous ``SeismicPredictionTask`` ("ResNet3D_Facies_v1" deep neural
network) was a dead fake — it claimed a trained AI model that does not exist
and was removed in the P2 scientific-honesty wave. The honest, registry-backed
replacements live in :mod:`paleo_workbench.prediction.providers`:

- :class:`DemoModelProvider` — deterministic synthetic demo (``demo_only=True``,
  never presented as production).
- :class:`LocalAssetProvider` — the real GR-median heuristic, honestly labelled
  ``final_scientific_prediction=False`` / ``model_type="heuristic"``.

Run them through :mod:`paleo_workbench.prediction.inference_service` so the
result is tracked as a catalog DataRun + DERIVED DataVersion.
"""

from __future__ import annotations

from paleo_workbench.prediction.providers import (
    DemoModelProvider,
    InferenceInputError,
    LocalAssetProvider,
)

__all__ = ["DemoModelProvider", "InferenceInputError", "LocalAssetProvider"]
