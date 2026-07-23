"""Unit tests for HorizonSculpting RBF brush surface editing engine (Ticket 01 & 02)."""

from __future__ import annotations

import numpy as np
import pytest
from paleo_workbench.env_bootstrap import ensure_geoviz_on_path

ensure_geoviz_on_path()

from paleo_workbench.viz.horizon_sculpting import HorizonSculpting, SculptableHorizonMesh


def test_horizon_sculpting_deforms_surface_vertices():
    # 10x10 horizon surface mesh at z=100.0
    x, y = np.meshgrid(np.arange(10, dtype=np.float32), np.arange(10, dtype=np.float32))
    z = np.full_like(x, 100.0)

    vertices = np.column_stack([x.ravel(), y.ravel(), z.ravel()])

    sculptor = HorizonSculpting()
    # Sculpt pointer at center (4.5, 4.5), elevation delta +10.0, radius 3.0
    modified = sculptor.sculpt_surface(
        vertices=vertices,
        center_xy=(4.5, 4.5),
        delta_z=10.0,
        radius=3.0,
    )

    dist = np.hypot(modified[:, 0] - 4.5, modified[:, 1] - 4.5)
    center_mask = dist <= 1.0
    far_mask = dist >= 4.0

    assert np.all(modified[center_mask, 2] > 105.0)
    assert np.allclose(modified[far_mask, 2], 100.0)


def test_sculptable_horizon_mesh_undo_redo():
    x, y = np.meshgrid(np.arange(10, dtype=np.float32), np.arange(10, dtype=np.float32))
    z = np.full_like(x, 50.0)
    vertices = np.column_stack([x.ravel(), y.ravel(), z.ravel()])

    mesh = SculptableHorizonMesh(vertices)
    assert not mesh.can_undo()
    assert not mesh.can_redo()

    # Sculpt 1
    mesh.sculpt_surface(center_xy=(2.0, 2.0), delta_z=15.0, radius=2.5)
    assert mesh.can_undo()
    edited_z = mesh.vertices[:, 2].copy()
    assert np.max(edited_z) > 60.0

    # Undo
    assert mesh.undo()
    assert np.allclose(mesh.vertices[:, 2], 50.0)
    assert mesh.can_redo()

    # Redo
    assert mesh.redo()
    assert np.allclose(mesh.vertices[:, 2], edited_z)


def test_horizon_sculpting_anneals_surface_smoothly():
    sculptor = HorizonSculpting()
    # Create noisy grid surface
    z_grid = np.random.uniform(90.0, 110.0, size=(10, 10)).astype(np.float32)
    smoothed = sculptor.smooth_anneal(z_grid, iterations=3)

    assert smoothed.shape == (10, 10)
    # Variance of smoothed surface should decrease
    assert np.var(smoothed) < np.var(z_grid)
