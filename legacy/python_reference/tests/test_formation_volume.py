"""Unit tests for FormationVolumeIntegrator closed mesh volume calculation (Ticket 03)."""

from __future__ import annotations

import numpy as np
import pytest
from paleo_workbench.env_bootstrap import ensure_geoviz_on_path

ensure_geoviz_on_path()

from paleo_workbench.viz.formation_volume import FormationVolumeIntegrator


def test_formation_volume_integrator_box_volume():
    # 10x10 grid from x=0..9, y=0..9 (9x9 units)
    x, y = np.meshgrid(np.linspace(0, 10, 11), np.linspace(0, 10, 11))
    top_z = np.full_like(x, 100.0)
    bot_z = np.full_like(x, 80.0)

    top_verts = np.column_stack([x.ravel(), y.ravel(), top_z.ravel()])
    bot_verts = np.column_stack([x.ravel(), y.ravel(), bot_z.ravel()])

    integrator = FormationVolumeIntegrator()
    volume = integrator.compute_closed_volume(top_verts, bot_verts, grid_shape=(11, 11))

    # Expected volume: 10 * 10 * (100 - 80) = 2000.0
    assert volume == pytest.approx(2000.0, rel=1e-3)


def test_formation_volume_integrator_deformed_surface():
    x, y = np.meshgrid(np.linspace(0, 10, 11), np.linspace(0, 10, 11))
    top_z = 100.0 + 0.5 * x
    bot_z = 80.0 + 0.5 * x  # Uniform thickness = 20.0

    top_verts = np.column_stack([x.ravel(), y.ravel(), top_z.ravel()])
    bot_verts = np.column_stack([x.ravel(), y.ravel(), bot_z.ravel()])

    integrator = FormationVolumeIntegrator()
    volume = integrator.compute_closed_volume(top_verts, bot_verts, grid_shape=(11, 11))

    assert volume == pytest.approx(2000.0, rel=1e-3)
