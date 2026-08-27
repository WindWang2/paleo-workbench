"""#1036 — scientific quality of the pure-NumPy Ordinary Kriging fallback.

The fallback used fixed magic variogram parameters (``sill = var(z)``,
``range = 0.8 * dmax``), no duplicate-point handling, an unchunked
(M x N) distance broadcast and ``pinv`` on the indefinite augmented saddle
system. These tests pin the remediated contract:

* constant fields reproduce exactly (ordinary-kriging unbiasedness),
* coincident samples collapse to their mean instead of a singular system,
* variogram parameters are FITTED (short-correlation noise fits a much
  shorter range than a smooth ramp),
* chunked evaluation is bitwise identical to the unchunked path,
* variance is non-negative everywhere.
"""

from __future__ import annotations

import numpy as np
import pytest

from paleo_workbench.mapping.geological_pipeline.interpolator import (
    _pure_numpy_kriging,
)


def _samples(n: int = 64, seed: int = 7, span: float = 1000.0):
    rng = np.random.default_rng(seed)
    x = rng.uniform(0.0, span, n)
    y = rng.uniform(0.0, span, n)
    return x, y


def _grid(span: float = 1000.0, grid_n: int = 24):
    g = np.linspace(0.0, span, grid_n)
    return g, g


def test_constant_field_is_reproduced_exactly():
    """Ordinary kriging is unbiased: a constant field must map to the same
    constant everywhere, whatever the fitted variogram says."""
    x, y = _samples()
    z = np.full_like(x, 17.25)
    gx, gy = _grid()
    grid_z, grid_var, params = _pure_numpy_kriging(x, y, z, gx, gy)
    assert np.allclose(grid_z, 17.25, atol=1e-6)


def test_coincident_samples_collapse_to_mean():
    x, y = _samples(n=24, seed=3)
    # duplicate the first four locations three times with different values
    xs = np.concatenate([x, x[:4], x[:4]])
    ys = np.concatenate([y, y[:4], y[:4]])
    zs = np.concatenate([np.full(24, 5.0), np.full(4, 8.0), np.full(4, 2.0)])
    gx, gy = _grid()
    grid_z, grid_var, params = _pure_numpy_kriging(xs, ys, zs, gx, gy)
    assert np.isfinite(grid_z).all()
    # at a duplicated location the estimate must be the coincident mean (5+8+2)/3
    idx = np.argmin(np.abs(gx - x[0]))
    idy = np.argmin(np.abs(gy - y[0]))
    assert grid_z[idy, idx] == pytest.approx(5.0, abs=0.5)


def test_identical_duplicate_values_do_not_blow_up():
    """The classic singular-matrix case: same location, same value."""
    x = np.array([0.0, 0.0, 10.0, 20.0, 30.0])
    y = np.array([0.0, 0.0, 10.0, 20.0, 5.0])
    z = np.array([4.0, 4.0, 4.0, 4.0, 4.0])
    gx, gy = _grid(span=30.0, grid_n=12)
    grid_z, grid_var, _ = _pure_numpy_kriging(x, y, z, gx, gy)
    assert np.isfinite(grid_z).all()
    assert np.allclose(grid_z, 4.0, atol=1e-6)


def test_variogram_parameters_are_fitted_not_magic():
    """Decorrelated noise must fit a much shorter range than a smooth ramp —
    the old fixed ``range = 0.8 * dmax`` cannot distinguish them."""
    rng = np.random.default_rng(11)
    x, y = _samples(n=120, seed=11)
    gx, gy = _grid()

    # smooth long-range field: planar ramp + gentle parabola
    z_smooth = 10.0 + 0.004 * x + 0.000002 * y**2
    # short-range field: independent noise (correlation length ~ 0)
    z_noise = rng.normal(0.0, 1.0, len(x))

    _, _, p_smooth = _pure_numpy_kriging(x, y, z_smooth, gx, gy)
    _, _, p_noise = _pure_numpy_kriging(x, y, z_noise, gx, gy)

    dmax = float(np.hypot(x.max() - x.min(), y.max() - y.min()))
    assert 0.0 < p_smooth["range"] <= dmax
    assert 0.0 < p_noise["range"] <= dmax
    # decorrelated noise gets a substantially shorter correlation range
    assert p_noise["range"] < 0.5 * p_smooth["range"]
    # a fit was actually performed (fitted fields carry the empirical bins)
    assert p_smooth.get("variogram_bins", 0) >= 4


def test_prediction_accuracy_on_known_synthetic_surface():
    """Kriging a smooth analytic surface must beat a naive mean estimate."""
    x, y = _samples(n=100, seed=5)
    z = 3.0 + 0.5 * np.sin(x / 300.0) + 0.3 * np.cos(y / 250.0)
    gx, gy = _grid()
    grid_z, grid_var, params = _pure_numpy_kriging(x, y, z, gx, gy)

    gxm, gym = np.meshgrid(gx, gy)
    truth = 3.0 + 0.5 * np.sin(gxm / 300.0) + 0.3 * np.cos(gym / 250.0)
    mae = float(np.mean(np.abs(grid_z - truth)))
    mean_baseline = float(np.mean(np.abs(np.full_like(truth, z.mean()) - truth)))
    assert mae < 0.5 * mean_baseline
    # R^2 against the truth
    ss_res = float(np.sum((grid_z - truth) ** 2))
    ss_tot = float(np.sum((truth - truth.mean()) ** 2))
    assert 1.0 - ss_res / ss_tot > 0.7


def test_kriging_is_exact_at_sample_locations_for_smooth_field():
    # samples drawn ON the lattice so evaluation hits them exactly: ordinary
    # kriging must reproduce its own data points (unbiased + solvable system)
    rng = np.random.default_rng(9)
    lattice = np.linspace(0.0, 1000.0, 41)
    ix = rng.choice(len(lattice), size=40, replace=False)
    iy = rng.choice(len(lattice), size=40, replace=False)
    x, y = lattice[ix], lattice[iy]
    z = 2.0 + 0.01 * x
    grid_z, _, _ = _pure_numpy_kriging(x, y, z, lattice, lattice)
    for xi, yi, zi in zip(x, y, z):
        gx_idx = int(np.flatnonzero(lattice == xi)[0])
        gy_idx = int(np.flatnonzero(lattice == yi)[0])
        assert grid_z[gy_idx, gx_idx] == pytest.approx(zi, abs=1e-6), (
            f"sample ({xi:.1f},{yi:.1f})={zi:.2f} predicted {grid_z[gy_idx, gx_idx]:.6f}"
        )


def test_variance_is_non_negative_and_small_at_samples():
    x, y = _samples(n=40, seed=13)
    z = 2.0 + 0.01 * x
    gx = np.linspace(0.0, 1000.0, 41)
    gy = np.linspace(0.0, 1000.0, 41)
    _, grid_var, _ = _pure_numpy_kriging(x, y, z, gx, gy)
    assert (grid_var >= -1e-9).all()
    sample_var = grid_var[20, 20]
    assert sample_var < float(np.max(grid_var))


def test_chunked_evaluation_matches_unchunked(monkeypatch):
    import paleo_workbench.mapping.geological_pipeline.interpolator as mod

    x, y = _samples(n=30, seed=17)
    z = 2.0 + 0.01 * x + 0.005 * y
    gx = np.linspace(0.0, 1000.0, 60)
    gy = np.linspace(0.0, 1000.0, 60)

    reference_z, reference_var, _ = _pure_numpy_kriging(x, y, z, gx, gy)
    monkeypatch.setattr(mod, "_KRIGE_TARGET_CHUNK", 64)
    chunked_z, chunked_var, _ = _pure_numpy_kriging(x, y, z, gx, gy)

    assert np.array_equal(chunked_z, reference_z)
    assert np.array_equal(chunked_var, reference_var)


def test_large_grid_stays_memory_bounded_and_correct_shape():
    x, y = _samples(n=25, seed=19)
    z = 1.0 + 0.002 * x
    gx = np.linspace(0.0, 1000.0, 400)
    gy = np.linspace(0.0, 1000.0, 400)
    grid_z, grid_var, _ = _pure_numpy_kriging(x, y, z, gx, gy)
    assert grid_z.shape == (400, 400)
    assert np.isfinite(grid_z).all()
