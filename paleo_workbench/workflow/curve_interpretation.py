"""Well curve interpretation: explicit operations → DERIVED versions (P1-A).

RAW curve datasets are immutable; every interpretation correction (depth
shift, despike, baseline shift) is a user-attributable operation that
produces a NEW derived LAS file and a catalog DERIVED version through
:data:`DataCatalogService.create_derived` — carrying the full provenance
set: input version ids, operation, parameters, generator, time, output
version ids. Nothing here ever writes to a RAW payload.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np

from paleo_workbench.catalog.service import DataCatalogService

logger = logging.getLogger(__name__)

GENERATOR_ID = "curve-interpretation-v1"


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
    if operation == "depth_shift":
        las.curves[las.curves[0].mnemonic].data = kernel(
            las.curves[las.curves[0].mnemonic].data, **kwargs
        )
        new_values = curve_values
    else:
        new_values = kernel(curve_values, **kwargs)
        las.curves[curve].data = new_values
    del new_values

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
            parameters={"curve": curve, **dict(parameters or {})},
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
    was. Depth_shift also refreshes them to the shifted range.
    """
    from lasio import HeaderItem

    index = las.curves[0].data
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
            well.append(HeaderItem(mnemonic=mnemonic, unit="M", value=value, descr=desc))
    well["STRT"].value = start
    well["STOP"].value = stop
    well["STEP"].value = step
