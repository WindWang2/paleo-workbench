"""CRS-aware geometry measures for contour/polygon products (V6 §15, P0-10).

Shoelace areas and polyline lengths computed in raw CRS axes are square
DEGREES / degrees under a geographic CRS — meaningless as physical areas.
This module labels every geometry measure with its unit and, for geographic
CRS, converts to an honestly-labelled local-scale approximation instead of
presenting degrees² as if they were meaningful.
"""

from __future__ import annotations

import math
from typing import Iterable, Sequence

_METRES_PER_DEGREE_LAT = 111_320.0


def is_geographic_crs(crs: str | None) -> bool:
    """True for geographic (lat/lon-degree) CRS — delegated to the D5
    authority ``crs_policy`` (single CRS predicate in the repo; review
    R2-P1/R3-P1: a substring heuristic here misclassified projected
    "WGS 84 / UTM …" strings and disagreed with crs_policy's answers)."""
    from paleo_workbench.workflow.crs_policy import crs_is_geographic

    try:
        result = crs_is_geographic(str(crs or "").strip())
    except Exception:
        return False
    return bool(result)


def area_unit_label(crs: str | None) -> str:
    """Unit label for areas computed in the CRS's own axes."""
    if is_geographic_crs(crs):
        return "deg²"
    if str(crs or "").strip():
        return f"{str(crs).strip()}-unit²"
    return "unknown-unit²"


def ring_area_with_unit(
    ring: Sequence[Sequence[float]], crs: str | None
) -> tuple[float, str, str | None]:
    """(area, unit_label, warning) for one coordinate ring.

    * projected CRS → shoelace in CRS units (typically m²), no warning;
    * geographic CRS → local-scale approximation in ≈m² (scale from the
      ring's mean latitude) with an explicit approximation warning — the
      honest alternative to presenting square degrees;
    * empty/unknown CRS → CRS-axis squares labelled unknown-unit² + warning.
    """
    from paleo_workbench.mapping.geological_pipeline.polygonization import (
        calculate_shoelace_area,
    )

    raw = calculate_shoelace_area(ring)
    if is_geographic_crs(crs):
        lats = [float(pt[1]) for pt in ring if len(pt) >= 2]
        mean_lat = math.radians(sum(lats) / len(lats)) if lats else 0.0
        scale = (_METRES_PER_DEGREE_LAT * math.cos(mean_lat)) * _METRES_PER_DEGREE_LAT
        approx = raw * scale
        return approx, "≈m² (local-scale approx, geographic CRS)", (
            f"CRS {crs!r} is geographic: area is a local-scale approximation "
            "from the ring's mean latitude; reproject to a projected CRS for "
            "exact areas"
        )
    if str(crs or "").strip():
        return raw, f"{str(crs).strip()}-unit²", None
    return raw, "unknown-unit²", "CRS undeclared: area unit is unknown (not metres)"


def polyline_length_with_unit(
    vertices: Iterable[Sequence[float]], crs: str | None
) -> tuple[float, str, str | None]:
    """(length, unit_label, warning) for one polyline in CRS axes."""
    pts = [(float(p[0]), float(p[1])) for p in vertices]
    if is_geographic_crs(crs):
        lats = [p[1] for p in pts]
        mean_lat = math.radians(sum(lats) / len(lats)) if lats else 0.0
        scale_x = _METRES_PER_DEGREE_LAT * math.cos(mean_lat)
        total = 0.0
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            dx = (x1 - x0) * scale_x
            dy = (y1 - y0) * _METRES_PER_DEGREE_LAT
            total += math.hypot(dx, dy)
        return total, "≈m (local-scale approx, geographic CRS)", (
            f"CRS {crs!r} is geographic: length is a local-scale approximation"
        )
    total = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        total += math.hypot(x1 - x0, y1 - y0)
    if str(crs or "").strip():
        return total, f"{str(crs).strip()}-unit", None
    return total, "unknown-unit", "CRS undeclared: length unit is unknown (not metres)"
