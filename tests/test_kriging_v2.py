"""V6 §11 — kriging V2: anisotropy, explicit nugget, fit diagnostics.

Scientific contract under test:
- geometric anisotropy (azimuth + major/minor ratio) changes the kriging
  surface in the direction the geology demands;
- an explicit nugget is honored exactly (no silent refit);
- the engine reports WHICH variogram parameters produced the surface and
  whether they were fitted or defaulted (no silent auto-fit).
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("scipy")

from geoviz_plots.factor.kriging import (
    apply_anisotropy_transform,
    fit_variogram,
    ordinary_kriging,
)


def _anisotropic_field(n: int = 400, seed: int = 7, side: float = 1000.0):
    """Stationary GRF with gaussian covariance: long range X, short range Y.

    Spectral synthesis (FFT): correlation length 200 m along X, 40 m along Y
    (ratio 5). Both lengths must exceed the sampling spacing or the empirical
    variogram cannot resolve them; a stationary field is what the fit needs.
    """
    rng = np.random.default_rng(seed)
    n_side = max(int(np.ceil(np.sqrt(n))) + 8, 64)
    # grid axis 0 = Y (rows), axis 1 = X (cols) — pair the frequencies with
    # the matching correlation lengths or the anisotropy comes out rotated.
    f_y = np.fft.fftfreq(n_side)[:, None]
    f_x = np.fft.fftfreq(n_side)[None, :]
    sx, sy = 200.0 / side * n_side, 40.0 / side * n_side
    spectrum = np.exp(-2.0 * np.pi**2 * (f_x**2 * sx**2 + f_y**2 * sy**2))
    noise = rng.standard_normal((n_side, n_side))
    field = np.real(np.fft.ifft2(np.fft.fft2(noise) * np.sqrt(spectrum)))
    field = (field - field.mean()) / (field.std() + 1e-12)
    coords = np.stack(
        np.meshgrid(np.linspace(0.0, side, n_side), np.linspace(0.0, side, n_side)),
        axis=-1,
    ).reshape(-1, 2)
    values = field.reshape(-1)
    pick = rng.choice(len(coords), size=min(n, len(coords)), replace=False)
    return coords[pick, 0], coords[pick, 1], values[pick]


class TestAnisotropyTransform:
    """Azimuth convention: geological, clockwise from north (+Y) — the same
    convention the directional backend uses."""

    def test_identity_when_ratio_one(self):
        x = np.array([100.0, 300.0])
        y = np.array([50.0, 250.0])
        tx, ty = apply_anisotropy_transform(x, y, azimuth_deg=90.0, ratio=1.0)
        np.testing.assert_allclose(tx, x)
        np.testing.assert_allclose(ty, y)

    def test_minor_axis_expanded(self):
        # azimuth 0 = major along +Y (north): the X coordinate is MINOR and
        # is expanded by the ratio (isotropic-frame convention, V6 §11)
        tx, ty = apply_anisotropy_transform(
            np.array([100.0]), np.array([0.0]), azimuth_deg=0.0, ratio=4.0
        )
        assert abs(ty[0]) == pytest.approx(400.0)
        assert abs(tx[0]) == pytest.approx(0.0, abs=1e-9)

    def test_azimuth_90_major_along_x(self):
        # azimuth 90 = major along +X: the Y coordinate is minor and expands
        tx, ty = apply_anisotropy_transform(
            np.array([0.0]), np.array([80.0]), azimuth_deg=90.0, ratio=4.0
        )
        assert abs(ty[0]) == pytest.approx(320.0)
        assert abs(tx[0]) == pytest.approx(0.0, abs=1e-9)

    def test_invalid_ratio_rejected(self):
        with pytest.raises(ValueError):
            apply_anisotropy_transform(
                np.array([0.0]), np.array([0.0]), azimuth_deg=0.0, ratio=0.5
            )


class TestAnisotropicKriging:
    def test_anisotropy_changes_the_surface_along_minor_axis(self):
        x, y, z = _anisotropic_field()
        gx, gy = np.meshgrid(np.linspace(0, 1000, 40), np.linspace(0, 1000, 40))
        tx, ty = gx.ravel(), gy.ravel()

        pred_iso, var_iso = ordinary_kriging(x, y, z, tx, ty)
        pred_aniso, var_aniso = ordinary_kriging(
            x, y, z, tx, ty,
            azimuth_deg=90.0,
            anisotropy_ratio=5.0,
        )
        assert not np.allclose(pred_iso, pred_aniso), (
            "anisotropy must change the surface"
        )

    def test_anisotropic_field_interpolated_better_than_isotropic(self):
        x, y, z = _anisotropic_field(seed=11)
        rng = np.random.default_rng(3)
        hold = rng.choice(len(x), size=40, replace=False)
        mask = np.ones(len(x), dtype=bool)
        mask[hold] = False
        xs, ys, zs = x[mask], y[mask], z[mask]
        xt, yt, zt = x[hold], y[hold], z[hold]

        pred_iso, _ = ordinary_kriging(xs, ys, zs, xt, yt)
        pred_aniso, _ = ordinary_kriging(
            xs, ys, zs, xt, yt, azimuth_deg=90.0, anisotropy_ratio=5.0
        )
        rmse_iso = float(np.sqrt(np.mean((pred_iso - zt) ** 2)))
        rmse_aniso = float(np.sqrt(np.mean((pred_aniso - zt) ** 2)))
        assert rmse_aniso < rmse_iso, (
            f"anisotropic kriging should beat isotropic on an anisotropic "
            f"field ({rmse_aniso:.4f} vs {rmse_iso:.4f})"
        )

    def test_fit_variogram_uses_transformed_space(self):
        x, y, z = _anisotropic_field(seed=5)
        iso = fit_variogram(x, y, z)
        aniso = fit_variogram(x, y, z, azimuth_deg=90.0, anisotropy_ratio=5.0)
        assert iso["range"] != pytest.approx(aniso["range"], rel=0.01)


class TestExplicitParameters:
    def test_explicit_nugget_is_honored_exactly(self):
        x, y, z = _anisotropic_field(seed=2)
        tx = np.array([300.0, 700.0])
        ty = np.array([400.0, 600.0])
        diagnostics: dict = {}
        pred, var = ordinary_kriging(
            x, y, z, tx, ty,
            range_=250.0, sill=0.01, nugget=0.005,
            diagnostics=diagnostics,
        )
        assert np.all(np.isfinite(pred))
        # The explicit nugget is honored verbatim (no refit); note standard
        # OK remains an exact interpolator at sample locations even with a
        # nugget (the γ-form system has γ(0)=0).
        assert diagnostics["variogram"]["nugget"] == pytest.approx(0.005)
        assert diagnostics["variogram_fit"] == "explicit"

    def test_diagnostics_report_fitted_vs_explicit(self):
        x, y, z = _anisotropic_field(seed=9)
        tx = np.array([500.0])
        ty = np.array([500.0])
        diagnostics: dict = {}
        ordinary_kriging(x, y, z, tx, ty, diagnostics=diagnostics)
        assert diagnostics["variogram"]["range"] > 0.0
        assert diagnostics["variogram_fit"] in ("fitted", "defaulted")
        ordinary_kriging(
            x, y, z, tx, ty,
            range_=300.0, sill=0.02, nugget=0.0,
            diagnostics=diagnostics,
        )
        assert diagnostics["variogram_fit"] == "explicit"
        assert diagnostics["variogram"]["range"] == pytest.approx(300.0)

    def test_anisotropy_reported_in_diagnostics(self):
        x, y, z = _anisotropic_field(seed=4)
        diagnostics: dict = {}
        ordinary_kriging(
            x, y, z, np.array([100.0]), np.array([100.0]),
            azimuth_deg=30.0, anisotropy_ratio=2.5,
            diagnostics=diagnostics,
        )
        assert diagnostics["anisotropy"] == {"azimuth_deg": 30.0, "ratio": 2.5}


class TestReviewRegressions:
    def test_fit_is_single_transformed_not_double(self):
        """R1-P0/R3-P0: ordinary_kriging's auto-fit must NOT re-transform the
        already-transformed coordinates (ratio² frame distorted range/sill)."""
        from geoviz_plots.factor.kriging import apply_anisotropy_transform, fit_variogram

        x, y, z = _anisotropic_field(seed=13, n=400)
        az, ratio = 90.0, 5.0
        u, v = apply_anisotropy_transform(x, y, azimuth_deg=az, ratio=ratio)
        direct = fit_variogram(u, v, z)  # correct single-transform reference
        d: dict = {}
        ordinary_kriging(
            x, y, z, np.array([500.0]), np.array([500.0]),
            azimuth_deg=az, anisotropy_ratio=ratio, diagnostics=d,
        )
        fitted = d["variogram"]
        assert fitted["range"] == pytest.approx(direct["range"], rel=1e-9)
        assert fitted["sill"] == pytest.approx(direct["sill"], rel=1e-9)
        assert fitted["nugget"] == pytest.approx(direct["nugget"], rel=1e-9)

    def test_azimuth_0_with_explicit_axes_is_requested(self):
        """R3-P1: azimuth 0° (due north) must not disable anisotropy when
        the axes are explicitly configured."""
        diagnostics: dict = {}
        ordinary_kriging(
            np.array([0.0, 100.0, 200.0, 300.0]),
            np.array([0.0, 10.0, 0.0, 10.0]),
            np.array([1.0, 2.0, 3.0, 4.0]),
            np.array([150.0]), np.array([5.0]),
            azimuth_deg=0.0, anisotropy_ratio=4.0, diagnostics=diagnostics,
        )
        assert diagnostics["anisotropy"] == {"azimuth_deg": 0.0, "ratio": 4.0}
