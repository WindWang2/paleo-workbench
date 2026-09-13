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
from paleo_workbench.workflow.crs_policy import resolve_distance_policy


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

        if _neighborhood_requested(options.max_neighbors, options.search_radius):
            # V12-B (decision D3): the geoviz engine takes no neighbourhood
            # parameters, so honouring them means the numpy moving-
            # neighbourhood path — an explicit, disclosed downgrade of the
            # variogram estimator whenever the engine would have been used.
            grid_z, grid_var, algo_params = _pure_numpy_kriging(
                xs, ys, zs, grid_x, grid_y,
                model=options.variogram_model,
                max_neighbors=options.max_neighbors,
                search_radius=options.search_radius,
                min_neighbors=options.min_neighbors,
            )
            algo_params["sample_points"] = [
                {"well": p.well_name or p.well_id, "x": p.x, "y": p.y, "value": p.value}
                for p in dataset.valid_points
            ]
            algo_params["degraded"] = True
            algo_params["degraded_reason"] = (
                "moving-neighbourhood kriging runs on the numpy path "
                "(geoviz engine exposes no max_neighbors/search_radius); "
                "variogram fitted with numpy grid-OLS, not the engine's "
                "weighted WLS fit; r_squared not computed (engine LOO "
                "unavailable on this path)"
            )
            algo_params["variogram_fit"] = "numpy-grid-ols"
            algo_params["r_squared"] = None
            return FactorGridResult(
                grid_z=np.asarray(grid_z, dtype=np.float32),
                grid_x=grid_x,
                grid_y=grid_y,
                factor_name=dataset.factor_name,
                algorithm_id="kriging",
                algorithm_parameters=algo_params,
                crs=dataset.crs or options.crs,
                unit=dataset.unit,
                variance_grid=(
                    np.asarray(grid_var, dtype=np.float32)
                    if grid_var is not None
                    else None
                ),
            )

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
                "variogram_fit": "engine-wls",
                "r_squared": float(r2),
                "grid_n": grid_n,
                "n_samples": len(xs),
                "sample_points": [
                    {"well": p.well_name or p.well_id, "x": p.x, "y": p.y, "value": p.value}
                    for p in dataset.valid_points
                ],
            }

        except ImportError:
            # Fallback pure-numpy Ordinary Kriging. V8 M1: the fallback's
            # variogram estimator is a numpy grid-OLS fit — a DIFFERENT
            # estimator from the engine's pair-count-weighted bounded WLS
            # (scipy least_squares). The result is explicitly degraded and
            # labeled; downstream QA/publish gates read these keys instead
            # of treating the surface as engine-equivalent.
            grid_z, grid_var, algo_params = _pure_numpy_kriging(
                xs, ys, zs, grid_x, grid_y, model=options.variogram_model
            )
            algo_params["sample_points"] = [
                {"well": p.well_name or p.well_id, "x": p.x, "y": p.y, "value": p.value}
                for p in dataset.valid_points
            ]
            algo_params["degraded"] = True
            algo_params["degraded_reason"] = (
                "geoviz kriging engine unavailable: numpy fallback used a "
                "grid-OLS variogram fit, not the engine's weighted WLS fit; "
                "r_squared not computed (engine LOO unavailable)"
            )
            algo_params["variogram_fit"] = "numpy-grid-ols"
            algo_params["r_squared"] = None

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
    """Inverse Distance Weighting (IDW) interpolation.

    #1048: neighbour selection runs through ``scipy.spatial.cKDTree`` with
    chunked target queries (k nearest neighbours + optional search radius)
    instead of materialising the full (M, N) target-by-sample distance
    matrix, which allocated several 40000x2000 float64 arrays (~640 MiB
    each) for a 2000-well / 200x200-grid map. Weighting semantics (power,
    eps clamp, exact sample hits, min/max neighbours, radius pruning and
    NaN nodata where a target lacks the required neighbours) are unchanged.
    """

    #: Target rows per cKDTree query chunk: bounds the transient (chunk, k)
    #: work arrays while amortising per-call query overhead.
    QUERY_CHUNK = 8192

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
        target_pts = np.stack([gx.ravel(), gy.ravel()], axis=1)  # (M, 2)
        sample_pts = np.stack([xs, ys], axis=1)  # (N, 2)
        n_samples = len(xs)

        p = max(1.0, float(options.power))
        eps = 1e-12
        min_n = max(1, int(options.min_neighbors))
        radius = (
            float(options.search_radius)
            if options.search_radius is not None and options.search_radius > 0
            else None
        )
        k = n_samples
        if options.max_neighbors is not None and 0 < options.max_neighbors < n_samples:
            k = int(options.max_neighbors)

        if k >= n_samples and radius is None:
            # Every sample neighbours every target, so the neighbour search
            # degenerates to the identity — compute the (chunk, N) distances
            # directly in place and accumulate with one BLAS gemv (no index
            # gather, which dominates the k == N tree path).
            z_flat = _idw_all_neighbors(target_pts, sample_pts, zs, p, eps, min_n)
        else:
            z_flat = self._idw_knn(target_pts, sample_pts, zs, k, radius, p, eps, min_n)
        grid_z = z_flat.reshape((grid_n, grid_n))

        sample_points_param = [
            {"well": p_.well_name or p_.well_id, "x": p_.x, "y": p_.y, "value": p_.value}
            for p_ in dataset.valid_points
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

    def _idw_knn(
        self,
        target_pts: np.ndarray,
        sample_pts: np.ndarray,
        zs: np.ndarray,
        k: int,
        radius: float | None,
        p: float,
        eps: float,
        min_n: int,
    ) -> np.ndarray:
        """IDW over the k nearest samples (optionally radius-pruned).

        Missing neighbours (beyond ``radius`` or fewer than k samples exist)
        come back from cKDTree as ``inf`` distance with index == n_samples;
        ``1 / inf**p == 0`` then yields exactly the masked weight the previous
        full-matrix implementation produced.
        """
        try:
            from scipy.spatial import cKDTree
        except ImportError as exc:  # pragma: no cover - scipy ships with the app
            raise RuntimeError("IDW interpolation requires scipy (scipy.spatial.cKDTree)") from exc

        n_samples = len(zs)
        k = max(1, min(int(k), n_samples))
        tree = cKDTree(sample_pts)
        m = len(target_pts)
        out = np.full(m, np.nan, dtype=np.float64)
        chunk_len = max(1, min(self.QUERY_CHUNK, m)) if m else 0
        for start in range(0, m, chunk_len):
            stop = min(start + chunk_len, m)
            rows = stop - start
            dist, idx = tree.query(
                target_pts[start:stop],
                k=k,
                distance_upper_bound=radius if radius is not None else np.inf,
                workers=1,
            )
            dist = np.asarray(dist, dtype=np.float64).reshape(rows, k)
            idx = np.asarray(idx).reshape(rows, k)
            valid = np.isfinite(dist)
            neighbor_counts = valid.sum(axis=1)
            # Exact sample hits drop out of the weighted mean (their weight
            # is 0) and are re-applied below, matching the legacy contract.
            exact = valid & (dist < eps)
            # weights = 1 / max(dist, eps) ** p; inf (no neighbour) -> 0
            weights = 1.0 / np.power(np.maximum(dist, eps), p)
            weights[exact] = 0.0
            weight_sum = weights.sum(axis=1)
            eligible = neighbor_counts >= min_n
            positive = eligible & (weight_sum > 0)
            if positive.any():
                idx_safe = np.where(valid, idx, 0)
                values = (weights * zs[idx_safe]).sum(axis=1)
                denom = np.where(positive, weight_sum, 1.0)
                out[start:stop] = np.where(positive, values / denom, np.nan)
            # Exact matches take the sample value outright (only when the
            # target still meets min_neighbors); row-major order keeps the
            # last-hit-wins tie behaviour of the full-matrix loop.
            hit_rows, hit_cols = np.nonzero(exact & eligible[:, None])
            for r, c in zip(hit_rows, hit_cols):
                out[start + r] = zs[idx[r, c]]
        return out


# Memory guard for the IDW all-neighbour path (#1048): squared distances and
# one work copy live per (chunk x n_samples) block, so the chunk length adapts
# to the sample count (mirrors the kriging target-chunk budget below).
_IDW_TARGET_CELLS = 1 << 23  # ~8M float64 elements ≈ 64 MiB per work array
_IDW_TARGET_CHUNK = 1 << 16  # upper bound for tiny sample sets


def _idw_all_neighbors(
    target_pts: np.ndarray,
    sample_pts: np.ndarray,
    zs: np.ndarray,
    p: float,
    eps: float,
    min_n: int,
) -> np.ndarray:
    """IDW using every sample, computed in chunked (chunk, N) work arrays.

    Specialisation of the k-nearest query for ``k == N`` with no search
    radius: the neighbour set is every sample, so distances are formed
    directly (no index gather) and the weighted numerator accumulates through
    one BLAS matrix-vector product. Semantics — power weighting on
    ``max(dist, eps)``, exact hits taking the sample value, ``NaN`` nodata
    when ``min_neighbors`` is unmet or no positive weight remains — match the
    previous full-matrix implementation exactly.
    """
    m = len(target_pts)
    n = len(zs)
    out = np.full(m, np.nan, dtype=np.float64)
    if m == 0 or n == 0:
        return out
    if n < min_n:
        return out  # no target can meet min_neighbors -> all nodata
    sx = np.ascontiguousarray(sample_pts[:, 0])
    sy = np.ascontiguousarray(sample_pts[:, 1])
    eps_sq = eps * eps
    chunk_len = max(256, min(_IDW_TARGET_CHUNK, _IDW_TARGET_CELLS // n))
    for start in range(0, m, chunk_len):
        stop = min(start + chunk_len, m)
        chunk = target_pts[start:stop]
        dx = chunk[:, 0:1] - sx[None, :]
        dy = chunk[:, 1:2] - sy[None, :]
        dx *= dx
        dy *= dy
        dx += dy  # squared distances, in place
        # dist < eps  <=>  dist² < eps² (both non-negative)
        exact = dx < eps_sq
        # weight = 1 / max(dist, eps) ** p = max(dist², eps²) ** (-p / 2)
        np.maximum(dx, eps_sq, out=dx)
        if p == 2.0:
            np.reciprocal(dx, out=dx)
        else:
            np.power(dx, -0.5 * p, out=dx)
        dx[exact] = 0.0
        weight_sum = dx.sum(axis=1)
        positive = weight_sum > 0.0
        if positive.any():
            values = dx @ zs  # (chunk,) weighted sums, no gather
            denom = np.where(positive, weight_sum, 1.0)
            out[start:stop] = np.where(positive, values / denom, np.nan)
        # neighbour count is n >= min_n for every row here, so every exact
        # hit applies; row-major order keeps last-hit-wins tie behaviour.
        hit_rows, hit_cols = np.nonzero(exact)
        for r, c in zip(hit_rows, hit_cols):
            out[start + r] = zs[c]
    return out


# Memory guard for the target-evaluation broadcast (#1036). Each chunk
# transiently holds several (chunk x n_samples) float64 arrays (deltas,
# squared deltas, distances, covariance, weights), so the chunk length
# adapts to the sample count: a fixed 2**18 rows measured ~1.45 GiB at
# n=100 (review finding) — the n-scaled budget below keeps the peak in the
# same band for any n while amortizing the per-chunk solve cost.
_KRIGE_TARGET_CELLS = 1 << 26  # ~64M float64 elements ≈ 512 MiB per array
_KRIGE_TARGET_CHUNK = 1 << 18  # lower bound for tiny sample sets

# Moving-neighborhood budget (V12-B): each chunk holds (k+1)² covariance /
# system entries per target plus the (chunk, k) query results, so the chunk
# length scales with the per-target system size instead of the sample count.
_KRIGE_NEIGHBOR_CELLS = 1 << 26  # ~512 MiB per (chunk, k, k) float64 array
_KRIGE_NEIGHBOR_CHUNK = 1 << 14
# Per-target system size cap. A (k+1)² system per target is only tractable
# for bounded k; beyond this the request is capped and the cap is DISCLOSED
# in the result metadata (never silently applied).
_KRIGE_NEIGHBORHOOD_CAP = 256

_KRIGE_MODELS = ("spherical", "exponential", "gaussian")


def _neighborhood_requested(
    max_neighbors: int | None, search_radius: float | None
) -> bool:
    """True when the user opted into a bounded kriging neighbourhood."""
    if max_neighbors is not None and int(max_neighbors) > 0:
        return True
    return search_radius is not None and float(search_radius) > 0.0


def _effective_neighborhood_k(max_neighbors: int | None, n: int) -> int:
    """Resolve the per-target kNN size, honouring the tractability cap.

    ``k = min(requested, n, cap)`` — clamping to the sample count is normal
    kNN semantics (every sample is a neighbour), NOT an approximation; only
    the cap is, and only ``_neighborhood_disclosure`` marks it.
    """
    requested = int(max_neighbors) if max_neighbors is not None else n
    return int(min(max(1, requested), n, _KRIGE_NEIGHBORHOOD_CAP))


def _neighborhood_disclosure(
    max_neighbors: int | None,
    search_radius: float | None,
    min_neighbors: int,
    n: int,
) -> dict[str, Any]:
    """Metadata block that makes every neighbourhood approximation visible."""
    requested = int(max_neighbors) if max_neighbors is not None else n
    k_eff = _effective_neighborhood_k(max_neighbors, n)
    radius = (
        float(search_radius) if search_radius is not None and search_radius > 0 else None
    )
    block: dict[str, Any] = {
        "engine": "cKDTree-moving",
        "max_neighbors": k_eff,
        "requested_max_neighbors": requested,
        "search_radius": radius,
        "min_neighbors": max(1, int(min_neighbors)),
        "capped": min(requested, n) > k_eff,
    }
    if block["capped"]:
        block["cap"] = _KRIGE_NEIGHBORHOOD_CAP
        block["note"] = (
            "requested neighbourhood exceeds the tractability cap; "
            "only the nearest cap samples are used per target"
        )
    return block


def _deduplicate_samples(
    x: np.ndarray, y: np.ndarray, z: np.ndarray, tol: float = 1e-9
) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """Collapse coincident samples onto their mean value.

    Duplicate locations make the kriging covariance block exactly singular;
    geology treats repeated measurements at one point as one averaged
    observation.
    """
    order = np.lexsort((y, x))
    xs, ys, zs = x[order], y[order], z[order]
    keep_x: list[float] = []
    keep_y: list[float] = []
    sums: list[float] = []
    counts: list[int] = []
    i = 0
    n = len(zs)
    while i < n:
        j = i + 1
        total = float(zs[i])
        while j < n and abs(xs[j] - xs[i]) <= tol and abs(ys[j] - ys[i]) <= tol:
            total += float(zs[j])
            j += 1
        keep_x.append(float(xs[i]))
        keep_y.append(float(ys[i]))
        sums.append(total)
        counts.append(j - i)
        i = j
    merged = np.array(sums, dtype=np.float64) / np.array(counts, dtype=np.float64)
    duplicates = n - len(keep_x)
    return (
        np.asarray(keep_x, dtype=np.float64),
        np.asarray(keep_y, dtype=np.float64),
        merged,
        duplicates,
    )


def _empirical_variogram(
    dists: np.ndarray, semivariance: np.ndarray, max_lag: float, n_bins: int = 12
) -> tuple[np.ndarray, np.ndarray]:
    """Bin pairwise semivariances into lag classes up to *max_lag*."""
    mask = (dists > 1e-12) & (dists <= max_lag)
    h = dists[mask]
    sv = semivariance[mask]
    if h.size < n_bins:
        return np.empty(0), np.empty(0)
    edges = np.linspace(0.0, max_lag, n_bins + 1)
    idx = np.clip(np.digitize(h, edges) - 1, 0, n_bins - 1)
    sums = np.bincount(idx, weights=sv, minlength=n_bins)
    counts = np.bincount(idx, minlength=n_bins)
    valid = counts > 0
    return (edges[:-1] + edges[1:])[valid] * 0.5, sums[valid] / counts[valid]


def _model_semivariance(h: np.ndarray, nugget: float, psill: float, r: float, model: str) -> np.ndarray:
    """Standardized two-parameter semivariance models (effective range r)."""
    r = max(r, 1e-9)
    if model == "spherical":
        hr = np.clip(h / r, 0.0, 1.0)
        shape = 1.5 * hr - 0.5 * hr**3
    elif model == "gaussian":
        shape = 1.0 - np.exp(-3.0 * (h / r) ** 2)
    else:  # exponential
        shape = 1.0 - np.exp(-3.0 * h / r)
    return nugget + psill * shape


def _fit_variogram_numpy(
    dists: np.ndarray, z: np.ndarray, model: str, max_lag: float
) -> tuple[float, float, float, int]:
    """Fit (nugget, sill, effective range) to the empirical variogram.

    For each (range, nugget) candidate the optimal partial sill has a
    closed least-squares form, so a two-level grid refinement over the pair
    is dependency-free and deterministic.
    """
    iu = np.triu_indices_from(dists, k=1)
    h_pairs = dists[iu]
    sv_pairs = 0.5 * (z[:, None] - z[None, :]) [iu] ** 2
    lag, sv = _empirical_variogram(h_pairs, sv_pairs, max_lag)
    total_sill = max(float(np.var(z)), 1e-12)
    if lag.size < 3:
        return 0.0, total_sill, max(max_lag, 1e-6), int(lag.size)

    sv_max = float(sv.max())
    nugget_grid = np.linspace(0.0, min(0.5 * sv_max, 0.9 * total_sill), 6)
    lo, hi = max(1e-3 * max_lag, 1e-6), max_lag
    best = (0.0, total_sill, max(max_lag, 1e-6))
    best_sse = np.inf
    for _round in range(4):
        ranges = np.linspace(lo, hi, 12)
        for r in ranges:
            for nugget in nugget_grid:
                shape_sv = _model_semivariance(lag, nugget, 1.0, float(r), model) - nugget
                denom = float(np.sum(shape_sv**2))
                if denom < 1e-18:
                    continue
                psill = float(np.sum((sv - nugget) * shape_sv) / denom)
                psill = max(psill, 1e-9)
                fitted = nugget + psill * shape_sv
                sse = float(np.sum((sv - fitted) ** 2))
                if sse < best_sse:
                    best_sse = sse
                    best = (float(nugget), float(psill), float(r))
        nugget, psill, r = best
        # refine around the winner
        lo, hi = max(1e-6, r * 0.5), min(max_lag, r * 1.5) if r < max_lag else max_lag
        span = max(hi - lo, 1e-6)
        lo, hi = max(1e-6, r - span * 0.25), min(max_lag, r + span * 0.25)
        nugget_grid = np.linspace(
            max(0.0, nugget - 0.1 * sv_max), min(nugget + 0.1 * sv_max, 0.9 * total_sill), 5
        )
    nugget, psill, r = best
    return nugget, psill, r, int(lag.size)


def _kriging_moving_targets(
    sample_pts: np.ndarray,
    z: np.ndarray,
    targets: np.ndarray,
    cov,
    sill: float,
    total_sill: float,
    max_neighbors: int | None,
    search_radius: float | None,
    min_neighbors: int,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Moving-neighbourhood Ordinary Kriging over per-target kNN systems.

    Semantics (V12-B, decisions D2/D3 in docs/development/geopipeline-v12/):

    * each target solves its own augmented OK system restricted to its k
      nearest samples (optionally pruned by *search_radius*) — NOT an
      approximation of the global solution: pruned neighbours are
      eliminated from the system exactly, by zeroing their rows/columns
      and pinning their weights to 0 while the unbiasedness row still sums
      the *kept* weights to 1;
    * targets with fewer than *min_neighbors* kept neighbours are nodata
      (NaN), matching the IDW neighbourhood contract;
    * the per-target systems are solved through a batched
      ``np.linalg.solve((G, k+1, k+1))``; a singular batch falls back to the
      same solve → scaled-ridge → lstsq ladder as the global path.
    """
    from scipy.spatial import cKDTree

    n = len(z)
    m = len(targets)
    z_pred = np.full(m, np.nan, dtype=np.float64)
    variance = np.full(m, np.nan, dtype=np.float64)

    k_eff = _effective_neighborhood_k(max_neighbors, n)
    radius = (
        float(search_radius)
        if search_radius is not None and search_radius > 0
        else None
    )
    tree = cKDTree(sample_pts)
    system_cells = (k_eff + 1) * (k_eff + 1)
    chunk_rows = max(64, min(_KRIGE_NEIGHBOR_CHUNK, _KRIGE_NEIGHBOR_CELLS // system_cells))
    diag = np.arange(k_eff)
    ridge = 1e-10 * float(sill) if sill > 0 else 1e-10

    for start in range(0, m, chunk_rows):
        stop = min(start + chunk_rows, m)
        rows = stop - start
        dist, idx = tree.query(
            targets[start:stop],
            k=k_eff,
            distance_upper_bound=radius if radius is not None else np.inf,
            workers=1,
        )
        dist = np.asarray(dist, dtype=np.float64).reshape(rows, k_eff)
        idx = np.asarray(idx).reshape(rows, k_eff)
        valid = np.isfinite(dist)
        eligible = valid.sum(axis=1) >= min(min_neighbors, k_eff)
        sel = np.nonzero(eligible)[0]
        if sel.size == 0:
            continue

        d_tn = dist[sel]                      # (G, k)
        ids = idx[sel]                        # (G, k)
        keep = valid[sel]                     # (G, k)
        dropped = ~keep
        ids_safe = np.where(keep, ids, 0)
        # neighbour-neighbour distances, in-place to avoid the (G, k, k, 2)
        # broadcast temp (memory traffic dominates at k² per target)
        px = sample_pts[ids_safe, 0]          # (G, k)
        py = sample_pts[ids_safe, 1]
        d_nn = px[:, :, None] - px[:, None, :]
        d_nn *= d_nn
        dyy = py[:, :, None] - py[:, None, :]
        dyy *= dyy
        d_nn += dyy
        np.sqrt(d_nn, out=d_nn)               # (G, k, k)

        g = sel.size
        Knn = cov(d_nn)                       # cov(0) == sill on the diagonal
        cov_tn = cov(d_tn)                    # (G, k), reused for rhs + variance
        if dropped.any():
            # Exact elimination of pruned neighbours: zero their rows/columns
            # and pin their weight to 0 (identity row); the Lagrange row then
            # constrains only the kept weights.
            drop2 = dropped[:, :, None] | dropped[:, None, :]
            Knn[drop2] = 0.0
            diag_vals = Knn[:, diag, diag]
            diag_vals[dropped] = 1.0
            Knn[:, diag, diag] = diag_vals
            cov_tn[dropped] = 0.0
        K = np.zeros((g, k_eff + 1, k_eff + 1), dtype=np.float64)
        K[:, :k_eff, :k_eff] = Knn
        lagrange_col = np.where(dropped, 0.0, 1.0)
        K[:, k_eff, :k_eff] = lagrange_col
        K[:, :k_eff, k_eff] = lagrange_col

        rhs = np.zeros((g, k_eff + 1), dtype=np.float64)
        rhs[:, :k_eff] = cov_tn
        rhs[:, k_eff] = 1.0

        try:
            W = np.linalg.solve(K, rhs[:, :, None])[:, :, 0]
        except np.linalg.LinAlgError:
            W = np.empty_like(rhs)
            for gi in range(g):
                W[gi] = _solve_single_system(K[gi], rhs[gi], ridge, k_eff)

        w = W[:, :k_eff]
        mu = W[:, k_eff]
        z_vals = z[ids_safe]
        z_vals[dropped] = 0.0
        z_pred[start + sel] = (w * z_vals).sum(axis=1)
        variance[start + sel] = np.maximum(
            0.0,
            total_sill - ((w * cov_tn).sum(axis=1) + mu),
        )

    stats = _neighborhood_disclosure(max_neighbors, search_radius, min_neighbors, n)
    return z_pred, variance, stats


def _solve_single_system(
    K: np.ndarray, rhs: np.ndarray, ridge: float, k: int
) -> np.ndarray:
    """solve → scaled-ridge → lstsq ladder for one singular target system."""
    try:
        return np.linalg.solve(K, rhs)
    except np.linalg.LinAlgError:
        regularized = K.copy()
        idx = np.arange(k)
        regularized[idx, idx] += ridge * float(k)
        try:
            return np.linalg.solve(regularized, rhs)
        except np.linalg.LinAlgError:
            weights, *_ = np.linalg.lstsq(regularized, rhs, rcond=None)
            return weights


def _pure_numpy_kriging(
    x: np.ndarray, y: np.ndarray, z: np.ndarray,
    grid_x: np.ndarray, grid_y: np.ndarray,
    model: str = "spherical",
    max_neighbors: int | None = None,
    search_radius: float | None = None,
    min_neighbors: int = 1,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Self-contained numpy Ordinary Kriging fallback (#1036 remediation).

    Differences from the legacy fallback, mirroring the geoviz engine's
    semantics:

    * coincident samples are merged onto their mean (singular-matrix guard);
    * variogram parameters are FITTED to the empirical variogram (closed-form
      sill inside a deterministic (range, nugget) grid refinement) instead of
      ``sill = var(z), range = 0.8 * dmax`` magic constants;
    * the augmented ordinary-kriging system is solved with a symmetrized LU
      (``np.linalg.solve``) plus a scaled ridge fallback — never ``pinv`` on
      the indefinite saddle matrix, whose minimum-norm solution can violate
      the unbiasedness constraint;
    * target evaluation is chunked so the (M x N) broadcast stays
      memory-bounded for large grids.

    V12-B: *max_neighbors* / *search_radius* / *min_neighbors* opt into a
    moving-neighbourhood evaluator (per-target kNN systems via cKDTree).
    With both neighbourhood knobs unset the global path below runs
    UNCHANGED — bit-identical to the pre-V12-B fallback (golden baseline
    ``tests/data/geopipeline_golden``).
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    z = np.asarray(z, dtype=np.float64)
    model_name = str(model).lower() if str(model).lower() in _KRIGE_MODELS else "spherical"

    x, y, z, duplicates = _deduplicate_samples(x, y, z)
    n = len(z)
    if n == 0:
        raise ValueError("kriging requires at least one sample")
    sample_pts = np.stack([x, y], axis=1)
    dists = np.sqrt(np.sum((sample_pts[:, None, :] - sample_pts[None, :, :]) ** 2, axis=2))

    dmax = float(np.max(dists)) if n > 1 else 1.0
    max_lag = max(0.5 * dmax, 1e-6)
    nugget, psill, r, bins = _fit_variogram_numpy(dists, z, model_name, max_lag)
    sill = psill  # partial sill (structure variance) on top of the nugget

    def gamma(h: np.ndarray) -> np.ndarray:
        return _model_semivariance(np.asarray(h, dtype=np.float64), nugget, psill, r, model_name)

    def cov(h: np.ndarray) -> np.ndarray:
        return (sill + nugget) - gamma(h)

    # Constant field shortcut: unbiasedness makes every estimate the sample
    # mean and the variance collapses to the nugget — also guards the
    # degenerate zero-variance fit.
    if float(np.var(z)) <= 1e-12 or n == 1:
        z_const = float(np.mean(z))
        gxm, gym = np.meshgrid(grid_x, grid_y)
        var_const = np.full(gxm.shape, max(nugget, 0.0), dtype=np.float64)
        params = {
            "method": "kriging_fallback",
            "model": model_name,
            "range": r,
            "sill": float(sill),
            "nugget": float(nugget),
            "n_samples": n,
            "duplicates_merged": duplicates,
            "variogram_bins": bins,
            "variogram_fit": "numpy-grid-ols",
        }
        if _neighborhood_requested(max_neighbors, search_radius):
            params["neighborhood"] = _neighborhood_disclosure(
                max_neighbors, search_radius, min_neighbors, n
            )
            params["neighborhood"]["note"] = "constant field: every estimate is the sample mean"
        return (
            np.full_like(gxm, z_const),
            var_const,
            params,
        )

    total_sill = sill + nugget

    if _neighborhood_requested(max_neighbors, search_radius):
        # Moving neighbourhood (V12-B): per-target kNN systems instead of the
        # global (n+1)² solve — O(M·k³) instead of O(n³ + M·n²).
        gx, gy = np.meshgrid(grid_x, grid_y)
        targets = np.stack([gx.ravel(), gy.ravel()], axis=1)  # (M, 2)
        z_pred, variance, nb_stats = _kriging_moving_targets(
            sample_pts,
            z,
            targets,
            cov,
            float(sill),
            total_sill,
            max_neighbors,
            search_radius,
            min_neighbors,
        )
        return (
            z_pred.reshape((len(grid_y), len(grid_x))),
            variance.reshape((len(grid_y), len(grid_x))),
            {
                "method": "kriging_fallback",
                "model": model_name,
                "range": float(r),
                "sill": float(sill),
                "nugget": float(nugget),
                "n_samples": n,
                "duplicates_merged": duplicates,
                "variogram_bins": bins,
                "variogram_fit": "numpy-grid-ols",
                "neighborhood": nb_stats,
            },
        )

    # Augmented ordinary-kriging system. The scaled ridge (relative to the
    # covariance diagonal) regularizes nearly-coincident geometry without
    # flattening genuine structure the way a fixed 1e-8 would under UTM
    # magnitudes.
    K = np.zeros((n + 1, n + 1), dtype=np.float64)
    K[:n, :n] = cov(dists)
    np.fill_diagonal(K[:n, :n], K[0, 0])
    K[:n, n] = 1.0
    K[n, :n] = 1.0

    def solve_system(rhs_matrix: np.ndarray) -> np.ndarray:
        ridge = 1e-10 * float(K[0, 0]) if K[0, 0] > 0 else 1e-10
        try:
            return np.linalg.solve(K, rhs_matrix)
        except np.linalg.LinAlgError:
            regularized = K.copy()
            regularized[:n, :n] += np.eye(n) * ridge * float(n)
            try:
                return np.linalg.solve(regularized, rhs_matrix)
            except np.linalg.LinAlgError:
                weights, *_ = np.linalg.lstsq(regularized, rhs_matrix, rcond=None)
                return weights

    # Grid targets — chunked to bound the (chunk x N) broadcast (#1036).
    gx, gy = np.meshgrid(grid_x, grid_y)
    targets = np.stack([gx.ravel(), gy.ravel()], axis=1)  # (M, 2)
    m = len(targets)
    z_pred = np.empty(m, dtype=np.float64)
    variance = np.empty(m, dtype=np.float64)
    total_sill = sill + nugget
    chunk_rows = max(64, min(_KRIGE_TARGET_CHUNK, _KRIGE_TARGET_CELLS // max(n, 1)))
    for start in range(0, m, chunk_rows):
        stop = min(start + chunk_rows, m)
        chunk = targets[start:stop]
        deltas = chunk[:, None, :] - sample_pts[None, :, :]
        deltas *= deltas  # in-place square: no third (chunk, n, 2) temp
        tdists = np.sqrt(np.sum(deltas, axis=2))
        del deltas
        cov_matrix = cov(tdists)
        rhs = np.empty((n + 1, chunk.shape[0]), dtype=np.float64)
        rhs[:n] = cov_matrix.T
        rhs[n] = 1.0
        w = solve_system(rhs)  # (n+1, chunk)
        w = w.T  # (chunk, n+1)
        z_pred[start:stop] = w[:, :n] @ z
        # reuse the chunk covariance for the kriging variance row (review:
        # the previous loop recomputed cov(tdists) identically)
        variance[start:stop] = np.maximum(
            0.0,
            total_sill
            - (np.sum(w[:, :n] * cov_matrix, axis=1) + w[:, n]),
        )
        del cov_matrix

    return (
        z_pred.reshape((len(grid_y), len(grid_x))),
        variance.reshape((len(grid_y), len(grid_x))),
        {
            "method": "kriging_fallback",
            "model": model_name,
            "range": float(r),
            "sill": float(sill),
            "nugget": float(nugget),
            "n_samples": n,
            "duplicates_merged": duplicates,
            "variogram_bins": bins,
            "variogram_fit": "numpy-grid-ols",
        },
    )


def _domain_mask(
    grid_x: np.ndarray, grid_y: np.ndarray, boundary: list[tuple[float, float]]
) -> np.ndarray:
    """Vectorised ray-cast inside/outside test for grid cell centres.

    Returns a boolean ``(len(grid_y), len(grid_x))`` array: ``True`` where a
    cell centre lies inside (or on the edge of) the user boundary ring.
    """
    poly = np.asarray(boundary, dtype=float)
    if poly.ndim != 2 or poly.shape[0] < 3:
        raise ValueError("boundary ring needs at least 3 vertices")
    from paleo_workbench.mapping.geometry_planar import (
        points_in_polygon_vectorized,
    )

    xx, yy = np.meshgrid(
        np.asarray(grid_x, dtype=float), np.asarray(grid_y, dtype=float)
    )
    return points_in_polygon_vectorized(xx, yy, {
        "type": "Polygon",
        "coordinates": [[(float(x), float(y)) for x, y in poly]],
    })


def _apply_domain_options(
    result: FactorGridResult, options: InterpolationOptions
) -> FactorGridResult:
    """Consume the previously-dead ``InterpolationOptions.boundary`` (D6).

    The user domain ring masks every cell centre outside it to nodata across
    the *same* grid that contouring and polygonization later read, so the
    mask is identical along the whole chain. The masking is recorded as real
    algorithm output (masked-cell count) — never a silent edit.
    """
    if not options.boundary:
        return result
    ring = [(float(x), float(y)) for x, y in options.boundary]
    inside = _domain_mask(result.grid_x, result.grid_y, ring)
    masked = int(np.isfinite(result.grid_z[~inside]).sum())
    if masked:
        grid = np.array(result.grid_z, copy=True)
        grid[~inside] = NODATA
        result.grid_z = grid
        result.statistics = type(result.statistics).from_grid(grid)
    result.boundary = ring
    result.algorithm_parameters["domain_mask"] = "user_boundary"
    result.algorithm_parameters["domain_masked_cells"] = masked
    return result


def interpolate_factor(
    dataset: GeologicalFactorDataset, options: InterpolationOptions | None = None
) -> FactorGridResult:
    """Top-level interpolation dispatcher (single place where the user
    domain boundary and the D5 distance policy are enforced and recorded)."""
    if options is None:
        options = InterpolationOptions()
    if options.method.lower() in ("kriging", "ordinary_kriging", "ok"):
        engine = KrigingInterpolator()
    else:
        engine = IDWInterpolator()
    result = engine.interpolate(dataset, options)
    result = _apply_domain_options(result, options)
    policy = resolve_distance_policy(dataset.crs or None, options.distance_policy)
    result.algorithm_parameters["distance_policy"] = policy["policy"]
    result.algorithm_parameters["distance_policy_annotation"] = policy["annotation"]
    return result
