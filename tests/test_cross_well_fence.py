"""Unit tests for CrossWellFenceGenerator 2D/3D seismic fence engine (Ticket 03)."""

from __future__ import annotations

import numpy as np
import pytest
from paleo_workbench.env_bootstrap import ensure_geoviz_on_path

ensure_geoviz_on_path()

from paleo_workbench.viz.geomodel import CrossWellFenceGenerator


def test_cross_well_fence_generator_mesh():
    wells = [
        {"name": "W1", "x": 0.0, "y": 0.0, "depth": 1000.0},
        {"name": "W2", "x": 10.0, "y": 10.0, "depth": 1200.0},
        {"name": "W3", "x": 20.0, "y": 5.0, "depth": 1100.0},
    ]

    verts, faces, colors = CrossWellFenceGenerator.generate_fence_mesh(wells, nz_samples=10)

    assert len(verts) > 0
    assert len(faces) > 0
    assert len(colors) == len(faces)
    assert verts.shape[1] == 3
    assert faces.shape[1] == 3


def test_cross_well_fence_extract_seismic_slice():
    seismic_vol = np.random.uniform(-1.0, 1.0, size=(20, 20, 50)).astype(np.float32)
    wells = [
        {"name": "W1", "x": 2, "y": 3},
        {"name": "W2", "x": 12, "y": 15},
    ]

    slice_2d = CrossWellFenceGenerator.extract_seismic_slice(seismic_vol, wells, n_samples_per_segment=10)

    assert slice_2d.shape == (50, 10)
