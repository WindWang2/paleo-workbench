"""TDD Tests for Advanced Geological & Well-Seismic Analysis.

Tests:
1. RGBAttributeFusion: Blending 3 attribute channels (R, G, B) into RGBA mesh colors.
2. LithologyCrossplotEngine: Generating 2D/3D scatter data and cluster centroids for AI vs GR.
3. CrossWellFenceGenerator: Generating 3D curtain mesh panels connecting adjacent wells.
"""
from __future__ import annotations

import numpy as np
import pytest

from paleo_workbench.viz.geomodel.well_seismic import (
    RGBAttributeFusion,
    LithologyCrossplotEngine,
    CrossWellFenceGenerator,
)


def test_rgb_attribute_fusion():
    """Test fusing 3 scalar attribute arrays into RGBA color array."""
    size = (20, 20)
    attr_r = np.linspace(0.0, 1.0, 400).reshape(size)
    attr_g = np.ones(size) * 0.5
    attr_b = np.linspace(1.0, 0.0, 400).reshape(size)

    rgba = RGBAttributeFusion.blend_rgb(attr_r, attr_g, attr_b, alpha=0.8)

    assert rgba.shape == (20, 20, 4)
    assert np.all(rgba[..., 3] == 0.8)  # Alpha check
    assert 0.0 <= np.min(rgba) <= np.max(rgba) <= 1.0


def test_lithology_crossplot_engine():
    """Test lithology crossplot data extraction and cluster statistics."""
    gr = np.array([30.0, 40.0, 110.0, 120.0, 25.0], dtype=np.float32)
    ai = np.array([8000.0, 7500.0, 4500.0, 4200.0, 9000.0], dtype=np.float32)
    lithology = ["砂岩", "砂岩", "泥岩", "泥岩", "石灰岩"]

    result = LithologyCrossplotEngine.analyze(gr, ai, lithology)

    assert "points" in result
    assert "clusters" in result
    assert len(result["points"]) == 5
    assert "砂岩" in result["clusters"]
    assert "泥岩" in result["clusters"]
    # Check centroid calculation for Sandstone
    sand_cluster = result["clusters"]["砂岩"]
    assert abs(sand_cluster["mean_gr"] - 35.0) < 1e-3
    assert abs(sand_cluster["mean_ai"] - 7750.0) < 1e-3


def test_cross_well_fence_generator():
    """Test generating 3D fence/curtain surface geometry between well locations."""
    wells = [
        {"name": "Well A", "x": -40.0, "y": -40.0, "depth": 150.0},
        {"name": "Well B", "x": 40.0, "y": -40.0, "depth": 180.0},
        {"name": "Well C", "x": 40.0, "y": 40.0, "depth": 160.0},
    ]

    verts, faces, colors = CrossWellFenceGenerator.generate_fence_mesh(wells, nz_samples=20)

    assert len(verts) > 0
    assert len(faces) > 0
    assert len(colors) == len(faces)
    assert verts.shape[1] == 3
    assert faces.shape[1] == 3
