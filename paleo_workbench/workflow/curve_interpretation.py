"""Well curve interpretation: explicit operations → DERIVED versions (P1-A / L3).

RAW curve datasets are immutable; every interpretation correction (depth
shift, despike, baseline shift, smoothing, resample, normalization, unit
conversion, derived curves, …) is a user-attributable operation that produces
a NEW derived LAS file and a catalog DERIVED version through
:data:`DataCatalogService.create_derived` — carrying the full provenance
set: input version ids, operation, parameters (including original sample
count / resample metadata / unit provenance), generator, time, output
version ids. Nothing here ever writes to a RAW payload.

Operation scopes (:data:`OPERATION_SCOPE`):

* ``depth_axis`` — transforms the measured-depth axis (depth_shift);
* ``curve`` — per-curve numeric kernel (despike, baseline_shift, smooth,
  median_filter, normalize, clip_outliers, unit_conversion);
* ``file`` — whole-file transforms that must keep every curve aligned
  (resample, depth_unit_normalize);
* ``derive`` — controlled-expression derived curve (derive_curve; the
  evaluator lives in :mod:`curve_operations` and never calls ``eval``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np

from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.workflow.curve_operations import (
    clip_outliers,
    conversion_factor,
    convert_values,
    evaluate_curve_expression,
    interp_nan_aware,
    median_filter_curve,
    missing_interval_report,
    moving_average,
    normalize_curve,
    resample_axis,
)

logger = logging.getLogger(__name__)

GENERATOR_ID = "curve-interpretation-v2"


# ---------------------------------------------------------------------------
# Numeric operations (pure functions — testable without any catalog)
# ---------------------------------------------------------------------------


def depth_shift(depths: np.ndarray, delta_m: float) -> np.ndarray:
    """Shift the measured-depth axis by *delta_m* (positive = deeper)."""
    return np.asarray(depths, dtype=float) + float(delta_m)


def despike(values: np.ndarray, threshold_sigma: float = 3.0, window: int = 3) -> np.ndarray:
    """Replace samples deviating > *threshold_sigma* from a rolling median.

    The rolling median is spike-resistant: a single extreme sample does not
    drag its own baseline, so the replacement stays local (interpretation
    correction, not a smoothing filter — the rest of the curve is untouched).
    """
    arr = np.asarray(values, dtype=float).copy()
    if arr.size == 0:
        return arr
    # Non-finite samples ride along as spikes too (they cannot be plotted).
    finite = np.isfinite(arr)
    if not finite.any():
        return arr
    from scipy.ndimage import median_filter

    window = max(1, int(window) | 1)  # odd, ≥1
    baseline = median_filter(np.where(finite, arr, np.nanmedian(arr)), size=window, mode="reflect")
    residual = arr - baseline
    # Robust scale: the ordinary std is itself dragged by the spikes being
    # detected (one 999.25 sample can hide itself). MAD-based sigma cannot.
    residual_finite = residual[finite]
    mad = np.median(np.abs(residual_finite - np.median(residual_finite)))
    # Floor at 1% of the curve's own range: on quiet stretches the MAD can
    # collapse to ~0 and flag ordinary rounding noise as spikes.
    spread_floor = 0.01 * float(np.ptp(arr[finite])) if int(finite.sum()) > 1 else 1.0
    spread = max(1.4826 * float(mad), spread_floor, 1e-9)
    spike = np.abs(residual) > float(threshold_sigma) * spread
    arr[spike] = baseline[spike]
    return arr


def baseline_shift(values: np.ndarray, delta: float) -> np.ndarray:
    """Add a constant environmental correction to the curve values."""
    return np.asarray(values, dtype=float) + float(delta)


# operation id -> (numeric kernel, required parameter names)
CURVE_OPERATIONS: dict[str, tuple[Callable[..., np.ndarray], tuple[str, ...]]] = {
    "depth_shift": (depth_shift, ("delta_m",)),
    "despike": (despike, ()),
    "baseline_shift": (baseline_shift, ("delta",)),
    "smooth": (moving_average, ("window",)),
    "median_filter": (median_filter_curve, ("window",)),
    "normalize": (normalize_curve, ()),
    "clip_outliers": (clip_outliers, ()),
    "unit_conversion": (convert_values, ("from_unit", "to_unit")),
    "resample": (resample_axis, ("step",)),
    "depth_unit_normalize": (conversion_factor, ("target_unit",)),
    "derive_curve": (evaluate_curve_expression, ("expression", "result_mnemonic")),
}

# How each operation touches the LAS file (see module docstring).
OPERATION_SCOPE: dict[str, str] = {
    "depth_shift": "depth_axis",
    "despike": "curve",
    "baseline_shift": "curve",
    "smooth": "curve",
    "median_filter": "curve",
    "normalize": "curve",
    "clip_outliers": "curve",
    "unit_conversion": "curve",
    "resample": "file",
    "depth_unit_normalize": "file",
    "derive_curve": "derive",
}


@dataclass
class CurveInterpretationResult:
    operation: str
    curve: str
    input_version_ids: list[str]
    output_version_id: str
    run_id: str
    derived_path: str


def apply_curve_operation(
    service: DataCatalogService,
    input_version_id: str,
    *,
    operation: str,
    curve: str,
    parameters: dict[str, Any],
) -> CurveInterpretationResult:
    """Apply one interpretation operation to one curve of a cataloged LAS.

    Reads the input version's payload, applies the numeric kernel, writes a
    NEW LAS beside the catalog's derived store, and registers the DERIVED
    version + DataRun with the complete provenance contract. The input
    version (RAW or any parent) is never modified.
    """
    if operation not in CURVE_OPERATIONS:
        raise ValueError(f"unknown curve operation {operation!r}")
    kernel, required = CURVE_OPERATIONS[operation]
    missing = [name for name in required if name not in (parameters or {})]
    if missing:
        raise ValueError(f"operation {operation!r} missing parameters: {missing}")

    try:
        input_version = service.get_version(input_version_id)
    except Exception as exc:
        raise ValueError(f"input version {input_version_id!r} not found") from exc
    input_path = service.resolve_path(input_version)
    if not input_path.is_file():
        raise FileNotFoundError(f"input payload missing: {input_path}")

    import lasio

    las = lasio.read(str(input_path))
    if curve not in las.curves:
        raise ValueError(f"curve {curve!r} not found in {input_path.name}")

    curve_values = np.asarray(las.curves[curve].data, dtype=float)
    kwargs = {k: v for k, v in (parameters or {}).items() if k != "curve"}
    scope = OPERATION_SCOPE.get(operation, "curve")
    provenance_extra: dict[str, Any] = {}

    if scope == "depth_axis":
        las.curves[las.curves[0].mnemonic].data = kernel(
            las.curves[las.curves[0].mnemonic].data, **kwargs
        )
    elif scope == "file":
        if operation == "resample":
            depth_axis = np.asarray(las.curves[las.curves[0].mnemonic].data, dtype=float)
            if depth_axis.size < 2:
                raise ValueError("resample needs a depth axis with ≥2 samples")
            original_step = float(depth_axis[1] - depth_axis[0]) if depth_axis.size > 1 else 0.0
            new_axis = resample_axis(depth_axis, float(kwargs["step"]))
            for log_curve in las.curves[1:]:
                log_curve.data = interp_nan_aware(
                    new_axis, depth_axis, np.asarray(log_curve.data, dtype=float)
                )
            las.curves[las.curves[0].mnemonic].data = new_axis
            provenance_extra = {
                "original_sample_count": int(depth_axis.size),
                "original_step": original_step,
                "new_step": float(kwargs["step"]),
            }
        elif operation == "depth_unit_normalize":
            target_unit = str(kwargs.get("target_unit", "m"))
            current_unit = (
                str(getattr(las.curves[0], "unit", "") or "m").strip() or "m"
            )
            factor = conversion_factor(current_unit, target_unit)  # raises on unknown
            if factor == 1.0:
                raise ValueError(
                    f"depth axis already in {target_unit!r}; nothing to normalize"
                )
            depth_axis = np.asarray(las.curves[las.curves[0].mnemonic].data, dtype=float)
            las.curves[las.curves[0].mnemonic].data = depth_axis * factor
            las.curves[0].unit = target_unit
            provenance_extra = {"unit_from": current_unit, "unit_to": target_unit}
        else:  # pragma: no cover - registry and scopes are defined together
            raise ValueError(f"unhandled file-scope operation {operation!r}")
    elif scope == "derive":
        expression = str(kwargs["expression"])
        result_mnemonic = str(kwargs["result_mnemonic"]).strip()
        result_unit = str(kwargs.get("result_unit", "") or "")
        if not result_mnemonic:
            raise ValueError("derive_curve needs a result_mnemonic")
        if result_mnemonic in las.curves:
            raise ValueError(
                f"curve {result_mnemonic!r} already exists in {input_path.name}"
            )
        variables = {
            str(log_curve.mnemonic): np.asarray(log_curve.data, dtype=float)
            for log_curve in las.curves[1:]
        }
        if not variables:
            raise ValueError("derive_curve needs at least one input curve")
        result = evaluate_curve_expression(expression, variables)
        las.append_curve(
            result_mnemonic, result, unit=result_unit, descr=f"derived: {expression}"
        )
        provenance_extra = {
            "expression": expression,
            "result_unit": result_unit,
        }
    else:
        new_values = kernel(curve_values, **kwargs)
        las.curves[curve].data = new_values
        if operation == "unit_conversion":
            las.curves[curve].unit = str(kwargs["to_unit"])
            provenance_extra = {
                "unit_from": str(kwargs["from_unit"]),
                "unit_to": str(kwargs["to_unit"]),
            }
    del curve_values

    # Stage the derived payload OUTSIDE the managed store (a RAW version's
    # directory is immutable); create_derived copies it into the derived
    # store, and the staging file is removed on every path.
    import tempfile

    with tempfile.NamedTemporaryFile(
        "w", suffix=".las", delete=False, encoding="utf-8"
    ) as handle:
        staged = Path(handle.name)
    _ensure_writable_well_header(las)
    las.write(str(staged))
    try:
        derived = service.create_derived(
            staged,
            parent_version_ids=[input_version_id],
            name=f"{input_version.asset_id} {operation} {curve}",
            operation=f"curve_interpretation:{operation}",
            parameters={"curve": curve, **dict(parameters or {}), **provenance_extra},
            generator=GENERATOR_ID,
            type="well_log",
            format="las",
        )
    finally:
        try:
            staged.unlink(missing_ok=True)
        except OSError:
            pass

    run_id = str(getattr(derived, "run_id", "") or "")
    if not run_id:
        for run in service.document.runs:
            if derived.id in (run.output_version_ids or ()):
                run_id = run.id
                break
    return CurveInterpretationResult(
        operation=operation,
        curve=curve,
        input_version_ids=[input_version_id],
        output_version_id=derived.id,
        run_id=run_id,
        derived_path=str(derived.path),
    )

def _ensure_writable_well_header(las) -> None:
    """Guarantee the STRT/STOP/STEP items lasio's writer requires.

    Minimal or hand-authored LAS files can omit them; the derived output
    must still be a readable LAS regardless of how sparse the input header
    was. Depth_shift also refreshes them to the shifted range. The depth
    unit follows the (possibly normalized) depth curve's own unit header.
    """
    from lasio import HeaderItem

    index = las.curves[0].data
    depth_unit = str(getattr(las.curves[0], "unit", "") or "M").strip() or "M"
    if len(index):
        start, stop = float(index[0]), float(index[-1])
        step = float(index[1] - index[0]) if len(index) > 1 else 0.0
    else:  # pragma: no cover - empty curve has nothing to interpret
        start = stop = step = 0.0
    well = las.well
    for mnemonic, value, desc in (
        ("STRT", start, "Start depth"),
        ("STOP", stop, "Stop depth"),
        ("STEP", step, "Step"),
        ("NULL", -999.25, "Null value"),
    ):
        if mnemonic not in well:
            well.append(HeaderItem(mnemonic=mnemonic, unit=depth_unit, value=value, descr=desc))
            continue
        # STRT/STOP/STEP track the (possibly shifted/resampled) axis; the
        # NULL sentinel is the FILE's own missing-value contract — a source
        # declaring -999.0 must stay -999.0 or every derived version would
        # silently redefine which samples are missing (review R1-M1).
        if mnemonic != "NULL":
            well[mnemonic].value = value
    for mnemonic in ("STRT", "STOP", "STEP"):
        well[mnemonic].unit = depth_unit
