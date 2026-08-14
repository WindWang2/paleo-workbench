"""Tests for the workbench stratal adapter (workflow glue over geoviz facade).

These use the synthetic demo volume/horizons so they run without a real SEGY or
OpenGL context. The engine math they delegate to is covered in the engine repo.
"""

from __future__ import annotations

import numpy as np
import pytest


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


def test_stratal_ms_to_sample_index_endpoints_and_monotonicity():
    """The vectorized ms->sample transform must honor its contract endpoints.

    Previously this test recomputed both expected and actual with the SAME
    test-local arithmetic, so it could never catch a regression in the
    production formula. Pin the real invariants instead: the t0 boundary maps
    to sample 0, the last full sample maps to the last preview sample, and the
    transform is monotonic in twt (these are the properties the stratal
    surface build relies on).
    """
    from types import SimpleNamespace

    survey = SimpleNamespace(
        iline_start=100, iline_step=2, n_inlines=8,
        xline_start=200, xline_step=2, n_crosslines=6,
        n_samples=50, dt_ms=4.0, t0_ms=100.0,
    )
    reg = SimpleNamespace(n_sample=20)  # preview downsampled to 20 samples
    # Call the PRODUCTION transform (K-F6: the previous test recomputed
    # expectations with a test-local copy of the formula and could never
    # catch a regression in the shipped arithmetic).
    from paleo_workbench.viz.stratal_adapter import ms_to_preview_sample_index

    def transform(twt):
        return float(
            ms_to_preview_sample_index(
                np.asarray([twt]),
                dt_ms=survey.dt_ms,
                t0_ms=survey.t0_ms,
                n_samples=survey.n_samples,
                n_sample_preview=reg.n_sample,
            )[0]
        )

    scale = reg.n_sample - 1
    dt = survey.dt_ms
    # t0 boundary -> preview sample 0.
    assert transform(survey.t0_ms) == pytest.approx(0.0)
    # Last full sample (t0 + (n_samples-1)*dt) -> last preview sample.
    last_twt = survey.t0_ms + (survey.n_samples - 1) * dt
    assert transform(last_twt) == pytest.approx(scale)
    # Monotonic non-decreasing in twt.
    twts = np.linspace(survey.t0_ms, last_twt, 9)
    out = np.asarray([transform(t) for t in twts])
    assert (np.diff(out) >= 0).all()
    # Spot check a mid value against an independent hand computation.
    assert transform(survey.t0_ms + 25 * dt) == pytest.approx(25 / 49.0 * 19.0)
    # Degenerate dt (<=0) degrades to dt=1.0, never divides by zero.
    degenerate = ms_to_preview_sample_index(
        np.asarray([survey.t0_ms + 10.0]),
        dt_ms=0.0,
        t0_ms=survey.t0_ms,
        n_samples=survey.n_samples,
        n_sample_preview=reg.n_sample,
    )[0]
    assert degenerate == pytest.approx(10.0 / 49.0 * 19.0)


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
