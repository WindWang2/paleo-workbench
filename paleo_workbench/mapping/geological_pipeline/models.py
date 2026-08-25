"""Geological Factor Data Models and Interpolation Configurations."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Mapping, Sequence

import numpy as np


@dataclass(frozen=True, slots=True)
class GeologicalFactor:
    """One single geological factor measurement at a spatial well location."""

    name: str
    value: float
    unit: str = ""
    well_id: str = ""
    well_name: str = ""
    x: float = 0.0
    y: float = 0.0
    crs: str = "EPSG:4326"
    formation: str = ""
    interval: str = ""
    quality: float = 1.0
    qc_flag: str = "ok"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not math.isfinite(self.x) or not math.isfinite(self.y):
            raise ValueError(f"well coordinates must be finite: ({self.x}, {self.y})")


@dataclass
class GeologicalFactorDataset:
    """Validated collection of geological factor points for a horizon or interval."""

    factor_name: str
    unit: str = ""
    target_horizon: str = ""
    crs: str = "EPSG:4326"
    points: list[GeologicalFactor] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_point(self, point: GeologicalFactor) -> None:
        self.points.append(point)

    @property
    def valid_points(self) -> list[GeologicalFactor]:
        """Return points with finite numeric values and ok/valid QC flags."""
        return [
            p for p in self.points
            if math.isfinite(p.value) and p.qc_flag in ("ok", "good", "")
        ]

    def to_arrays(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Extract (x, y, value) numpy arrays from valid points."""
        pts = self.valid_points
        if not pts:
            return (
                np.zeros(0, dtype=np.float64),
                np.zeros(0, dtype=np.float64),
                np.zeros(0, dtype=np.float64),
            )
        xs = np.array([p.x for p in pts], dtype=np.float64)
        ys = np.array([p.y for p in pts], dtype=np.float64)
        zs = np.array([p.value for p in pts], dtype=np.float64)
        return xs, ys, zs

    @property
    def extent(self) -> tuple[float, float, float, float]:
        """Bounding box (xmin, ymin, xmax, ymax) of all points."""
        if not self.points:
            return (0.0, 0.0, 1.0, 1.0)
        xs = [p.x for p in self.points]
        ys = [p.y for p in self.points]
        xmin, xmax = min(xs), max(xs)
        ymin, ymax = min(ys), max(ys)
        pad_x = max(0.01, (xmax - xmin) * 0.1) if not math.isclose(xmin, xmax) else 0.05
        pad_y = max(0.01, (ymax - ymin) * 0.1) if not math.isclose(ymin, ymax) else 0.05
        return (xmin - pad_x, ymin - pad_y, xmax + pad_x, ymax + pad_y)

    def validate(self) -> list[str]:
        """Validate sample count, coordinate spread, and value sanity."""
        issues = []
        valid = self.valid_points
        if len(valid) < 2:
            issues.append(f"Insufficient sample points ({len(valid)}); at least 2 valid points required for spatial interpolation.")
            return issues
        xs, ys, zs = self.to_arrays()
        if math.isclose(float(np.min(xs)), float(np.max(xs))) and math.isclose(float(np.min(ys)), float(np.max(ys))):
            issues.append("All points are collocated at the same coordinate.")
        return issues


@dataclass
class InterpolationOptions:
    """Configuration for spatial interpolation and grid generation."""

    method: str = "kriging"  # kriging | idw | constrained_idw | spline
    grid_n: int = 50
    resolution: float | None = None
    variogram_model: str = "spherical"  # spherical | exponential | gaussian
    power: float = 2.0  # For IDW
    color_ramp: str = "porosity"
    contour_levels: list[float] | None = None
    contour_interval: float | None = None
    boundary: list[tuple[float, float]] | None = None
    crs: str = "EPSG:4326"
    anisotropy_angle: float | None = None
    anisotropy_ratio: float | None = None
