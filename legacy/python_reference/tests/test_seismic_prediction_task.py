"""Honesty tests: DemoModelProvider + VisualizationWorkspace payload loading.

The former ``SeismicPredictionTask`` ("ResNet3D_Facies_v1" deep neural
network) was a dead fake and was removed in the P2 scientific-honesty wave.
Its deterministic demo math now lives in
:class:`paleo_workbench.prediction.providers.DemoModelProvider`, explicitly
marked ``demo_only`` / ``demo=True`` / ``source="synthetic/demo"`` and never
presentable as a scientific prediction.
"""

from __future__ import annotations

import numpy as np

from paleo_workbench.env_bootstrap import ensure_geoviz_on_path

ensure_geoviz_on_path()

from paleo_workbench.prediction.providers import DemoModelProvider  # noqa: E402
from paleo_workbench.ui.pages.composite_visualization_panel import (  # noqa: E402
    VisualizationWorkspace,
)
from paleo_workbench.viz.models import VizPayload  # noqa: E402


def test_demo_provider_marks_demo_output():
    provider = DemoModelProvider()
    result = provider.run(inputs={}, parameters={"seed": 3})

    assert provider.demo_only is True
    assert result["demo"] is True
    assert result["source"] == "synthetic/demo"
    summary = result["result_summary"]
    assert summary["is_mock"] is True
    assert summary["final_scientific_prediction"] is False
    assert summary["model_type"] == "demo"
    # Deterministic for the same seed
    again = DemoModelProvider().run(inputs={}, parameters={"seed": 3})
    assert again["result_summary"]["predicted_regions"] == summary["predicted_regions"]
    # Different seed changes the template
    other = DemoModelProvider().run(inputs={}, parameters={"seed": 9})
    assert other["result_summary"]["predicted_regions"] != summary["predicted_regions"]


def test_visualization_workspace_loads_demo_prediction_payload(qtbot):
    workspace = VisualizationWorkspace()
    qtbot.addWidget(workspace)

    rng = np.random.RandomState(7)
    volume = rng.randn(10, 10, 20).astype(np.float32)
    # Deterministic demo facies map — the same math the removed fake used, now
    # honestly labeled as a demo payload, not an AI inference.
    prob_map = np.clip(np.sin(volume * 0.5) * 0.4 + 0.5, 0.0, 1.0).astype(np.float32)
    class_map = ((np.abs(volume * 2.0).astype(np.uint8) % 4) + 1)
    payload = VizPayload(
        kind="prediction",
        label="演示预测 (Demo): Delta_Facies",
        seismic_volume=volume,
        class_map=class_map,
        prob_map=prob_map,
    )

    workspace.load(payload)

    # Status label confirms successful loading of the demo payload
    assert "Delta_Facies" in workspace.status_label.text()
    assert payload.prob_map.dtype == np.float32
    assert np.all(payload.prob_map >= 0.0) and np.all(payload.prob_map <= 1.0)
