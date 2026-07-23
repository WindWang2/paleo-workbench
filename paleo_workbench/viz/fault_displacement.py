"""FaultDisplacement: Fault throw displacement vector offset engine for 3D horizon meshes."""

from __future__ import annotations

import math
import numpy as np


class FaultDisplacement:
    """Computes vertical and lateral fault throw displacement for 3D horizon surface vertices."""

    def apply_fault_throw(
        self,
        vertices: np.ndarray,
        fault_line_x: float,
        throw_z: float,
        throw_x: float = 0.0,
        dip_deg: float = 60.0,
    ) -> np.ndarray:
        """Displace hanging-wall vertices (x >= fault_line_x) according to fault throw vectors and dip angle."""
        if vertices.ndim != 2 or vertices.shape[1] != 3:
            raise ValueError("Vertices array must have shape (N, 3)")

        res = vertices.copy()
        hanging_wall = res[:, 0] >= fault_line_x

        # If throw_x is not explicitly given, derive lateral offset from dip angle
        if throw_x == 0.0 and dip_deg > 0 and dip_deg < 90:
            rad = math.radians(dip_deg)
            effective_throw_x = abs(throw_z) / math.tan(rad)
        else:
            effective_throw_x = throw_x

        res[hanging_wall, 0] += effective_throw_x
        res[hanging_wall, 2] += throw_z

        return res
