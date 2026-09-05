"""Domain-space measurement tools (G10).

All measurement math happens in **domain coordinates** — the renderer never
measures, and screen-space pixel distances are never converted into science.
Every tool returns a :class:`MeasurementRecord` (domain object) so results
are auditable, unit-labelled and persistable (ADR-08).
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np

from .domain import DomainError, HorizonSurface, MeasurementRecord, Provenance

__all__ = [
    "point_coordinate",
    "distance",
    "polyline_length",
    "vertical_difference",
    "thickness_at",
    "plane_orientation",
    "format_result",
]

_KIND_COUNTER: dict[str, int] = {}


def _next_id(kind: str) -> str:
    import itertools
    import threading

    lock = threading.Lock()
    with lock:
        _KIND_COUNTER[kind] = _KIND_COUNTER.get(kind, 0) + 1
        n = _KIND_COUNTER[kind]
    return f"measure:{kind}-{n}"


def _pts(points: Sequence[Sequence[float]], minimum: int, oid: str) -> np.ndarray:
    p = np.asarray(points, dtype=np.float64)
    if p.ndim != 2 or p.shape[0] < minimum or (p.size and p.shape[1] != 3):
        raise DomainError(f"{oid}: needs >= {minimum} (x, y, z) points")
    if not np.all(np.isfinite(p)):
        raise DomainError(f"{oid}: points must be finite")
    return p


def point_coordinate(
    point: Sequence[float],
    *,
    crs: str,
    unit: str = "m",
    vertical_domain: str = "depth",
    provenance: Provenance | None = None,
) -> MeasurementRecord:
    """Record a picked point in domain coordinates."""
    p = _pts([point], 1, "measure:point")
    return MeasurementRecord(
        object_id=_next_id("point"),
        name="Point",
        crs=crs,
        unit=unit,
        vertical_domain=vertical_domain,
        measurement_kind="point",
        points=p,
        result=None,
        extra={"x": float(p[0, 0]), "y": float(p[0, 1]), "z": float(p[0, 2])},
        provenance=provenance or Provenance(source_kind="derived"),
    )


def distance(
    a: Sequence[float],
    b: Sequence[float],
    *,
    crs: str,
    unit: str = "m",
    vertical_domain: str = "depth",
    provenance: Provenance | None = None,
) -> MeasurementRecord:
    """Straight-line 3-D distance between two domain points."""
    p = _pts([a, b], 2, "measure:distance")
    result = float(np.linalg.norm(p[1] - p[0]))
    return MeasurementRecord(
        object_id=_next_id("distance"),
        name="Distance",
        crs=crs,
        unit=unit,
        vertical_domain=vertical_domain,
        measurement_kind="distance",
        points=p,
        result=result,
        extra={"unit": unit},
        provenance=provenance or Provenance(source_kind="derived"),
    )


def polyline_length(
    points: Sequence[Sequence[float]],
    *,
    crs: str,
    unit: str = "m",
    vertical_domain: str = "depth",
    provenance: Provenance | None = None,
) -> MeasurementRecord:
    """3-D arc length of a picked polyline (>= 2 points)."""
    p = _pts(points, 2, "measure:polyline")
    result = float(np.linalg.norm(np.diff(p, axis=0), axis=1).sum())
    return MeasurementRecord(
        object_id=_next_id("polyline"),
        name="Polyline",
        crs=crs,
        unit=unit,
        vertical_domain=vertical_domain,
        measurement_kind="polyline",
        points=p,
        result=result,
        extra={"legs": int(len(p) - 1)},
        provenance=provenance or Provenance(source_kind="derived"),
    )


def vertical_difference(
    a: Sequence[float],
    b: Sequence[float],
    *,
    crs: str,
    unit: str = "m",
    vertical_domain: str = "depth",
    provenance: Provenance | None = None,
) -> MeasurementRecord:
    """Vertical (z) difference between two points, in the vertical unit."""
    p = _pts([a, b], 2, "measure:vert")
    result = float(p[1, 2] - p[0, 2])
    return MeasurementRecord(
        object_id=_next_id("vert"),
        name="Vertical Δ",
        crs=crs,
        unit=unit,
        vertical_domain=vertical_domain,
        measurement_kind="vertical_difference",
        points=p,
        result=result,
        extra={"dz": result},
        provenance=provenance or Provenance(source_kind="derived"),
    )


def thickness_at(
    x: float,
    y: float,
    top: HorizonSurface,
    base: HorizonSurface,
    *,
    crs: str | None = None,
    unit: str | None = None,
    provenance: Provenance | None = None,
) -> MeasurementRecord:
    """Vertical thickness between top and base at a world-XY location.

    Bilinear interpolation on each grid; NaN holes propagate as an error —
    a thickness through a hole is *unknown*, never zero (fail-closed).
    """
    if top.vertical_domain != base.vertical_domain or top.unit != base.unit:
        raise DomainError("thickness: top/base must share vertical domain and unit")
    crs = crs or top.crs
    unit = unit or top.unit
    p = np.array([[float(x), float(y), 0.0]])
    zt = _bilinear_z(top, float(x), float(y))
    zb = _bilinear_z(base, float(x), float(y))
    if zt is None or zb is None:
        raise DomainError(
            f"thickness at ({x:.2f}, {y:.2f}): point falls in a grid hole "
            "(NaN) — thickness unknown"
        )
    return MeasurementRecord(
        object_id=_next_id("thickness"),
        name="Thickness",
        crs=crs,
        unit=unit,
        vertical_domain=top.vertical_domain,
        measurement_kind="thickness",
        points=np.array([[x, y, zt], [x, y, zb]]),
        result=float(abs(zb - zt)),
        extra={
            "top_id": top.object_id,
            "base_id": base.object_id,
            "signed": float(zb - zt),
        },
        provenance=provenance or Provenance(source_kind="derived"),
    )


def _bilinear_z(hor: HorizonSurface, x: float, y: float) -> float | None:
    g = np.asarray(hor.z_grid, dtype=np.float64)
    dy, dx = hor.spacing
    x0, y0 = hor.origin
    fj = (x - x0) / dx if dx else 0.0
    fi = (y - y0) / dy if dy else 0.0
    nI, nX = g.shape
    j0, i0 = int(np.floor(fj)), int(np.floor(fi))
    if i0 < 0 or j0 < 0 or i0 + 1 >= nI or j0 + 1 >= nX:
        return None
    tj, ti = fj - j0, fi - i0
    corners = (g[i0, j0], g[i0, j0 + 1], g[i0 + 1, j0], g[i0 + 1, j0 + 1])
    if any(not np.isfinite(c) for c in corners):
        return None
    topmix = corners[0] * (1 - tj) + corners[1] * tj
    botmix = corners[2] * (1 - tj) + corners[3] * tj
    return float(topmix * (1 - ti) + botmix * ti)


def plane_orientation(
    points: Sequence[Sequence[float]],
    *,
    crs: str,
    unit: str = "m",
    vertical_domain: str = "depth",
    provenance: Provenance | None = None,
) -> MeasurementRecord:
    """Strike/dip of the best-fit plane through >= 3 picked points.

    Only meaningful when the picks genuinely span a plane (min eigenvalue
    ratio reported in ``extra``); the record still stores the raw picks so
    the fit is auditable.
    """
    p = _pts(points, 3, "measure:plane")
    centroid = p.mean(axis=0)
    u, s, vt = np.linalg.svd(p - centroid)
    normal = vt[-1]
    if normal[2] < 0:
        normal = -normal
    dip = float(np.degrees(np.arccos(np.clip(abs(normal[2]), 0.0, 1.0))))
    strike = float(np.degrees(np.arctan2(normal[1], normal[0])))
    if strike < 0:
        strike += 180.0
    planarity = float(s[1] / s[0]) if s[0] > 0 else 0.0
    return MeasurementRecord(
        object_id=_next_id("plane"),
        name="Plane",
        crs=crs,
        unit=unit,
        vertical_domain=vertical_domain,
        measurement_kind="plane_orientation",
        points=p,
        result=dip,
        extra={
            "strike_deg": strike,
            "dip_deg": dip,
            "planarity_ratio": planarity,
            "note": "dip result; strike in extra — planarity<0.05 means picks are near-collinear",
        },
        provenance=provenance or Provenance(source_kind="derived"),
    )


def format_result(record: MeasurementRecord) -> str:
    """Human-readable, unit-explicit result line for the inspector/panel."""
    unit = record.unit
    kind = record.measurement_kind
    if kind == "point":
        e = record.extra
        return f"({e.get('x', 0):.2f}, {e.get('y', 0):.2f}, {e.get('z', 0):.2f}) {unit}"
    if kind == "distance":
        return f"{record.result:.3f} {unit}"
    if kind == "polyline":
        legs = record.extra.get("legs", 0)
        return f"{record.result:.3f} {unit} ({legs} legs)"
    if kind == "vertical_difference":
        sign = "+" if (record.result or 0) >= 0 else ""
        return f"{sign}{record.result:.3f} {unit} (vertical)"
    if kind == "thickness":
        return f"{record.result:.3f} {unit} (vertical thickness)"
    if kind == "plane_orientation":
        e = record.extra
        return (
            f"strike {e.get('strike_deg', 0):.1f}° dip {e.get('dip_deg', 0):.1f}° "
            f"(planarity {e.get('planarity_ratio', 0):.2f})"
        )
    return f"{record.result} {unit}"
