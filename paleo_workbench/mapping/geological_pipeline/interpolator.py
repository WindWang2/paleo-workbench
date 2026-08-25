"""Spatial interpolation engine supporting Ordinary Kriging and Inverse Distance Weighting (IDW)."""

from __future__ import annotations

from abc import ABC, abstractmethod
import math
from typing import Any

import numpy as np

from paleo_workbench.mapping.geological_pipeline.models import (
    GeologicalFactorDataset,
    InterpolationOptions,
)
from paleo_workbench.workflow.factor_grid_result import FactorGridResult, NODATA


class Interpolator(ABC):
    """Protocol / ABC for spatial interpolation engines."""

    @abstractmethod
    def interpolate(
        self, dataset: GeologicalFactorDataset, options: InterpolationOptions
    ) -> FactorGridResult:
        pass


class KrigingInterpolator(Interpolator):
    """Ordinary Kriging with empirical variogram fitting and kriging variance grid."""

    def interpolate(
        self, dataset: GeologicalFactorDataset, options: InterpolationOptions
    ) -> FactorGridResult:
        issues = dataset.validate()
        if issues:
            raise ValueError("; ".join(issues))

        xs, ys, zs = dataset.to_arrays()
        xmin, ymin, xmax, ymax = dataset.extent
        grid_n = max(10, int(options.grid_n))
        grid_x = np.linspace(xmin, xmax, grid_n, dtype=np.float64)
        grid_y = np.linspace(ymin, ymax, grid_n, dtype=np.float64)

        try:
            from geoviz_plots.factor.kriging import (
                fit_variogram,
                kriging_grid,
                leave_one_out_predictions,
            )

            model_name = options.variogram_model if options.variogram_model in ("spherical", "exponential", "gaussian") else "spherical"
            fit_params = fit_variogram(xs, ys, zs, model=model_name)

            # Run 2D Kriging grid
            grid_z, grid_var = kriging_grid(
                xs, ys, zs, grid_x, grid_y,
                variogram_model=model_name,
                range_=fit_params["range"],
                sill=fit_params["sill"],
                nugget=fit_params["nugget"],
            )

            # Cross validation LOO
            loo_preds, z_dedup = leave_one_out_predictions(
                xs, ys, zs,
                variogram_model=model_name,
                range_=fit_params["range"],
                sill=fit_params["sill"],
                nugget=fit_params["nugget"],
            )
            # Compute R²
            tot_ss = float(np.sum((z_dedup - np.mean(z_dedup)) ** 2))
            res_ss = float(np.sum((z_dedup - loo_preds) ** 2))
            r2 = max(0.0, 1.0 - (res_ss / tot_ss)) if tot_ss > 1e-12 else 1.0

            algo_params = {
                "method": "kriging",
                "model": model_name,
                "range": fit_params["range"],
                "sill": fit_params["sill"],
                "nugget": fit_params["nugget"],
                "r_squared": float(r2),
                "grid_n": grid_n,
                "n_samples": len(xs),
            }

        except ImportError:
            # Fallback pure-numpy Ordinary Kriging
            grid_z, grid_var, algo_params = _pure_numpy_kriging(
                xs, ys, zs, grid_x, grid_y, model=options.variogram_model
            )

        return FactorGridResult(
            grid_z=np.asarray(grid_z, dtype=np.float32),
            grid_x=grid_x,
            grid_y=grid_y,
            factor_name=dataset.factor_name,
            algorithm_id="kriging",
            algorithm_parameters=algo_params,
            crs=dataset.crs or options.crs,
            unit=dataset.unit,
            variance_grid=np.asarray(grid_var, dtype=np.float32) if grid_var is not None else None,
        )


class IDWInterpolator(Interpolator):
    """Inverse Distance Weighting (IDW) interpolation."""

    def interpolate(
        self, dataset: GeologicalFactorDataset, options: InterpolationOptions
    ) -> FactorGridResult:
        issues = dataset.validate()
        if issues:
            raise ValueError("; ".join(issues))

        xs, ys, zs = dataset.to_arrays()
        xmin, ymin, xmax, ymax = dataset.extent
        grid_n = max(10, int(options.grid_n))
        grid_x = np.linspace(xmin, xmax, grid_n, dtype=np.float64)
        grid_y = np.linspace(ymin, ymax, grid_n, dtype=np.float64)

        gx, gy = np.meshgrid(grid_x, grid_y)  # (H, W)
        target_pts = np.stack([gx.ravel(), gy.ravel()], axis=1)  # (H*W, 2)
        sample_pts = np.stack([xs, ys], axis=1)  # (N, 2)

        # Distances: (H*W, N)
        dx = target_pts[:, 0:1] - sample_pts[:, 0].T
        dy = target_pts[:, 1:2] - sample_pts[:, 1].T
        dist = np.sqrt(dx * dx + dy * dy)

        p = max(1.0, float(options.power))
        eps = 1e-12

        # Check for exact matches
        exact_match = dist < eps
        weights = 1.0 / np.maximum(dist, eps) ** p
        weights[exact_match] = 0.0

        weight_sum = np.sum(weights, axis=1)
        z_grid_flat = np.sum(weights * zs, axis=1) / np.maximum(weight_sum, 1e-15)

        # Apply exact matches
        match_rows, match_cols = np.nonzero(exact_match)
        if match_rows.size > 0:
            z_grid_flat[match_rows] = zs[match_cols]

        grid_z = z_grid_flat.reshape((grid_n, grid_n))

        algo_params = {
            "method": "idw",
            "power": p,
            "grid_n": grid_n,
            "n_samples": len(xs),
        }

        return FactorGridResult(
            grid_z=np.asarray(grid_z, dtype=np.float32),
            grid_x=grid_x,
            grid_y=grid_y,
            factor_name=dataset.factor_name,
            algorithm_id="idw",
            algorithm_parameters=algo_params,
            crs=dataset.crs or options.crs,
            unit=dataset.unit,
        )


def _pure_numpy_kriging(
    x: np.ndarray, y: np.ndarray, z: np.ndarray,
    grid_x: np.ndarray, grid_y: np.ndarray,
    model: str = "spherical",
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Self-contained numpy Ordinary Kriging fallback."""
    n = len(z)
    sample_pts = np.stack([x, y], axis=1)
    dists = np.sqrt(np.sum((sample_pts[:, None, :] - sample_pts[None, :, :]) ** 2, axis=2))

    # Variance and range heuristics
    sill = float(np.var(z)) if float(np.var(z)) > 1e-6 else 1.0
    dmax = float(np.max(dists)) if float(np.max(dists)) > 1e-6 else 1.0
    r = dmax * 0.8
    nugget = 0.0

    # Covariance function
    def cov(h: np.ndarray) -> np.ndarray:
        hr = np.clip(h / max(r, 1e-6), 0.0, 1.0)
        gamma = sill * (1.5 * hr - 0.5 * hr ** 3)
        return (sill + nugget) - gamma

    # Augmented kriging matrix K
    K = np.zeros((n + 1, n + 1), dtype=np.float64)
    K[:n, :n] = cov(dists) + np.eye(n) * 1e-8
    K[:n, n] = 1.0
    K[n, :n] = 1.0
    K[n, n] = 0.0

    inv_K = np.linalg.pinv(K)

    # Grid targets
    gx, gy = np.meshgrid(grid_x, grid_y)
    targets = np.stack([gx.ravel(), gy.ravel()], axis=1)  # (M, 2)
    m = len(targets)

    # Target distances: (M, N)
    tdists = np.sqrt(np.sum((targets[:, None, :] - sample_pts[None, :, :]) ** 2, axis=2))
    k = np.zeros((m, n + 1), dtype=np.float64)
    k[:, :n] = cov(tdists)
    k[:, n] = 1.0

    # Weights: (M, N+1) = k @ inv_K
    w = k @ inv_K
    z_pred = np.sum(w[:, :n] * z, axis=1)
    variance = (sill + nugget) - np.sum(w * k, axis=1)
    variance = np.maximum(0.0, variance)

    return (
        z_pred.reshape((len(grid_y), len(grid_x))),
        variance.reshape((len(grid_y), len(grid_x))),
        {"method": "kriging_fallback", "model": model, "range": r, "sill": sill},
    )


def interpolate_factor(
    dataset: GeologicalFactorDataset, options: InterpolationOptions | None = None
) -> FactorGridResult:
    """Convenience top-level interpolation dispatcher."""
    if options is None:
        options = InterpolationOptions()
    if options.method.lower() in ("kriging", "ordinary_kriging", "ok"):
        engine = KrigingInterpolator()
    else:
        engine = IDWInterpolator()
    return engine.interpolate(dataset, options)
