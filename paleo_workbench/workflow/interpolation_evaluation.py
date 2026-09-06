"""Unified interpolation accuracy evaluation (M2 workstation V2).

One evaluation authority for every single-factor interpolation method:

* :class:`EvaluationMetrics` — RMSE / MAE / bias / signed R² with honest
  skip accounting (non-finite pairs are counted, never silently dropped).
* :func:`spatial_fold_assignment` — deterministic spatial K-fold assignment
  (round-robin by angle around the centroid), the same scheme the
  constrained-IDW adapter introduced for #921.
* :func:`cross_validate_surface` — engine-agnostic K-fold surface CV. The
  caller injects a ``run_fold(points)`` closure that mirrors the production
  engine path (plain methods wrap ``interpolate_factor_grid``, the constrained
  engine wraps ``run_constrained_idw``), so evaluation can never drift from
  what production actually runs.
* :func:`kriging_leave_one_out` / :func:`kriging_diagnostics` — exact
  closed-form LOO (single inverse, Dubrule 1983) and variogram diagnostics
  from the geoviz kriging authority.

Computation and display are separate: this module returns data objects only;
residual point layers are built by the mapping side from
:func:`residual_features`.

The bilinear sampler and signed R² helpers were promoted here from
``workflow/constrained_idw_adapter`` (which now imports them back) so every
method is scored with byte-identical maths.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

import numpy as np

__all__ = [
    "EvaluationMetrics",
    "CrossValidationReport",
    "bilinear_sample_grid",
    "signed_r_squared",
    "spatial_fold_assignment",
    "cross_validate_surface",
    "surface_residuals",
    "residual_features",
    "kriging_leave_one_out",
    "kriging_diagnostics",
]

DEFAULT_CV_FOLDS = 4


def bilinear_sample_grid(
    grid_z: np.ndarray,
    grid_x: np.ndarray,
    grid_y: np.ndarray,
    px: float,
    py: float,
) -> float | None:
    """Bilinearly sample *grid_z* at map coordinates (px, py); NaN → None."""
    gx = np.asarray(grid_x, dtype=float)
    gy = np.asarray(grid_y, dtype=float)
    z = np.asarray(grid_z, dtype=float)
    x0, x1 = gx[0], gx[-1]
    y0, y1 = gy[0], gy[-1]
    nx, ny = gx.size, gy.size
    fi = (px - x0) / (x1 - x0) * (nx - 1) if nx > 1 else 0.0
    fj = (py - y0) / (y1 - y0) * (ny - 1) if ny > 1 else 0.0
    if not (math.isfinite(fi) and math.isfinite(fj)):
        return None
    i = min(max(int(math.floor(fi)), 0), nx - 2)
    j = min(max(int(math.floor(fj)), 0), ny - 2)
    a = fi - i
    b = fj - j
    # rows index y (grid_z shape = (len(grid_y), len(grid_x)))
    v = (
        z[j, i] * (1 - a) * (1 - b)
        + z[j, i + 1] * a * (1 - b)
        + z[j + 1, i] * (1 - a) * b
        + z[j + 1, i + 1] * a * b
    )
    if not math.isfinite(float(v)):
        return None
    return float(v)


def signed_r_squared(observed: np.ndarray, predicted: np.ndarray) -> float:
    """Signed R² over paired samples (never clamped; issue #844 convention)."""
    ss_res = float(np.sum((observed - predicted) ** 2))
    ss_tot = float(np.sum((observed - observed.mean()) ** 2))
    if ss_tot < 1e-12:
        return 1.0
    return float(1.0 - ss_res / ss_tot)


@dataclass(frozen=True, slots=True)
class EvaluationMetrics:
    """Accuracy metrics over paired observed/predicted samples."""

    rmse: float | None
    mae: float | None
    bias: float | None  # mean(observed - predicted); positive = surface under-predicts
    r_squared: float | None  # signed (#844)
    n_samples: int
    n_skipped: int  # pairs excluded because the prediction was not finite

    @classmethod
    def from_arrays(
        cls, observed: Sequence[float], predicted: Sequence[float]
    ) -> "EvaluationMetrics":
        obs = np.asarray(observed, dtype=float)
        pred = np.asarray(predicted, dtype=float)
        if obs.shape != pred.shape:
            raise ValueError(
                f"observed/predicted shape mismatch: {obs.shape} vs {pred.shape}"
            )
        valid = np.isfinite(obs) & np.isfinite(pred)
        n_skipped = int(obs.size - int(valid.sum()))
        o = obs[valid]
        p = pred[valid]
        if o.size == 0:
            return cls(None, None, None, None, 0, n_skipped)
        err = o - p
        return cls(
            rmse=float(np.sqrt(np.mean(err**2))),
            mae=float(np.mean(np.abs(err))),
            bias=float(np.mean(err)),
            r_squared=signed_r_squared(o, p),
            n_samples=int(o.size),
            n_skipped=n_skipped,
        )

    def to_dict(self) -> dict[str, Any]:
        def num(value: float | None) -> float | None:
            if value is None:
                return None
            return value if math.isfinite(value) else None

        return {
            "rmse": num(self.rmse),
            "mae": num(self.mae),
            "bias": num(self.bias),
            "r_squared": num(self.r_squared),
            "n_samples": self.n_samples,
            "n_skipped": self.n_skipped,
        }


def _with_n_skipped(
    metrics: EvaluationMetrics, n_skipped: int
) -> EvaluationMetrics:
    return EvaluationMetrics(
        rmse=metrics.rmse,
        mae=metrics.mae,
        bias=metrics.bias,
        r_squared=metrics.r_squared,
        n_samples=metrics.n_samples,
        n_skipped=n_skipped,
    )


def spatial_fold_assignment(
    x: Sequence[float], y: Sequence[float], k: int = DEFAULT_CV_FOLDS
) -> list[np.ndarray]:
    """Deterministic spatial fold ids: round-robin by angle around the centroid.

    Same scheme as the constrained-IDW adapter (#921): sectors of the survey
    become folds, so held-out wells are genuinely peripheral to their training
    set instead of interleaved neighbours.
    """
    if k < 2:
        raise ValueError(f"k must be >= 2, got {k}")
    xs = np.asarray(x, dtype=float)
    ys = np.asarray(y, dtype=float)
    if xs.size != ys.size:
        raise ValueError("x/y size mismatch")
    if xs.size == 0:
        return []
    angle = np.arctan2(ys - ys.mean(), xs - xs.mean())
    order = np.argsort(angle, kind="stable")
    folds: list[list[int]] = [[] for _ in range(k)]
    for rank, idx in enumerate(order):
        folds[rank % k].append(int(idx))
    return [np.array(fold, dtype=int) for fold in folds]


@dataclass(slots=True)
class CrossValidationReport:
    """Result of one cross-validation run (data only — rendering is separate)."""

    method: str
    scheme: str  # "kfold_surface" | "loo_exact" | "unavailable"
    k: int
    metrics: EvaluationMetrics
    folds: list[dict[str, Any]] = field(default_factory=list)
    residuals: list[dict[str, float]] = field(default_factory=list)
    engine: str = ""
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "scheme": self.scheme,
            "k": self.k,
            "metrics": self.metrics.to_dict(),
            "folds": list(self.folds),
            "engine": self.engine,
            "detail": self.detail,
        }


def leave_one_well_out_folds(
    points: Sequence[Mapping[str, Any]],
) -> list[np.ndarray]:
    """Fold indices grouping samples by WELL identity (V6 §11/§13).

    Every fold holds out ALL samples of one well — the honest scheme when
    well-level bias (not point noise) is the question: an interpolator can
    look good under point-wise folds while failing to transfer across
    wells. Wells are keyed by ``well_id`` (falling back to ``name``); wells
    with neither are treated as anonymous single-sample wells.
    """
    folds_by_key: dict[str, list[int]] = {}
    anonymous = 0
    for index, pt in enumerate(points):
        key = str(pt.get("well_id") or pt.get("name") or "").strip()
        if not key:
            anonymous += 1
            key = f"__anonymous_{index}"
        folds_by_key.setdefault(key, []).append(index)
    return [np.array(idx, dtype=int) for idx in folds_by_key.values()]


def cross_validate_surface(
    points: Sequence[Mapping[str, Any]],
    *,
    run_fold: Callable[[list[Mapping[str, Any]]], tuple[Any, Any, Any]],
    k: int = DEFAULT_CV_FOLDS,
    method_label: str = "",
    engine: str = "",
    cancellation_token=None,
) -> CrossValidationReport | None:
    """Spatial K-fold cross-validation of a *surface* interpolation engine.

    *run_fold* receives the training points and returns ``(grid_x, grid_y,
    grid_z)`` exactly as the production engine emits them (``None``-encoded
    nodata allowed — the bilinear scorer treats non-finite as unresolvable).
    Held-out points whose bilinear window touches nodata are counted as
    skipped, never faked. Returns ``None`` when evaluation cannot honestly
    run (too few points for *k* folds); the caller hides the metric instead.
    """
    # Fold over the FINITE sample list only: fold indices must index exactly
    # the points that participate, otherwise a single NaN sample shifts every
    # assignment and silently holds out the wrong wells (review R1-P1).
    scorable: list[Mapping[str, Any]] = []
    seen_coords: set[tuple[float, float]] = set()
    n_nonfinite = 0
    n_duplicates = 0
    for pt in points:
        x_v = float(pt.get("x"))
        y_v = float(pt.get("y"))
        z_v = float(pt.get("value", pt.get("z", float("nan"))))
        if not (math.isfinite(x_v) and math.isfinite(y_v) and math.isfinite(z_v)):
            n_nonfinite += 1
            continue
        # Twin wells (identical coordinates): a held-out twin is anchored by
        # its in-fold twin and scores zero residual, inflating CV accuracy —
        # duplicate groups enter as ONE sample (review R3-P1).
        coord_key = (x_v, y_v)
        if coord_key in seen_coords:
            n_duplicates += 1
            continue
        seen_coords.add(coord_key)
        scorable.append(pt)
    if len(scorable) < k + 2:
        return None
    x = [float(p.get("x")) for p in scorable]
    y = [float(p.get("y")) for p in scorable]
    folds = spatial_fold_assignment(x, y, k)
    observed_all: list[float] = []
    predicted_all: list[float] = []
    attempted = 0
    fold_records: list[dict[str, Any]] = []
    residuals: list[dict[str, float]] = []
    for fold_idx, test_indices in enumerate(folds):
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        test_set = {int(i) for i in test_indices}
        train = [scorable[i] for i in range(len(scorable)) if i not in test_set]
        held = [scorable[i] for i in sorted(test_set)]
        if len(train) < 2 or not held:
            fold_records.append({"fold": fold_idx, "status": "skipped", "n_skipped": len(held)})
            continue
        try:
            gx, gy, gz = run_fold(train)
        except Exception as exc:
            # A fold engine failure must stay visible, not become a silently
            # smaller evaluation set (#921 convention).
            return CrossValidationReport(
                method=method_label,
                scheme="unavailable",
                k=k,
                metrics=EvaluationMetrics(None, None, None, None, 0, 0),
                folds=fold_records,
                engine=engine,
                detail=f"fold {fold_idx} failed: {type(exc).__name__}: {exc}",
            )
        gz = np.asarray(gz, dtype=float)
        fold_obs: list[float] = []
        fold_pred: list[float] = []
        fold_skipped = 0
        attempted += len(held)
        for pt in held:
            px = float(pt.get("x"))
            py = float(pt.get("y"))
            pv = float(pt.get("value", pt.get("z", float("nan"))))
            sampled = bilinear_sample_grid(gz, gx, gy, px, py)
            if sampled is None:
                fold_skipped += 1
                continue
            fold_obs.append(pv)
            fold_pred.append(sampled)
            residuals.append(
                {
                    "x": px,
                    "y": py,
                    "value": pv,
                    "predicted": sampled,
                    "residual": pv - sampled,
                }
            )
        observed_all.extend(fold_obs)
        predicted_all.extend(fold_pred)
        fold_metrics = EvaluationMetrics.from_arrays(fold_obs, fold_pred)
        fold_payload = fold_metrics.to_dict()
        fold_payload["n_held_skipped"] = fold_skipped
        fold_records.append(
            {
                "fold": fold_idx,
                "n_train": len(train),
                "n_held": len(held),
                **fold_payload,
            }
        )
    metrics = EvaluationMetrics.from_arrays(observed_all, predicted_all)
    if metrics.n_samples < attempted:
        # Held-out points the surface could not score (nodata window) are
        # unresolvable, not absent — report the count.
        metrics = _with_n_skipped(metrics, attempted - metrics.n_samples)
    return CrossValidationReport(
        method=method_label,
        scheme="kfold_surface",
        k=k,
        metrics=metrics,
        folds=fold_records,
        residuals=residuals,
        engine=engine,
        detail=(
            f"scorable={len(scorable)}"
            + (f"; non_finite_dropped={n_nonfinite}" if n_nonfinite else "")
            + (f"; duplicates_merged={n_duplicates}" if n_duplicates else "")
        ),
    )


def surface_residuals(
    points: Sequence[Mapping[str, Any]],
    grid_x: Any,
    grid_y: Any,
    grid_z: Any,
) -> tuple[list[dict[str, float]], EvaluationMetrics]:
    """In-sample surface residuals: sample value minus the delivered surface.

    This measures how well the *produced grid* reproduces its own inputs
    (anchoring fidelity for re-anchoring engines) — it is NOT cross-validated
    accuracy and must be labelled as such wherever shown.
    """
    observed: list[float] = []
    predicted: list[float] = []
    records: list[dict[str, float]] = []
    for pt in points:
        px = float(pt.get("x"))
        py = float(pt.get("y"))
        pv = float(pt.get("value", pt.get("z", float("nan"))))
        sampled = bilinear_sample_grid(grid_z, grid_x, grid_y, px, py)
        if sampled is None:
            continue
        observed.append(pv)
        predicted.append(sampled)
        records.append(
            {
                "x": px,
                "y": py,
                "value": pv,
                "predicted": sampled,
                "residual": pv - sampled,
            }
        )
    return records, EvaluationMetrics.from_arrays(observed, predicted)


def residual_features(residuals: Sequence[Mapping[str, float]]) -> list[dict[str, Any]]:
    """GeoJSON-style point features for a residual layer (display concern)."""
    return [
        {
            "type": "Feature",
            "id": f"residual_{i}",
            "geometry": {"type": "Point", "coordinates": [float(r["x"]), float(r["y"])]},
            "properties": {
                "value": float(r["value"]),
                "predicted": float(r["predicted"]),
                "residual": float(r["residual"]),
            },
        }
        for i, r in enumerate(residuals)
    ]


# ---------------------------------------------------------------------------
# Kriging exact LOO + variogram diagnostics (geoviz authority)
# ---------------------------------------------------------------------------


def recommend_interpolation_methods(
    points: Sequence[Mapping[str, Any]],
    *,
    methods: Sequence[str],
    run_fold: Callable[[list[Mapping[str, Any]]], tuple[Any, Any, Any]],
    requested_constraints: Sequence[str] | None = None,
    k: int = DEFAULT_CV_FOLDS,
    cancellation_token=None,
) -> dict[str, Any]:
    """Cross-method comparison with a structured recommendation (V6 §13).

    Every method in *methods* is scored by the same spatial K-fold surface
    CV (``run_fold`` has the :func:`cross_validate_surface` contract). The
    recommendation NEVER rests on metrics alone: a method with violated
    constraints (capability matrix, §10) is disqualified regardless of its
    RMSE — a great number computed by ignoring the user's geology is not a
    better answer.
    """
    requested = [str(c) for c in (requested_constraints or [])]
    entries: list[dict[str, Any]] = []
    for method in methods:
        report = cross_validate_surface(
            points,
            run_fold=run_fold,
            k=k,
            method_label=str(method),
            cancellation_token=cancellation_token,
        )
        capability_warnings: list[str] = []
        if requested:
            from paleo_workbench.workflow.constraint_capabilities import (
                evaluate_request,
            )

            from paleo_workbench.workflow.constraint_capabilities import ConstraintKind

            kinds: list[ConstraintKind] = []
            for name in requested:
                try:
                    kinds.append(ConstraintKind(name))
                except ValueError:
                    capability_warnings.append(f"unknown constraint {name!r}")
            if kinds:
                evaluation = evaluate_request(str(method), kinds)
                capability_warnings.extend(evaluation.diagnostics)
        if report is None:
            entries.append(
                {
                    "method": str(method),
                    "metrics": None,
                    "capability_warnings": capability_warnings
                    or ["evaluation unavailable: too few scorable samples"],
                    "recommended": False,
                    "rationale": "cross-validation could not run honestly "
                    "(insufficient samples for the fold scheme)",
                }
            )
            continue
        entries.append(
            {
                "method": str(method),
                "metrics": report.to_dict()["metrics"],
                "n_folds": report.k,
                "residuals": report.residuals[:200],
                "capability_warnings": capability_warnings,
            }
        )

    def _score(entry: dict[str, Any]) -> float:
        metrics = entry.get("metrics") or {}
        rmse = metrics.get("rmse")
        return float(rmse) if rmse is not None else float("inf")

    best_metric_method: str | None = None
    scorable = [e for e in entries if e.get("metrics")]
    if scorable:
        best_metric_method = min(scorable, key=_score)["method"]

    for entry in entries:
        warnings = entry.get("capability_warnings") or []
        unsupported = any(":unsupported:" in w for w in warnings)
        if entry.get("metrics") is None:
            continue  # rationale already set
        if unsupported:
            entry["recommended"] = False
            entry["rationale"] = (
                "disqualified: requested constraints ignored by this method "
                "(capability matrix) — metrics alone cannot justify it"
            )
        elif entry["method"] == best_metric_method:
            entry["recommended"] = True
            entry["rationale"] = (
                "best cross-validated RMSE among methods that honor every "
                "requested constraint"
            )
        else:
            entry["recommended"] = False
            entry["rationale"] = (
                f"higher cross-validated RMSE than {best_metric_method!r}"
            )
    return {
        "scheme": "spatial_kfold_surface",
        "k": k,
        "requested_constraints": requested,
        "methods": entries,
        "recommended_method": next(
            (e["method"] for e in entries if e.get("recommended")), None
        ),
    }


def kriging_leave_one_out(
    points: Sequence[Mapping[str, Any]],
    *,
    variogram_model: str = "spherical",
    cancellation_token=None,
) -> CrossValidationReport | None:
    """Exact closed-form kriging LOO via the geoviz kriging authority.

    Returns ``None`` when there are too few points or the geoviz kriging
    module is unavailable; degenerate systems surface as an ``unavailable``
    report with the engine's error in ``detail``.
    """
    try:
        from geoviz_plots.factor.kriging import leave_one_out_predictions
    except ImportError:
        return None
    x, y, z = _points_to_arrays(points)
    if x.size < 3:
        return None
    if cancellation_token is not None:
        cancellation_token.raise_if_cancelled()
    try:
        preds, z_dedup = leave_one_out_predictions(
            x, y, z, variogram_model=variogram_model
        )
    except ValueError as exc:
        return CrossValidationReport(
            method="kriging",
            scheme="unavailable",
            k=1,
            metrics=EvaluationMetrics(None, None, None, None, 0, 0),
            engine="geoviz_plots.factor.kriging",
            detail=str(exc),
        )
    metrics = EvaluationMetrics.from_arrays(z_dedup, preds)
    residuals = [
        {
            "x": float(xi),
            "y": float(yi),
            "value": float(zi),
            "predicted": float(pi),
            "residual": float(zi - pi),
        }
        for xi, yi, zi, pi in zip(x, y, z_dedup, preds)
    ]
    return CrossValidationReport(
        method="kriging",
        scheme="loo_exact",
        k=1,
        metrics=metrics,
        residuals=residuals,
        engine="geoviz_plots.factor.kriging",
    )


def kriging_diagnostics(
    points: Sequence[Mapping[str, Any]],
    *,
    variogram_model: str = "spherical",
    n_lags: int = 12,
) -> dict[str, Any] | None:
    """Empirical variogram + fitted model parameters for one factor dataset.

    Returns ``None`` when the geoviz kriging module is unavailable or the
    samples cannot support a fit; a failed fit is reported with
    ``"fit": "defaulted"`` instead of being passed off as a real fit.
    """
    try:
        from geoviz_plots.factor.kriging import empirical_variogram, fit_variogram
    except ImportError:
        return None
    x, y, z = _points_to_arrays(points)
    if x.size < 3:
        return None
    try:
        emp = empirical_variogram(x, y, z, n_lags=n_lags)
    except ValueError:
        return None
    lags = np.asarray(emp["lags"], dtype=float)
    gamma = np.asarray(emp["gamma"], dtype=float)
    counts = np.asarray(emp["counts"], dtype=int)
    finite = np.isfinite(gamma)
    result: dict[str, Any] = {
        "model": variogram_model,
        "n_samples": int(x.size),
        "lags": [float(v) for v in lags[finite]],
        "semivariance": [float(v) for v in gamma[finite]],
        "n_pairs": [int(v) for v in counts[finite]],
        "n_empty_bins": int((~finite).sum()),
    }
    try:
        fitted = fit_variogram(x, y, z, model=variogram_model)
        result.update(
            {
                "range": float(fitted["range"]),
                "sill": float(fitted["sill"]),
                "nugget": float(fitted["nugget"]),
                "fit": "fitted",
            }
        )
    except (ValueError, RuntimeError):
        result["fit"] = "defaulted"
    return result


def _points_to_arrays(
    points: Sequence[Mapping[str, Any]],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []
    for pt in points:
        px = float(pt.get("x"))
        py = float(pt.get("y"))
        pv = float(pt.get("value", pt.get("z", float("nan"))))
        if not (math.isfinite(px) and math.isfinite(py) and math.isfinite(pv)):
            continue
        xs.append(px)
        ys.append(py)
        zs.append(pv)
    return (
        np.asarray(xs, dtype=float),
        np.asarray(ys, dtype=float),
        np.asarray(zs, dtype=float),
    )
