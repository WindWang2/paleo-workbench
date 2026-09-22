"""#1038 — fault throw must anchor BOTH axes in projected Map CRS.

``dist_normal = nx * (x - fault_line_x) + ny * y`` omitted the Y anchor, so
any fault with a non-zero strike in UTM/Gauss-Krüger coordinates (Y ≈ 3e6)
placed the fault plane hundreds of kilometers from the survey. These tests
pin the anchored signed-normal distance and UTM-scale correctness.
"""

from __future__ import annotations

import numpy as np
import pytest

from paleo_workbench.env_bootstrap import ensure_geoviz_on_path

ensure_geoviz_on_path()

from paleo_workbench.viz.fault_displacement import FaultDisplacement, FaultSpec


def _flat_grid(x_range, y_range, z=100.0):
    x, y = np.meshgrid(x_range, y_range)
    z = np.full_like(x, z, dtype=np.float64)
    return np.column_stack([x.ravel(), y.ravel(), z.ravel()])


def test_utm_coordinates_fault_stays_on_survey():
    """A vertical-strike fault at UTM (500000, 3200000) must displace only the
    hanging wall on the survey, not the entire mesh."""
    engine = FaultDisplacement()
    verts = _flat_grid(np.linspace(499900.0, 500100.0, 21), np.linspace(3199900.0, 3200100.0, 21))
    displaced = engine.apply_fault_throw(
        vertices=verts,
        fault_line_x=500000.0,
        fault_line_y=3200000.0,
        throw_z=-15.0,
    )
    # Pre-fault classification: hanging wall = x >= fault_line_x
    hanging = verts[:, 0] >= 500000.0
    footwall = ~hanging
    assert np.allclose(displaced[footwall, 2], 100.0)
    assert np.allclose(displaced[hanging, 2], 85.0)


def test_offset_fault_line_with_zero_strike_matches_anchor():
    """With strike=0 the fault line is x = fault_line_x regardless of Y — the
    unanchored bug broke this as soon as ny != 0 was impossible... but any
    nonzero strike needs the Y anchor (next test)."""
    engine = FaultDisplacement()
    verts = _flat_grid(np.linspace(-10.0, 10.0, 5), np.linspace(-10.0, 10.0, 5))
    displaced = engine.apply_fault_throw(
        vertices=verts,
        fault_line_x=2.0,
        fault_line_y=-3.0,
        throw_z=-10.0,
    )
    hanging = verts[:, 0] >= 2.0
    assert np.allclose(displaced[~hanging, 2], 100.0)
    assert np.allclose(displaced[hanging, 2], 90.0)


def test_diagonal_strike_anchored_distance_is_translation_invariant():
    """dist_normal must depend on the offset from the ANCHORED line, not on
    the absolute distance from the coordinate origin."""
    engine = FaultDisplacement()
    strike = 30.0
    local = _flat_grid(np.linspace(-10.0, 10.0, 9), np.linspace(-10.0, 10.0, 9))

    utm_offset = np.array([500000.0, 3200000.0, 0.0])
    shifted = local + utm_offset

    out_local = engine.apply_fault_throw(
        local, fault_line_x=0.0, fault_line_y=0.0, throw_z=-10.0, strike_deg=strike
    )
    out_shifted = engine.apply_fault_throw(
        shifted,
        fault_line_x=500000.0,
        fault_line_y=3200000.0,
        throw_z=-10.0,
        strike_deg=strike,
    )
    # Same relative geometry → same relative displacement
    assert np.allclose(out_shifted - shifted, out_local - local, atol=1e-6)


def test_diagonal_strike_signed_normal_matches_geometry():
    """For strike=45°, a point anchored +n along the normal must be hanging
    wall; -n must be footwall — in UTM coordinates."""
    engine = FaultDisplacement()
    anchor = np.array([500000.0, 3200000.0])
    normal = np.array([np.cos(np.radians(45.0)), np.sin(np.radians(45.0))])
    plus = np.array([[*(anchor + 5.0 * normal), 100.0]])
    minus = np.array([[*(anchor - 5.0 * normal), 100.0]])
    displaced = engine.apply_fault_throw(
        np.vstack([plus, minus]),
        fault_line_x=anchor[0],
        fault_line_y=anchor[1],
        throw_z=-20.0,
        strike_deg=45.0,
    )
    assert displaced[0, 2] == pytest.approx(80.0)
    assert displaced[1, 2] == pytest.approx(100.0)


def test_decay_radius_uses_anchored_distance():
    """Gaussian decay must measure distance from the anchored fault line."""
    engine = FaultDisplacement()
    anchor = np.array([500000.0, 3200000.0])
    near = np.array([[*(anchor + np.array([3.0, 4.0])), 100.0]])  # 5 m away
    far = np.array([[*(anchor + np.array([300.0, 400.0])), 100.0]])  # 500 m away
    displaced = engine.apply_fault_throw(
        np.vstack([near, far]),
        fault_line_x=anchor[0],
        fault_line_y=anchor[1],
        throw_z=-20.0,
        strike_deg=0.0,
        decay_radius=100.0,
    )
    # near vertex sits mostly on the hanging wall side of a vertical fault
    # (x = anchor+3): full-ish throw; far vertex gets the same side but the
    # weight depends only on |dist_normal| = 3 vs 300.
    assert displaced[0, 2] < displaced[1, 2]  # near displaced more
    assert displaced[0, 2] < 100.0


def test_fault_spec_carries_y_anchor():
    spec = FaultSpec(
        fault_line_x=500000.0,
        fault_line_y=3200000.0,
        throw_z=-10.0,
    )
    assert spec.fault_line_y == 3200000.0
    engine = FaultDisplacement()
    verts = _flat_grid(np.linspace(499990.0, 500010.0, 5), np.linspace(3199990.0, 3200010.0, 5))
    displaced = engine.apply_fault_throw(verts, spec=spec)
    hanging = verts[:, 0] >= 500000.0
    assert np.allclose(displaced[hanging, 2], 90.0)
    assert np.allclose(displaced[~hanging, 2], 100.0)


def test_spec_defaults_keep_local_origin_compatible():
    """Existing local-coordinate callers (fault at origin) keep working."""
    spec = FaultSpec(fault_line_x=5.0, throw_z=-15.0)
    assert spec.fault_line_y == 0.0
    engine = FaultDisplacement()
    verts = _flat_grid(np.arange(10, dtype=np.float64), np.arange(10, dtype=np.float64))
    displaced = engine.apply_fault_throw(verts, spec=spec)
    hanging = verts[:, 0] >= 5.0
    assert np.allclose(displaced[hanging, 2], 85.0)
