"""FaultDisplacement: Fault throw displacement vector offset engine for 3D horizon meshes."""

from __future__ import annotations

from dataclasses import dataclass
import math
import numpy as np


@dataclass
class FaultSpec:
    """Encapsulates 3D fault plane geometry and throw magnitude parameters."""
    fault_line_x: float
    throw_z: float
    throw_x: float = 0.0
    dip_deg: float = 60.0
    strike_deg: float = 0.0
    decay_radius: float = 0.0


class FaultDisplacement:
    """Computes vertical and lateral fault throw displacement for 3D horizon surface vertices."""

    def apply_fault_throw(
        self,
        vertices: np.ndarray,
        fault_line_x: float,
        throw_z: float,
        throw_x: float = 0.0,
        dip_deg: float = 60.0,
        strike_deg: float = 0.0,
        decay_radius: float = 0.0,
        spec: FaultSpec | None = None,
    ) -> np.ndarray:
        """Displace hanging-wall vertices according to fault plane vectors and distance decay."""
        if spec is not None:
            fault_line_x = spec.fault_line_x
            throw_z = spec.throw_z
            throw_x = spec.throw_x
            dip_deg = spec.dip_deg
            strike_deg = spec.strike_deg
            decay_radius = spec.decay_radius

        if vertices.ndim != 2 or vertices.shape[1] != 3:
            raise ValueError("Vertices array must have shape (N, 3)")

        res = vertices.copy()

        # Compute fault normal distance accounting for strike angle
        rad_strike = math.radians(strike_deg)
        nx = math.cos(rad_strike)
        ny = math.sin(rad_strike)

        # Distance to fault plane normal line
        dist_normal = nx * (res[:, 0] - fault_line_x) + ny * res[:, 1]
        hanging_wall = dist_normal >= 0

        if throw_x == 0.0 and dip_deg > 0 and dip_deg < 90:
            rad_dip = math.radians(dip_deg)
            # Heave must carry the throw's SIGN (#846): a reverse fault
            # (throw_z < 0) displaces the hanging wall in the OPPOSITE
            # horizontal direction from a normal fault of the same magnitude
            # — abs() made both point the same way.
            effective_throw_x = throw_z / math.tan(rad_dip)
        else:
            effective_throw_x = throw_x

        if decay_radius > 0.0:
            dist = np.abs(dist_normal)
            weights = np.exp(-((dist / (decay_radius * 0.5)) ** 2))
            weights[~hanging_wall] = 0.0
            res[:, 0] += effective_throw_x * nx * weights
            res[:, 1] += effective_throw_x * ny * weights
            res[:, 2] += throw_z * weights
        else:
            res[hanging_wall, 0] += effective_throw_x * nx
            res[hanging_wall, 1] += effective_throw_x * ny
            res[hanging_wall, 2] += throw_z

        return res
