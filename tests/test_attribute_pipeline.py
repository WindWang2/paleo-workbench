"""Unit tests for AttributePipeline & AttributeTaskWorker (Ticket 02)."""

from __future__ import annotations

import time

import numpy as np
import pytest
from paleo_workbench.env_bootstrap import ensure_geoviz_on_path

ensure_geoviz_on_path()

from paleo_workbench.viz.seismic_3d_api import AttributePipeline, AttributeTaskWorker


def test_attribute_pipeline_coherence_computation():
    # 3D dummy volume 20x20x50
    rng = np.random.default_rng(2)
    volume = rng.standard_normal((20, 20, 50)).astype(np.float32)

    pipeline = AttributePipeline()
    result = pipeline.compute_attribute(volume, attribute_type="coherence_3d")

    assert result.shape == (20, 20, 50)
    assert result.dtype == np.float32
    assert np.all(result >= 0.0) and np.all(result <= 1.0)


def test_attribute_task_worker_asynchronous(qtbot):
    rng = np.random.default_rng(2)
    volume = rng.standard_normal((15, 15, 30)).astype(np.float32)
    worker = AttributeTaskWorker(volume=volume, attribute_type="coherence_3d")

    progresses: list[float] = []
    results: list[np.ndarray] = []

    worker.progress_changed.connect(progresses.append)
    worker.result_ready.connect(results.append)

    worker.start()
    qtbot.waitUntil(lambda: len(results) > 0, timeout=3000)

    assert len(results) == 1
    assert results[0].shape == (15, 15, 30)
    assert len(progresses) > 0
    assert progresses[-1] == pytest.approx(100.0)
