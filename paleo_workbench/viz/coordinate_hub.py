"""CoordinateTransformHub: Unified Coordinate Transformation Engine (Features F17 & F18).

Provides bidirectional conversions across:
- 2D/3D Map CRS (X, Y, Z / TVD)
- Well Trajectory & Depth Datums (MD, TVD, TVDSS, nearest well spatial query)
- Seismic Grid Volumes (Inline, Crossline, TWT in milliseconds)
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np


@dataclass(frozen=True)
class TimeDepthCalibration:
    """Explicit, provenance-carrying time-depth relationship for one well.

    A piecewise-linear checkshot-style calibration over strictly increasing
    (MD m, TWT ms) pairs. Deliberately narrow:

    * conversions are interpolated ONLY inside the calibrated range — no
      extrapolation, no constant-velocity fallback (out-of-range → None);
    * ``provenance`` records where the relationship came from
      (``checkshot:<asset>``, ``td-table:<path>``, …) so any depth↔time
      routing can state its authority.
    """

    well_id: str
    pairs: tuple[tuple[float, float], ...]
    provenance: str

    def __post_init__(self) -> None:
        if len(self.pairs) < 2:
            raise ValueError("time-depth calibration needs at least two pairs")
        for (md0, twt0), (md1, twt1) in zip(self.pairs, self.pairs[1:]):
            if not md1 > md0:
                raise ValueError(f"calibration MD values must strictly increase ({md0} → {md1})")
            if not twt1 > twt0:
                raise ValueError(
                    f"calibration TWT values must strictly increase ({twt0} → {twt1})"
                )

    @classmethod
    def from_pairs(
        cls,
        well_id: str,
        pairs: Sequence[tuple[float, float]],
        *,
        provenance: str,
    ) -> "TimeDepthCalibration":
        cleaned = tuple(
            (float(md), float(twt)) for md, twt in sorted(pairs, key=lambda p: float(p[0]))
        )
        return cls(well_id=str(well_id), pairs=cleaned, provenance=str(provenance))

    def md_to_twt(self, md: float) -> float | None:
        md_val = float(md)
        if md_val < self.pairs[0][0] or md_val > self.pairs[-1][0]:
            return None
        for (md0, twt0), (md1, twt1) in zip(self.pairs, self.pairs[1:]):
            if md0 <= md_val <= md1:
                if md1 == md0:
                    return float(twt0)
                frac = (md_val - md0) / (md1 - md0)
                return float(twt0 + frac * (twt1 - twt0))
        return float(self.pairs[-1][1])

    def twt_to_md(self, twt: float) -> float | None:
        twt_val = float(twt)
        if twt_val < self.pairs[0][1] or twt_val > self.pairs[-1][1]:
            return None
        for (md0, twt0), (md1, twt1) in zip(self.pairs, self.pairs[1:]):
            if twt0 <= twt_val <= twt1:
                if twt1 == twt0:
                    return float(md0)
                frac = (twt_val - twt0) / (twt1 - twt0)
                return float(md0 + frac * (md1 - md0))
        return float(self.pairs[-1][0])


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
        self._lock = threading.RLock()
        self._wells: dict[str, WellTrajectoryData] = {}
        self._calibrations: dict[str, TimeDepthCalibration] = {}
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
            data = WellTrajectoryData(
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
            data = WellTrajectoryData(
                well_id=well_id,
                surface_x=surface_x,
                surface_y=surface_y,
                kb_m=kb_m,
                total_depth_m=td_m,
                is_deviated=False,
            )
        with self._lock:
            self._wells[well_id] = data

    def unregister_well(self, well_id: str) -> bool:
        """Remove a well from the registry. Returns True if removed, False otherwise."""
        with self._lock:
            if well_id in self._wells:
                del self._wells[well_id]
                return True
            return False

    def clear_all_wells(self) -> int:
        """Remove every registered well (project switch/close). Returns the count removed."""
        with self._lock:
            removed = len(self._wells)
            self._wells.clear()
            self._calibrations.clear()
            return removed

    # -------------------------------------------------------------------------
    # Time-Depth Calibration (fail-closed)
    # -------------------------------------------------------------------------

    def set_time_depth_calibration(self, calibration: TimeDepthCalibration) -> None:
        """Attach an explicit time-depth relationship to its well."""
        if not getattr(calibration, "well_id", ""):
            raise ValueError("calibration must name its well")
        with self._lock:
            self._calibrations[str(calibration.well_id)] = calibration

    def clear_time_depth_calibration(self, well_id: str) -> bool:
        with self._lock:
            return self._calibrations.pop(str(well_id), None) is not None

    def time_depth_calibration(self, well_id: str) -> TimeDepthCalibration | None:
        with self._lock:
            return self._calibrations.get(str(well_id))

    def well_md_to_twt(self, well_id: str, md: float) -> float | None:
        """MD (m) → TWT (ms) through the well's calibration; None without one.

        This is the fail-closed conversion: no calibration, no answer. It
        never falls back to the average velocity — depth==time guessing is
        exactly what the calibration gate exists to prevent.
        """
        cal = self.time_depth_calibration(well_id)
        if cal is None:
            return None
        return cal.md_to_twt(md)

    def twt_to_well_md(self, well_id: str, twt: float) -> float | None:
        """TWT (ms) → MD (m) through the well's calibration; None without one."""
        cal = self.time_depth_calibration(well_id)
        if cal is None:
            return None
        return cal.twt_to_md(twt)

    def well_md_to_seismic_cursor(
        self, well_id: str, md: float
    ) -> tuple[int, int, float] | None:
        """Well MD → (inline, crossline, twt) with a calibration-authoritative time.

        The (IL, XL) part is pure geometry (trajectory + bin grid) and always
        available; the TWT part exists only through the well's calibration,
        so the whole conversion is None when the calibration is missing or
        the MD is outside the calibrated range.
        """
        twt = self.well_md_to_twt(well_id, md)
        if twt is None:
            return None
        x, y, _tvd = self.well_depth_to_map(well_id, md)
        il, xl, _ = self.map_to_seismic(x, y, 0.0)
        return (il, xl, float(twt))

    def registered_well_ids(self) -> tuple[str, ...]:
        """Snapshot of currently registered well ids (diagnostics/tests)."""
        with self._lock:
            return tuple(self._wells.keys())

    def map_to_well(self, x: float, y: float, max_radius: float = 50.0) -> str | None:
        """Find the nearest registered well within max_radius (Euclidean surface distance)."""
        best_id: str | None = None
        min_dist = float("inf")
        with self._lock:
            wells_snapshot = list(self._wells.items())
        for wid, well in wells_snapshot:
            dist = math.hypot(x - well.surface_x, y - well.surface_y)
            if dist <= max_radius and dist < min_dist:
                min_dist = dist
                best_id = wid
        return best_id

    def well_depth_to_map(self, well_id: str, md: float) -> tuple[float, float, float]:
        """Convert well measured depth (MD) to 3D Map coordinates (x, y, tvd)."""
        with self._lock:
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
        with self._lock:
            if well_id not in self._wells:
                raise KeyError(f"Well {well_id} not found in transform hub")
            well = self._wells[well_id]
        _, _, tvd = self.well_depth_to_map(well_id, md)
        return float(well.kb_m - tvd)

    def map_to_well_depth(self, well_id: str, tvd: float) -> float:
        """Convert TVD back to MD along the well's surveyed trajectory (#1037).

        Horizontal and undulating trajectories (incidence > 90°) cross one
        TVD several times. The trajectory is walked segment-by-segment in
        survey (MD) order and the FIRST crossing is returned — the depth
        first reached while drilling. Use :meth:`map_to_well_depth_all` when
        the caller must disambiguate multi-crossing levels. TVD outside the
        surveyed range clamps onto the trajectory endpoint (the MD of the
        TVD minimum/maximum), matching the legacy endpoint behaviour.
        """
        crossings = self.map_to_well_depth_all(well_id, tvd)
        if not crossings:
            return float(tvd)
        return crossings[0]

    def map_to_well_depth_all(self, well_id: str, tvd: float) -> list[float]:
        """Every MD at which the trajectory crosses *tvd*, in MD order.

        Piecewise-linear segment model over the survey stations: each segment
        whose TVD interval spans the target contributes one linearly
        interpolated MD. ``np.interp`` cannot be used here — it requires
        strictly increasing TVD and silently corrupts on non-monotonic
        trajectories (#1037).
        """
        with self._lock:
            if well_id not in self._wells:
                raise KeyError(f"Well {well_id} not found in transform hub")
            well = self._wells[well_id]
        tvd_val = float(tvd)

        if not well.is_deviated or len(well.tvd) == 0:
            return [tvd_val]

        md_arr = well.md
        tvd_arr = well.tvd
        crossings: list[float] = []
        for i in range(len(md_arr) - 1):
            md0, md1 = float(md_arr[i]), float(md_arr[i + 1])
            tvd0, tvd1 = float(tvd_arr[i]), float(tvd_arr[i + 1])
            if md1 <= md0:
                continue
            lo, hi = (tvd0, tvd1) if tvd0 <= tvd1 else (tvd1, tvd0)
            if lo <= tvd_val <= hi:
                span = tvd1 - tvd0
                if abs(span) < 1e-12:
                    # Constant-TVD segment (lateral): the whole segment sits
                    # at the target — report its entry MD once.
                    if not crossings or crossings[-1] < md0:
                        crossings.append(md0)
                else:
                    fraction = (tvd_val - tvd0) / span
                    fraction = min(1.0, max(0.0, fraction))
                    candidate = md0 + fraction * (md1 - md0)
                    if not crossings or candidate - crossings[-1] > 1e-9:
                        crossings.append(candidate)

        if not crossings:
            # Out of the surveyed TVD range: clamp onto the extremal station
            # (deepest crossing available), mirroring np.interp's endpoint
            # clamping instead of extrapolating fabricating depth.
            extremal_index = int(np.argmax(tvd_arr)) if tvd_val > float(
                np.max(tvd_arr)
            ) else int(np.argmin(tvd_arr))
            crossings.append(float(md_arr[extremal_index]))
        return crossings

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
