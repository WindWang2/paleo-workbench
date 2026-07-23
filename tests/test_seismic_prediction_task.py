"""Unit tests for SeismicPredictionTask dual tensor payload & VisualizationWorkspace integration (Ticket 03)."""

from __future__ import annotations

import numpy as np
import pytest
from paleo_workbench.env_bootstrap import ensure_geoviz_on_path

ensure_geoviz_on_path()

from paleo_workbench.services.prediction_service import SeismicPredictionTask
from paleo_workbench.ui.pages.composite_visualization_panel import VisualizationWorkspace
from paleo_workbench.viz.models import VizPayload


def test_seismic_prediction_task_dual_tensors():
    volume = np.random.randn(20, 20, 40).astype(np.float32)
    task = SeismicPredictionTask(name="Facies_Prediction", input_volume=volume)

    payload = task.run_inference()

    assert payload.kind == "prediction"
    assert payload.class_map is not None
    assert payload.prob_map is not None

    # Class map is uint8, prob map is float32
    assert payload.class_map.dtype == np.uint8
    assert payload.prob_map.dtype == np.float32
    assert payload.class_map.shape == (20, 20, 40)
    assert payload.prob_map.shape == (20, 20, 40)
    assert np.all(payload.prob_map >= 0.0) and np.all(payload.prob_map <= 1.0)


def test_visualization_workspace_loads_prediction_dual_tensors(qtbot):
    workspace = VisualizationWorkspace()
    qtbot.addWidget(workspace)

    volume = np.random.randn(10, 10, 20).astype(np.float32)
    task = SeismicPredictionTask(name="Delta_Facies", input_volume=volume)
    payload = task.run_inference()

    workspace.load(payload)

    # Status label confirms successful loading of prediction payload
    assert "Delta_Facies" in workspace.status_label.text()
