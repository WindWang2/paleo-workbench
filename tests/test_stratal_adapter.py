"""Tests for the workbench stratal adapter (workflow glue over geoviz facade).

These use the synthetic demo volume/horizons so they run without a real SEGY or
OpenGL context. The engine math they delegate to is covered in the engine repo.
"""

from __future__ import annotations

import numpy as np


def test_demo_volume_has_structure():
    from paleo_workbench.viz.stratal_adapter import make_synthetic_demo_volume

    vol = make_synthetic_demo_volume((12, 14, 24), n_reflectors=3, seed=1)
    assert vol.shape == (12, 14, 24)
    assert vol.dtype == np.float32
    # Multiple reflectors => non-trivial variance.
    assert vol.std() > 0.05


def test_demo_grids_bracket_middle_and_are_inverted_safe():
    from paleo_workbench.viz.stratal_adapter import make_demo_stratal_grids

    vol, top, bot = make_demo_stratal_grids((12, 14, 24))
    assert top.shape == (12, 14)
    assert bot.shape == (12, 14)
    # Top must sit above bottom everywhere (no inverted pair).
    assert (bot >= top).all()
    # Both within sample range.
    assert (top >= 0).all() and (bot < 24).all()


def test_build_stratal_surfaces_masks_inverted_cells():
    from paleo_workbench.viz.stratal_adapter import build_stratal_surfaces

    top = np.array([[5.0, 15.0], [5.0, 5.0]])   # (0,1) inverted vs bot=10
    bot = np.full((2, 2), 10.0)
    out = build_stratal_surfaces(top, bot, (2, 2, 20), fractions=(0.5,))
    assert out is not None
    surfaces, _ = out
    assert len(surfaces) == 1
    # The inverted cell must be NaN in the resulting surface.
    assert np.isnan(surfaces[0][0, 1])
    assert np.isfinite(surfaces[0][0, 0])


def test_build_stratal_surfaces_returns_none_when_all_invalid():
    from paleo_workbench.viz.stratal_adapter import build_stratal_surfaces

    top = np.full((2, 2), 15.0)
    bot = np.full((2, 2), 5.0)  # fully inverted
    out = build_stratal_surfaces(top, bot, (2, 2, 20))
    assert out is None


def test_stratal_adapter_end_to_end_with_demo_and_renderer(qtbot):
    """The full demo path: synthetic volume + horizons -> Renderer3D planes."""
    from geoviz_seismic.renderer_3d import Renderer3D
    from paleo_workbench.viz.stratal_adapter import (
        build_stratal_surfaces,
        make_demo_stratal_grids,
    )

    widget = Renderer3D()
    qtbot.addWidget(widget)
    vol, top, bot = make_demo_stratal_grids((10, 12, 20))
    widget.load_volume(vol)
    assert widget._loaded

    out = build_stratal_surfaces(top, bot, vol.shape, fractions=(0.5,))
    assert out is not None
    surfaces, _ = out
    widget.set_stratal_slices(surfaces, labels=["half"], active=0)
    snap = widget.get_stratal_slices()
    assert len(snap) == 1
    # Mean depth should be near the middle (between top and bot midpoints).
    assert 6.0 < snap[0][2] < 14.0
    # Plane item registered.
    assert len(widget._stratal_plane_items) == 1
