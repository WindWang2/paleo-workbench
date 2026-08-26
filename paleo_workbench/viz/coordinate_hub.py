"""CoordinateTransformHub: Unified Coordinate Transformation Engine (Features F17 & F18).

Provides bidirectional conversions across:
- 2D/3D Map CRS (X, Y, Z / TVD)
- Well Trajectory & Depth Datums (MD, TVD, TVDSS, nearest well spatial query)
- Seismic Grid Volumes (Inline, Crossline, TWT in milliseconds)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np


@dataclass
class WellTrajectoryData:
    """Well trajectory survey and 3D spatial positioning data."""

    well_id: str
    surface_x: float
    surface_y: float
    kb_m: float = 0.0
    total_depth_m: float = 0.0
    md: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.float64))
    tvd: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.float64))
    x: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.float64))
    y: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.float64))
    is_deviated: bool = False


def _compute_minimum_curvature_trajectory(
    surface_x: float,
    surface_y: float,
    kb_m: float,
    total_depth_m: float,
    stations: Sequence[tuple[float, float, float]],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Compute 3D well trajectory from survey stations (MD, Inc, Az) using minimum curvature method.

    Returns (md, tvd, x, y) arrays.
    """
    pts = sorted(
        [(float(s[0]), float(s[1]), float(s[2])) for s in stations],
        key=lambda p: p[0],
    )
    if not pts:
        td = max(float(total_depth_m), 10000.0)
        return (
            np.array([0.0, td], dtype=np.float64),
            np.array([0.0, td], dtype=np.float64),
            np.array([surface_x, surface_x], dtype=np.float64),
            np.array([surface_y, surface_y], dtype=np.float64),
        )

    # Prepend surface station (0, 0, 0) if first station MD > 0
    if pts[0][0] > 0.0:
        pts.insert(0, (0.0, 0.0, 0.0))

    n = len(pts)
    md = np.empty(n, dtype=np.float64)
    tvd = np.empty(n, dtype=np.float64)
    x = np.empty(n, dtype=np.float64)
    y = np.empty(n, dtype=np.float64)

    md[0] = pts[0][0]
    tvd[0] = pts[0][0] if (n == 1 and pts[0][1] == 0.0) else 0.0
    north_disp = 0.0
    east_disp = 0.0
    x[0] = surface_x
    y[0] = surface_y

    for i in range(1, n):
        md0, inc0_deg, az0_deg = pts[i - 1]
        md1, inc1_deg, az1_deg = pts[i]
        dmd = md1 - md0
        if dmd <= 0.0:
            md[i] = md1
            tvd[i] = tvd[i - 1]
            x[i] = x[i - 1]
            y[i] = y[i - 1]
            continue

        inc0 = math.radians(inc0_deg)
        az0 = math.radians(az0_deg)
        inc1 = math.radians(inc1_deg)
        az1 = math.radians(az1_deg)

        # Minimum curvature dogleg calculation
        di = inc1 - inc0
        da = az1 - az0
        cos_dl = math.cos(di) + math.sin(inc0) * math.sin(inc1) * (math.cos(da) - 1.0)
        cos_dl = max(-1.0, min(1.0, cos_dl))
        dl = math.acos(cos_dl)

        rf = (2.0 / dl) * math.tan(dl / 2.0) if dl > 1e-9 else 1.0
        half = 0.5 * dmd * rf

        d_tvd = half * (math.cos(inc0) + math.cos(inc1))
        d_north = half * (math.sin(inc0) * math.cos(az0) + math.sin(inc1) * math.cos(az1))
        d_east = half * (math.sin(inc0) * math.sin(az0) + math.sin(inc1) * math.sin(az1))

        tvd[i] = tvd[i - 1] + d_tvd
        north_disp += d_north
        east_disp += d_east
        x[i] = surface_x + east_disp
        y[i] = surface_y + north_disp
        md[i] = md1

    return md, tvd, x, y


class CoordinateTransformHub:
    """Central coordinate transformation service bridging Map, Well, and Seismic spaces."""

    def __init__(self) -> None:
        self._wells: dict[str, WellTrajectoryData] = {}
        # Default seismic grid geometry
        self._seismic_origin: tuple[float, float] = (100.0, 200.0)
        self._seismic_il_step: tuple[float, float] = (10.0, 0.0)
        self._seismic_xl_step: tuple[float, float] = (0.0, 10.0)
        self._il_min: int = 100
        self._xl_min: int = 200
        self._velocity: float = 2000.0  # m/s

    # -------------------------------------------------------------------------
    # Well Registry & Depth Transformations
    # -------------------------------------------------------------------------

    def register_well(
        self,
        well_id: str,
        x: float,
        y: float,
        elevation: float = 0.0,
        total_depth_m: float = 0.0,
        stations: Sequence[tuple[float, float, float]] | None = None,
    ) -> None:
        """Register a well with surface coordinates, KB elevation, and optional survey stations."""
        surface_x = float(x)
        surface_y = float(y)
        kb_m = float(elevation)
        td_m = float(total_depth_m)

        if stations is not None and len(stations) > 0:
            md_arr, tvd_arr, x_arr, y_arr = _compute_minimum_curvature_trajectory(
                surface_x, surface_y, kb_m, td_m, stations
            )
            self._wells[well_id] = WellTrajectoryData(
                well_id=well_id,
                surface_x=surface_x,
                surface_y=surface_y,
                kb_m=kb_m,
                total_depth_m=max(td_m, float(md_arr[-1])),
                md=md_arr,
                tvd=tvd_arr,
                x=x_arr,
                y=y_arr,
                is_deviated=True,
            )
        else:
            self._wells[well_id] = WellTrajectoryData(
                well_id=well_id,
                surface_x=surface_x,
                surface_y=surface_y,
                kb_m=kb_m,
                total_depth_m=td_m,
                is_deviated=False,
            )

    def unregister_well(self, well_id: str) -> bool:
        """Remove a well from the registry. Returns True if removed, False otherwise."""
        if well_id in self._wells:
            del self._wells[well_id]
            return True
        return False

    def map_to_well(self, x: float, y: float, max_radius: float = 50.0) -> str | None:
        """Find the nearest registered well within max_radius (Euclidean surface distance)."""
        best_id: str | None = None
        min_dist = float("inf")
        for wid, well in self._wells.items():
            dist = math.hypot(x - well.surface_x, y - well.surface_y)
            if dist <= max_radius and dist < min_dist:
                min_dist = dist
                best_id = wid
        return best_id

    def well_depth_to_map(self, well_id: str, md: float) -> tuple[float, float, float]:
        """Convert well measured depth (MD) to 3D Map coordinates (x, y, tvd)."""
        if well_id not in self._wells:
            raise KeyError(f"Well {well_id} not found in transform hub")
        well = self._wells[well_id]
        md_val = float(md)

        if not well.is_deviated or len(well.md) == 0:
            return (well.surface_x, well.surface_y, md_val)

        x_val = float(np.interp(md_val, well.md, well.x))
        y_val = float(np.interp(md_val, well.md, well.y))
        tvd_val = float(np.interp(md_val, well.md, well.tvd))
        return (x_val, y_val, tvd_val)

    def well_depth_to_tvdss(self, well_id: str, md: float) -> float:
        """Convert well measured depth (MD) to true vertical depth subsea (TVDSS = KB - TVD)."""
        if well_id not in self._wells:
            raise KeyError(f"Well {well_id} not found in transform hub")
        well = self._wells[well_id]
        _, _, tvd = self.well_depth_to_map(well_id, md)
        return float(well.kb_m - tvd)

    def map_to_well_depth(self, well_id: str, tvd: float) -> float:
        """Convert TVD back to MD for a given well."""
        if well_id not in self._wells:
            raise KeyError(f"Well {well_id} not found in transform hub")
        well = self._wells[well_id]
        tvd_val = float(tvd)

        if not well.is_deviated or len(well.tvd) == 0:
            return tvd_val

        md_val = float(np.interp(tvd_val, well.tvd, well.md))
        return md_val

    # -------------------------------------------------------------------------
    # Seismic Grid Geometry & Transformations
    # -------------------------------------------------------------------------

    def configure_seismic_grid(
        self,
        origin: tuple[float, float] = (100.0, 200.0),
        il_step: tuple[float, float] = (10.0, 0.0),
        xl_step: tuple[float, float] = (0.0, 10.0),
        il_min: int = 100,
        xl_min: int = 200,
        velocity: float = 2000.0,
    ) -> None:
        """Configure seismic grid origin, step vectors, index minima, and default velocity."""
        if velocity <= 0.0:
            raise ValueError(f"Velocity must be positive, got {velocity}")
        self._seismic_origin = (float(origin[0]), float(origin[1]))
        self._seismic_il_step = (float(il_step[0]), float(il_step[1]))
        self._seismic_xl_step = (float(xl_step[0]), float(xl_step[1]))
        self._il_min = int(il_min)
        self._xl_min = int(xl_min)
        self._velocity = float(velocity)

    def set_velocity(self, velocity: float) -> None:
        """Set average velocity (m/s) for time-depth conversion."""
        if velocity <= 0.0:
            raise ValueError(f"Velocity must be positive, got {velocity}")
        self._velocity = float(velocity)

    def seismic_to_map(
        self, il: int | float, xl: int | float, twt: float
    ) -> tuple[float, float, float]:
        """Convert seismic (inline, crossline, twt_ms) to Map (x, y, z_m)."""
        dil = float(il) - self._il_min
        dxl = float(xl) - self._xl_min
        x = (
            self._seismic_origin[0]
            + dil * self._seismic_il_step[0]
            + dxl * self._seismic_xl_step[0]
        )
        y = (
            self._seismic_origin[1]
            + dil * self._seismic_il_step[1]
            + dxl * self._seismic_xl_step[1]
        )
        z = (float(twt) / 2000.0) * self._velocity
        return (float(x), float(y), float(z))

    def map_to_seismic(
        self, x: float, y: float, z: float
    ) -> tuple[int, int, float]:
        """Convert Map (x, y, z_m) to seismic (inline, crossline, twt_ms) using full 2x2 matrix inversion."""
        rel_x = float(x) - self._seismic_origin[0]
        rel_y = float(y) - self._seismic_origin[1]

        dx_il, dy_il = self._seismic_il_step
        dx_xl, dy_xl = self._seismic_xl_step
        det = dx_il * dy_xl - dx_xl * dy_il
        if abs(det) < 1e-12:
            raise ValueError(
                f"Degenerate seismic grid step matrix with determinant {det}"
            )

        dil = (dy_xl * rel_x - dx_xl * rel_y) / det
        dxl = (-dy_il * rel_x + dx_il * rel_y) / det

        il = int(round(self._il_min + dil))
        xl = int(round(self._xl_min + dxl))
        twt = (float(z) / self._velocity) * 2000.0
        return (il, xl, float(twt))

    # -------------------------------------------------------------------------
    # Direct Cross-Domain Helpers
    # -------------------------------------------------------------------------

    def well_to_seismic(self, well_id: str, md: float) -> tuple[int, int, float]:
        """Directly map well MD to seismic (inline, crossline, twt)."""
        x, y, tvd = self.well_depth_to_map(well_id, md)
        return self.map_to_seismic(x, y, tvd)

    def seismic_to_well(
        self, il: int | float, xl: int | float, twt: float, max_radius: float = 50.0
    ) -> tuple[str | None, float]:
        """Map seismic (il, xl, twt) to nearest well ID and corresponding MD."""
        x, y, z = self.seismic_to_map(il, xl, twt)
        nearest = self.map_to_well(x, y, max_radius=max_radius)
        if nearest is None:
            return None, 0.0
        md = self.map_to_well_depth(nearest, z)
        return nearest, float(md)
