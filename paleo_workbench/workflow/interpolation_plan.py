"""Reusable spatial plans for multi-factor interpolation (same geometry, different values).

An :class:`InterpolationPlan` captures geometry- and config-dependent work that does
*not* depend on factor values, so batch preparation can:

    build plan once → apply values many times

Value-dependent weighted sums and LOO / fidelity metrics are never stored on the plan.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np

from geoviz import extract_xy_values

__all__ = [
    "InterpolationPlan",
    "PlanKey",
    "build_idw_plan",
    "apply_idw_plan",
    "apply_idw_plan_multi",
    "xy_signature",
    "plan_key_from_arrays",
]


def _orientation(a, b, c) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(a, b, p, tolerance: float) -> bool:
    return (
        min(a[0], b[0]) - tolerance <= p[0] <= max(a[0], b[0]) + tolerance
        and min(a[1], b[1]) - tolerance <= p[1] <= max(a[1], b[1]) + tolerance
    )


def _segments_intersect(
    p1: tuple[float, float],
    p2: tuple[float, float],
    q1: tuple[float, float],
    q2: tuple[float, float],
    *,
    tolerance: float = 1e-12,
) -> bool:
    """Match geo-viz IDW fault barrier intersection semantics."""
    o1 = _orientation(p1, p2, q1)
    o2 = _orientation(p1, p2, q2)
    o3 = _orientation(q1, q2, p1)
    o4 = _orientation(q1, q2, p2)
    if ((o1 > tolerance and o2 < -tolerance) or (o1 < -tolerance and o2 > tolerance)) and (
        (o3 > tolerance and o4 < -tolerance) or (o3 < -tolerance and o4 > tolerance)
    ):
        return True
    return (
        (abs(o1) <= tolerance and _on_segment(p1, p2, q1, tolerance))
        or (abs(o2) <= tolerance and _on_segment(p1, p2, q2, tolerance))
        or (abs(o3) <= tolerance and _on_segment(q1, q2, p1, tolerance))
        or (abs(o4) <= tolerance and _on_segment(q1, q2, p2, tolerance))
    )


def xy_signature(x: np.ndarray, y: np.ndarray) -> str:
    """Stable content hash of source coordinates (order-preserving)."""
    x = np.ascontiguousarray(x, dtype=np.float64)
    y = np.ascontiguousarray(y, dtype=np.float64)
    h = hashlib.sha256()
    h.update(np.uint64(x.size).tobytes())
    h.update(x.tobytes())
    h.update(y.tobytes())
    return h.hexdigest()[:24]


# Per-chunk element budget (cells × wells).  The fault mask and the IDW weight
# tensors are chunked so peak memory stays flat as the well count grows
# (chunk = budget // n_wells cells) instead of scaling with 16384 × n_wells.
_ELEMENT_BUDGET = 4_194_304  # 16_384 cells × 256 wells


def _chunk_cells_for_budget(element_budget: int, n_src: int) -> int:
    return max(1, int(element_budget) // max(1, int(n_src)))


def _fault_segments(
    fault_polylines: Sequence[Sequence[tuple[float, float]]] | None,
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for polyline in fault_polylines or []:
        if len(polyline) >= 2:
            for i in range(len(polyline) - 1):
                segments.append((polyline[i], polyline[i + 1]))
    return segments


def _fault_blocked_mask(
    cell_x: np.ndarray,
    cell_y: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    fault_segments: Sequence[tuple[tuple[float, float], tuple[float, float]]],
    *,
    element_budget: int = _ELEMENT_BUDGET,
    cancellation_token=None,
    tolerance: float = 1e-12,
) -> np.ndarray:
    """Vectorized fault-barrier LOS mask: ``blocked[c, w]`` == segment c→w crosses any fault.

    Replicates the reference per-element Python loop (``_segments_intersect``)
    exactly — same orientation arithmetic, same tolerance handling, same
    endpoint-touch / collinear semantics — but evaluated with NumPy per fault
    segment.  Cells are processed in chunks bounded by ``element_budget`` so
    peak memory stays flat as the well count grows.  Cancellation is checked
    between cell chunks and between segments.

    Orientation identities keep the per-segment work small: with
    ``outer = cross(cell, well)`` (segment-independent), each segment only adds
    two 1-D ``cross`` terms per endpoint::
        orient(cell, well, q) = cross(well, q) - cross(cell, q) + outer
    """
    n_cells = int(np.size(cell_x))
    n_wells = int(np.size(x))
    blocked = np.zeros((n_cells, n_wells), dtype=bool)
    if n_cells == 0 or n_wells == 0 or not fault_segments:
        return blocked
    cell_x = np.asarray(cell_x, dtype=np.float64)
    cell_y = np.asarray(cell_y, dtype=np.float64)
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    wx = x[None, :]
    wy = y[None, :]
    chunk = _chunk_cells_for_budget(element_budget, n_wells)
    for start in range(0, n_cells, chunk):
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        stop = min(start + chunk, n_cells)
        cx = cell_x[start:stop, None]
        cy = cell_y[start:stop, None]
        # cross(cell, well) — shared by every segment.
        outer = cx * wy - cy * wx
        chunk_blocked = np.zeros((stop - start, n_wells), dtype=bool)
        for (q1x, q1y), (q2x, q2y) in fault_segments:
            if cancellation_token is not None:
                cancellation_token.raise_if_cancelled()
            seg_dx = q2x - q1x
            seg_dy = q2y - q1y
            # Orientation of each fault endpoint w.r.t. the (cell → well) line.
            o1 = (wx * q1y - wy * q1x) - (cx * q1y - cy * q1x) + outer
            o2 = (wx * q2y - wy * q2x) - (cx * q2y - cy * q2x) + outer
            # Orientation of each cell / well w.r.t. the fault segment line
            # (column/row vectors broadcast to the (cell × well) pair grid).
            o3 = seg_dx * (cy - q1y) - seg_dy * (cx - q1x)
            o4 = seg_dx * (wy - q1y) - seg_dy * (wx - q1x)
            s1 = o1 > tolerance
            s2 = o1 < -tolerance
            s3 = o2 > tolerance
            s4 = o2 < -tolerance
            strict = ((s1 & s4) | (s2 & s3)) & (
                ((o3 > tolerance) & (o4 < -tolerance))
                | ((o3 < -tolerance) & (o4 > tolerance))
            )
            hit = strict
            # Endpoint-touch / collinear-overlap branches (rare): they require
            # a fault endpoint on some (cell → well) line, i.e. |o| <= tol for
            # some pair.  Generic geometry never satisfies that; scan only when
            # the cheap all() check fails.
            if not (s1 | s2).all():
                rows, cols = np.nonzero(~(s1 | s2))
                if rows.size:
                    cxs = cx[rows, 0]
                    cys = cy[rows, 0]
                    wxs = wx[0, cols]
                    wys = wy[0, cols]
                    ok = (
                        (np.minimum(cxs, wxs) - tolerance <= q1x)
                        & (q1x <= np.maximum(cxs, wxs) + tolerance)
                        & (np.minimum(cys, wys) - tolerance <= q1y)
                        & (q1y <= np.maximum(cys, wys) + tolerance)
                    )
                    if np.any(ok):
                        hit[rows[ok], cols[ok]] = True
            if not (s3 | s4).all():
                rows, cols = np.nonzero(~(s3 | s4))
                if rows.size:
                    cxs = cx[rows, 0]
                    cys = cy[rows, 0]
                    wxs = wx[0, cols]
                    wys = wy[0, cols]
                    ok = (
                        (np.minimum(cxs, wxs) - tolerance <= q2x)
                        & (q2x <= np.maximum(cxs, wxs) + tolerance)
                        & (np.minimum(cys, wys) - tolerance <= q2y)
                        & (q2y <= np.maximum(cys, wys) + tolerance)
                    )
                    if np.any(ok):
                        hit[rows[ok], cols[ok]] = True
            # Cell on the fault segment line (blocks the whole row) / well on
            # the fault segment line (blocks the whole column).
            o3_flat = o3[:, 0]
            o4_flat = o4[0, :]
            cells_on = (np.abs(o3_flat) <= tolerance) & (
                (min(q1x, q2x) - tolerance <= cx[:, 0])
                & (cx[:, 0] <= max(q1x, q2x) + tolerance)
                & (min(q1y, q2y) - tolerance <= cy[:, 0])
                & (cy[:, 0] <= max(q1y, q2y) + tolerance)
            )
            wells_on = (np.abs(o4_flat) <= tolerance) & (
                (min(q1x, q2x) - tolerance <= wx[0, :])
                & (wx[0, :] <= max(q1x, q2x) + tolerance)
                & (min(q1y, q2y) - tolerance <= wy[0, :])
                & (wy[0, :] <= max(q1y, q2y) + tolerance)
            )
            if np.any(cells_on):
                hit[cells_on, :] = True
            if np.any(wells_on):
                hit[:, wells_on] = True
            chunk_blocked |= hit
        blocked[start:stop] = chunk_blocked
    return blocked


def _plan_fault_mask(
    plan: "InterpolationPlan", cancellation_token=None
) -> np.ndarray | None:
    """Full-grid LOS barrier mask for *plan*, computed once and cached.

    The mask depends only on geometry (grid axes + well XY + fault segments),
    never on factor values, so one mask serves every factor in a batch.
    """
    if not plan.fault_polylines:
        return None
    if plan.fault_mask is None:
        cell_x = np.tile(plan.grid_x, len(plan.grid_y))
        cell_y = np.repeat(plan.grid_y, len(plan.grid_x))
        plan.fault_mask = _fault_blocked_mask(
            cell_x,
            cell_y,
            plan.source_x,
            plan.source_y,
            _fault_segments(plan.fault_polylines),
            cancellation_token=cancellation_token,
        )
    return plan.fault_mask


def _grid_axes_from_samples(
    x: np.ndarray, y: np.ndarray, grid_n: int
) -> tuple[np.ndarray, np.ndarray]:
    """Match geo-viz ``_grid_axes`` padding (5% span, min pad 1e-6)."""
    n = max(2, int(grid_n))
    if len(x) == 0:
        gx = np.linspace(0.0, 1.0, n, dtype=np.float64)
        gy = np.linspace(0.0, 1.0, n, dtype=np.float64)
        return gx, gy
    pad_x = max((float(x.max()) - float(x.min())) * 0.05, 1e-6)
    pad_y = max((float(y.max()) - float(y.min())) * 0.05, 1e-6)
    gx = np.linspace(float(x.min()) - pad_x, float(x.max()) + pad_x, n, dtype=np.float64)
    gy = np.linspace(float(y.min()) - pad_y, float(y.max()) + pad_y, n, dtype=np.float64)
    return gx, gy


@dataclass(frozen=True, slots=True)
class PlanKey:
    """Config + geometry identity for plan reuse."""

    method: str
    xy_sig: str
    grid_n: int
    power: float
    fault_sig: str
    azimuth_deg: float
    semi_major: float
    semi_minor: float

    def digest(self) -> str:
        raw = (
            f"{self.method}|{self.xy_sig}|{self.grid_n}|{self.power:.12g}|"
            f"{self.fault_sig}|{self.azimuth_deg:.12g}|{self.semi_major:.12g}|"
            f"{self.semi_minor:.12g}"
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _fault_signature(
    fault_polylines: Sequence[Sequence[tuple[float, float]]] | None,
) -> str:
    if not fault_polylines:
        return "none"
    parts: list[str] = []
    for poly in fault_polylines:
        pts = ",".join(f"{float(x):.9g}:{float(y):.9g}" for x, y in poly)
        parts.append(pts)
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


def plan_key_from_arrays(
    *,
    method: str,
    x: np.ndarray,
    y: np.ndarray,
    grid_n: int,
    power: float = 2.0,
    fault_polylines: Sequence[Sequence[tuple[float, float]]] | None = None,
    azimuth_deg: float = 0.0,
    semi_major: float = 1.0,
    semi_minor: float = 0.4,
) -> PlanKey:
    return PlanKey(
        method=str(method),
        xy_sig=xy_signature(x, y),
        grid_n=int(grid_n),
        power=float(power),
        fault_sig=_fault_signature(fault_polylines),
        azimuth_deg=float(azimuth_deg),
        semi_major=float(semi_major),
        semi_minor=float(semi_minor),
    )


@dataclass(slots=True)
class InterpolationPlan:
    """Geometry-fixed plan for plain IDW (and simple non-value spatial prep).

    Stores immutable contiguous axes and source coordinates.  Distances are
    *not* materialised for the full grid (that would be O(G²·N) memory); the
    chunked engine path recomputes them, but axes / sample XY / config are shared.
    """

    key: PlanKey
    source_x: np.ndarray
    source_y: np.ndarray
    grid_x: np.ndarray
    grid_y: np.ndarray
    fault_polylines: list[list[tuple[float, float]]] | None = None
    # Session geometry interning for multi-factor axis sharing
    geometry_id: str = field(default="")
    # Lazily computed full-grid LOS barrier mask (see _plan_fault_mask).
    fault_mask: np.ndarray | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.source_x = _freeze_array(np.ascontiguousarray(self.source_x, dtype=np.float64))
        self.source_y = _freeze_array(np.ascontiguousarray(self.source_y, dtype=np.float64))
        self.grid_x = _freeze_array(np.ascontiguousarray(self.grid_x, dtype=np.float64))
        self.grid_y = _freeze_array(np.ascontiguousarray(self.grid_y, dtype=np.float64))
        if not self.geometry_id:
            self.geometry_id = f"{self.key.xy_sig}:{self.key.grid_n}"


def _freeze_array(arr: np.ndarray) -> np.ndarray:
    out = np.array(arr, copy=True, order="C") if not arr.flags["OWNDATA"] else arr
    out.setflags(write=False)
    return out


def build_idw_plan(
    sample_points: list[dict[str, Any]] | None,
    *,
    grid_n: int = 50,
    power: float = 2.0,
    fault_polylines: Sequence[Sequence[tuple[float, float]]] | None = None,
) -> InterpolationPlan:
    """Build a plain-IDW plan from host sample_points records."""
    x, y, z = extract_xy_values(sample_points)
    if len(z) < 2:
        raise ValueError("插值至少需要 2 个有效采样点")
    # z discarded — plan is geometry-only
    gx, gy = _grid_axes_from_samples(x, y, grid_n)
    breaks = None
    if fault_polylines:
        breaks = [[(float(a), float(b)) for a, b in poly] for poly in fault_polylines]
    key = plan_key_from_arrays(
        method="idw",
        x=x,
        y=y,
        grid_n=grid_n,
        power=power,
        fault_polylines=breaks,
    )
    return InterpolationPlan(
        key=key,
        source_x=x,
        source_y=y,
        grid_x=gx,
        grid_y=gy,
        fault_polylines=breaks,
    )


def _idw_multi_chunked(
    x: np.ndarray,
    y: np.ndarray,
    z_stack: np.ndarray,
    grid_x: np.ndarray,
    grid_y: np.ndarray,
    *,
    power: float,
    fault_polylines: list[list[tuple[float, float]]] | None,
    fault_mask: np.ndarray | None = None,
    element_budget: int = _ELEMENT_BUDGET,
    cancellation_token=None,
) -> np.ndarray:
    """IDW for F value stacks sharing geometry: shape (F, H, W).

    Distances / base weights are built once per cell chunk, then dotted with each
    factor's values.  Avoids an F×G×N tensor by streaming factors over the chunk.
    Chunks are sized by an element budget (cells × wells), so per-chunk memory
    stays flat as the well count grows.  ``fault_mask`` is the precomputed
    (G, N) LOS barrier mask (see :func:`_fault_blocked_mask`); when faults are
    present and no mask is supplied it is computed once and reused for all
    chunks, with the cancellation token checked between chunks.
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    z_stack = np.ascontiguousarray(z_stack, dtype=np.float64)
    if z_stack.ndim != 2:
        raise ValueError("z_stack must be (n_factors, n_sources)")
    n_factors, n_src = z_stack.shape
    if n_src != len(x):
        raise ValueError("z_stack width must match source count")
    grid_x = np.asarray(grid_x, dtype=np.float64)
    grid_y = np.asarray(grid_y, dtype=np.float64)
    H, W = len(grid_y), len(grid_x)
    epsilon = 1e-12
    if n_src == 0 or H == 0 or W == 0:
        return np.full((n_factors, H, W), np.nan, dtype=np.float64)

    fault_segments = _fault_segments(fault_polylines)

    cell_x = np.tile(grid_x, H)
    cell_y = np.repeat(grid_y, W)
    out = np.full((n_factors, cell_x.size), np.nan, dtype=np.float64)
    chunk = _chunk_cells_for_budget(element_budget, n_src)
    if fault_segments and fault_mask is None:
        fault_mask = _fault_blocked_mask(
            cell_x,
            cell_y,
            x,
            y,
            fault_segments,
            element_budget=element_budget,
            cancellation_token=cancellation_token,
        )
    for start in range(0, cell_x.size, chunk):
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        stop = min(start + chunk, cell_x.size)
        dx = cell_x[start:stop, None] - x[None, :]
        distances = np.hypot(dx, cell_y[start:stop, None] - y[None, :], out=dx)
        np.maximum(distances, epsilon, out=distances)
        np.power(distances, power, out=distances)
        weights = 1.0 / distances
        if fault_mask is not None:
            weights[fault_mask[start:stop]] = 0.0
        totals = np.sum(weights, axis=1)
        populated = totals > epsilon
        # weights[populated]: (P, N); z_stack: (F, N) → (F, P)
        if np.any(populated):
            w_pop = weights[populated]
            t_pop = totals[populated]
            # (F, P) = (F, N) @ (N, P)
            vals = (z_stack @ w_pop.T) / t_pop[None, :]
            out[:, start:stop][:, populated] = vals
    return out.reshape(n_factors, H, W)


def apply_idw_plan(
    plan: InterpolationPlan,
    values: np.ndarray | Sequence[float],
    *,
    cancellation_token=None,
) -> dict[str, Any]:
    """Interpolate *values* (length = n source points) onto the plan grid.

    Returns an engine-shaped dict with ndarray axes and grid_z (float64),
    plus summary stats.  LOO R² is omitted here for batch throughput; callers
    that need quality metrics can compute separately or use the single-task path.
    """
    z = np.asarray(values, dtype=np.float64)
    if z.shape != plan.source_x.shape:
        raise ValueError(
            f"values shape {z.shape} does not match plan sources {plan.source_x.shape}"
        )
    # Single-factor: use multi path with F=1 for identical math / chunking.
    stack = z.reshape(1, -1)
    grids = _idw_multi_chunked(
        plan.source_x,
        plan.source_y,
        stack,
        plan.grid_x,
        plan.grid_y,
        power=plan.key.power,
        fault_polylines=plan.fault_polylines,
        fault_mask=_plan_fault_mask(plan, cancellation_token),
        cancellation_token=cancellation_token,
    )
    grid_z = np.ascontiguousarray(grids[0], dtype=np.float64)
    finite = grid_z[np.isfinite(grid_z)]
    if finite.size == 0:
        raise ValueError("插值结果全为无效值")
    return {
        "grid_x": plan.grid_x,
        "grid_y": plan.grid_y,
        "grid_z": grid_z,
        "backend": "idw",
        "method": "IDW",
        "grid_n": int(plan.key.grid_n),
        "n_points": int(z.size),
        "n_break_lines": int(len(plan.fault_polylines or [])),
        "min": float(np.min(finite)),
        "max": float(np.max(finite)),
        "mean": float(np.mean(finite)),
        "r_squared": None,
        "power": float(plan.key.power),
        "geometry_id": plan.geometry_id,
    }


def apply_idw_plan_multi(
    plan: InterpolationPlan,
    values_stack: np.ndarray | Sequence[Sequence[float]],
    *,
    cancellation_token=None,
) -> list[dict[str, Any]]:
    """Apply many factor value vectors against one plan (shared distances/weights)."""
    stack = np.ascontiguousarray(values_stack, dtype=np.float64)
    if stack.ndim != 2:
        raise ValueError("values_stack must be 2-D (n_factors, n_sources)")
    if stack.shape[1] != plan.source_x.size:
        raise ValueError("values_stack width must match plan source count")
    grids = _idw_multi_chunked(
        plan.source_x,
        plan.source_y,
        stack,
        plan.grid_x,
        plan.grid_y,
        power=plan.key.power,
        fault_polylines=plan.fault_polylines,
        fault_mask=_plan_fault_mask(plan, cancellation_token),
        cancellation_token=cancellation_token,
    )
    results: list[dict[str, Any]] = []
    for i in range(stack.shape[0]):
        grid_z = np.ascontiguousarray(grids[i], dtype=np.float64)
        finite = grid_z[np.isfinite(grid_z)]
        if finite.size == 0:
            raise ValueError("插值结果全为无效值")
        results.append(
            {
                "grid_x": plan.grid_x,
                "grid_y": plan.grid_y,
                "grid_z": grid_z,
                "backend": "idw",
                "method": "IDW",
                "grid_n": int(plan.key.grid_n),
                "n_points": int(stack.shape[1]),
                "n_break_lines": int(len(plan.fault_polylines or [])),
                "min": float(np.min(finite)),
                "max": float(np.max(finite)),
                "mean": float(np.mean(finite)),
                "r_squared": None,
                "power": float(plan.key.power),
                "geometry_id": plan.geometry_id,
            }
        )
    return results


def extract_values_aligned(
    sample_points: list[dict[str, Any]] | None,
    plan: InterpolationPlan,
) -> np.ndarray:
    """Extract z values in the same order / filter as the plan's source XY.

    Re-runs coordinate filtering so invalid samples are dropped consistently with
    :func:`extract_xy_values`.  If the surviving XY do not match the plan, raises.
    """
    x, y, z = extract_xy_values(sample_points)
    if x.shape != plan.source_x.shape or not (
        np.allclose(x, plan.source_x) and np.allclose(y, plan.source_y)
    ):
        raise ValueError("sample geometry does not match interpolation plan")
    return z
