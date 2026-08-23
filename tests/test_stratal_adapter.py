"""Tests for the workbench stratal adapter (workflow glue over geoviz facade).

Most tests use the synthetic demo volume/horizons so they run without a real
SEGY or OpenGL context. The single Renderer3D test is marked ``opengl`` and
is skipped on the offscreen CI platform (no software-GL leg today — #940-1);
engine math it delegates to is covered in the engine repo.
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
    # Legitimate preview per VolumeRegistration: 50 native samples at
    # stride 3 give ceil(50/3) == 17 preview samples.
    stride = 3
    reg = SimpleNamespace(n_sample=17, strides=(1, 1, stride))
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
                sample_stride=reg.strides[2],
            )[0]
        )

    dt = survey.dt_ms
    # t0 boundary -> preview sample 0.
    assert transform(survey.t0_ms) == pytest.approx(0.0)
    # Native sample p*stride maps exactly to preview sample p (#890: the
    # endpoint-ratio form drifted up to stride-1 samples on odd sizes).
    for p in (0, 1, 5, 16):
        assert transform(survey.t0_ms + p * stride * dt) == pytest.approx(float(p))
    # Monotonic non-decreasing in twt.
    twts = np.linspace(survey.t0_ms, survey.t0_ms + 49 * dt, 9)
    out = np.asarray([transform(t) for t in twts])
    assert (np.diff(out) >= 0).all()
    # Spot check a non-lattice value: native sample 25 -> 25/3.
    assert transform(survey.t0_ms + 25 * dt) == pytest.approx(25.0 / stride)
    # Degenerate dt (<=0) degrades to dt=1.0, never divides by zero.
    degenerate = ms_to_preview_sample_index(
        np.asarray([survey.t0_ms + 30.0]),
        dt_ms=0.0,
        t0_ms=survey.t0_ms,
        sample_stride=stride,
    )[0]
    assert degenerate == pytest.approx(30.0 / stride)


@pytest.mark.opengl  # #940-1: requires real GL; skipped on offscreen CI (no coverage leg today)
def test_stratal_adapter_end_to_end_with_demo_and_renderer(qtbot):
    """The full demo path: synthetic volume + horizons -> Renderer3D planes.

    #940-1: this is the only stratal test that needs a real OpenGL context.
    # Pure-math stratal tests above run everywhere; this one is permanently
    # skipped on offscreen CI and has no dedicated software-GL leg today.
    """
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
