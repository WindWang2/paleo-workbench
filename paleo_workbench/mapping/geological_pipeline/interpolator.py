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
            from geoviz import (
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
                "sample_points": [
                    {"well": p.well_name or p.well_id, "x": p.x, "y": p.y, "value": p.value}
                    for p in dataset.valid_points
                ],
            }

        except ImportError:
            # Fallback pure-numpy Ordinary Kriging
            grid_z, grid_var, algo_params = _pure_numpy_kriging(
                xs, ys, zs, grid_x, grid_y, model=options.variogram_model
            )
            algo_params["sample_points"] = [
                {"well": p.well_name or p.well_id, "x": p.x, "y": p.y, "value": p.value}
                for p in dataset.valid_points
            ]

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
        target_pts = np.stack([gx.ravel(), gy.ravel()], axis=1)  # (M = H*W, 2)
        sample_pts = np.stack([xs, ys], axis=1)  # (N, 2)
        n_samples = len(xs)

        # Distances: (M, N)
        dx = target_pts[:, 0:1] - sample_pts[:, 0].T
        dy = target_pts[:, 1:2] - sample_pts[:, 1].T
        dist = np.sqrt(dx * dx + dy * dy)

        p = max(1.0, float(options.power))
        eps = 1e-12

        # 1. Search radius filtering
        valid_mask = np.ones_like(dist, dtype=bool)
        if options.search_radius is not None and options.search_radius > 0:
            valid_mask = dist <= float(options.search_radius)

        # 2. Max neighbors filtering (keep top k nearest within search radius per target)
        if options.max_neighbors is not None and 0 < options.max_neighbors < n_samples:
            k = int(options.max_neighbors)
            dist_masked = np.where(valid_mask, dist, np.inf)
            k_mask = np.zeros_like(valid_mask, dtype=bool)
            nearest_indices = np.argpartition(dist_masked, kth=k - 1, axis=1)[:, :k]
            valid_k = np.take_along_axis(dist_masked, nearest_indices, axis=1) < np.inf
            np.put_along_axis(k_mask, nearest_indices, valid_k, axis=1)
            valid_mask = valid_mask & k_mask

        # Count active neighbors per target point
        neighbor_counts = np.sum(valid_mask, axis=1)
        min_n = max(1, int(options.min_neighbors))

        # Calculate inverse distance weights
        weights = np.zeros_like(dist, dtype=np.float64)
        np.divide(1.0, np.maximum(dist, eps) ** p, out=weights, where=valid_mask)
        weights[~valid_mask] = 0.0

        # Exact matches within valid mask
        exact_match = (dist < eps) & valid_mask
        weights[exact_match] = 0.0

        weight_sum = np.sum(weights, axis=1)
        z_grid_flat = np.full(len(target_pts), np.nan, dtype=np.float64)

        # Calculate values where neighbor_counts >= min_neighbors
        eligible = neighbor_counts >= min_n
        positive_weights = eligible & (weight_sum > 0)
        if np.any(positive_weights):
            z_grid_flat[positive_weights] = np.sum(weights[positive_weights] * zs, axis=1) / weight_sum[positive_weights]

        # Apply exact matches
        match_rows, match_cols = np.nonzero(exact_match)
        if match_rows.size > 0:
            for r, c in zip(match_rows, match_cols):
                if neighbor_counts[r] >= min_n:
                    z_grid_flat[r] = zs[c]

        grid_z = z_grid_flat.reshape((grid_n, grid_n))

        sample_points_param = [
            {"well": p.well_name or p.well_id, "x": p.x, "y": p.y, "value": p.value}
            for p in dataset.valid_points
        ]

        algo_params = {
            "method": "idw",
            "power": p,
            "grid_n": grid_n,
            "n_samples": n_samples,
            "search_radius": options.search_radius,
            "min_neighbors": options.min_neighbors,
            "max_neighbors": options.max_neighbors,
            "sample_points": sample_points_param,
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

    model_name = str(model).lower() if str(model).lower() in ("spherical", "exponential", "gaussian") else "spherical"
    sill = float(np.var(z)) if float(np.var(z)) > 1e-6 else 1.0
    dmax = float(np.max(dists)) if float(np.max(dists)) > 1e-6 else 1.0
    r = dmax * 0.8 if dmax > 1e-6 else 1.0
    nugget = 0.0

    def gamma(h: np.ndarray) -> np.ndarray:
        h = np.asarray(h, dtype=np.float64)
        if model_name == "spherical":
            hr = np.clip(h / max(r, 1e-6), 0.0, 1.0)
            g = sill * (1.5 * hr - 0.5 * hr ** 3)
            g = np.where(h >= r, sill, g)
        elif model_name == "exponential":
            g = sill * (1.0 - np.exp(-3.0 * h / max(r, 1e-6)))
        elif model_name == "gaussian":
            g = sill * (1.0 - np.exp(-3.0 * (h / max(r, 1e-6)) ** 2))
        else:
            g = sill * (1.0 - np.exp(-3.0 * h / max(r, 1e-6)))
        return nugget + g

    def cov(h: np.ndarray) -> np.ndarray:
        return (sill + nugget) - gamma(h)

    # Augmented kriging matrix K with ridge regularization
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
        {
            "method": "kriging_fallback",
            "model": model_name,
            "range": r,
            "sill": sill,
            "nugget": nugget,
            "n_samples": n,
        },
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
