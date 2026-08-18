"""Unit tests for FaultDisplacement vector offset engine (Ticket 02 & 03)."""

from __future__ import annotations

import numpy as np
import pytest
from paleo_workbench.env_bootstrap import ensure_geoviz_on_path

ensure_geoviz_on_path()

from paleo_workbench.viz.fault_displacement import FaultDisplacement


def test_fault_displacement_offsets_hanging_wall():
    # Horizon surface mesh: 10x10 grid at z=100.0
    x, y = np.meshgrid(np.arange(10, dtype=np.float32), np.arange(10, dtype=np.float32))
    z = np.full_like(x, 100.0)
    vertices = np.column_stack([x.ravel(), y.ravel(), z.ravel()])

    engine = FaultDisplacement()
    # Fault line along x=5.0, hanging wall x >= 5.0 drops by throw_z=15.0
    displaced = engine.apply_fault_throw(
        vertices=vertices,
        fault_line_x=5.0,
        throw_z=-15.0,
    )

    # Classify by PRE-fault geometry: the signed heave (#846) moves the
    # hanging wall horizontally too, so post-displacement x would mislabel
    # moved vertices as footwall.
    footwall_mask = vertices[:, 0] < 5.0
    hangingwall_mask = vertices[:, 0] >= 5.0

    assert np.allclose(displaced[footwall_mask, 2], 100.0)
    assert np.allclose(displaced[hangingwall_mask, 2], 85.0)


def test_fault_displacement_distance_decay():
    engine = FaultDisplacement()
    vertices = np.array([
        [4.0, 5.0, 100.0],  # Footwall
        [5.1, 5.0, 100.0],  # Near Fault Hanging Wall
        [10.0, 5.0, 100.0], # Far Hanging Wall
    ], dtype=np.float32)

    displaced = engine.apply_fault_throw(
        vertices=vertices,
        fault_line_x=5.0,
        throw_z=-20.0,
        decay_radius=3.0,
    )

    assert displaced[0, 2] == 100.0  # Unchanged
    assert displaced[1, 2] < 100.0   # Near fault displaced significantly
    assert displaced[2, 2] > displaced[1, 2]  # Far hanging wall decays


def test_fault_displacement_preserves_topology():
    engine = FaultDisplacement()
    vertices = np.array([
        [4.9, 5.0, 100.0],
        [5.1, 5.0, 100.0],
    ], dtype=np.float32)

    displaced = engine.apply_fault_throw(vertices, fault_line_x=5.0, throw_z=-20.0)
    assert displaced[0, 2] == 100.0
    assert displaced[1, 2] == 80.0
