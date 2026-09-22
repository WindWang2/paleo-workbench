"""Directional weighted trend surface (ISS-ALG-02).

Product formulas:
  Local frame: rotate (x - x0, y - y0) by azimuth θ (degrees from +Y / north
  toward +X) into (u, v) where u is along-strike and v is across-strike.

  Directional distance:
      d_i(θ) = √( (u_i / a)² + (v_i / b)² )

  Weights:
      w_i = exp(-d_i²) · q_i · b_i

  Trend surface:
      T(x, y) = Σ w_i z_i / Σ w_i
"""

from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np

from geoviz import (
    azimuth_to_rad,
    directional_distance,
    directional_trend_grid,
    directional_weights,
    rotate_to_uv,
    trend_value_at,
)

# Default anisotropy: elongate along strike (a > b).
_DEFAULT_A = 1.0
_DEFAULT_B = 0.4
def resolve_anisotropy_params(
    direction_params: Sequence[dict[str, Any]] | None,
) -> tuple[float, float, float]:
    """Pick azimuth / a / b from the first active direction-line param dict."""
    if not direction_params:
        return 0.0, _DEFAULT_A, _DEFAULT_B
    p0 = direction_params[0]
    az = float(p0.get("azimuth_deg") if p0.get("azimuth_deg") is not None else 0.0)
    a = float(p0.get("semi_major") if p0.get("semi_major") is not None else _DEFAULT_A)
    b = float(p0.get("semi_minor") if p0.get("semi_minor") is not None else _DEFAULT_B)
    if a <= 0:
        a = _DEFAULT_A
    if b <= 0:
        b = _DEFAULT_B
    return az, a, b


def extract_xy_z_weights(
    sample_points: list[dict[str, Any]] | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return (x, y, z, q, b_i) arrays from sample_points / WellTable export dicts."""
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []
    qs: list[float] = []
    bs: list[float] = []
    for pt in sample_points or []:
        if not isinstance(pt, dict):
            continue
        try:
            if "x" in pt and "y" in pt:
                x = float(pt["x"])
                y = float(pt["y"])
            elif "lng" in pt and "lat" in pt:
                x = float(pt["lng"])
                y = float(pt["lat"])
            else:
                continue
            z = float(pt.get("value", pt.get("z", pt.get("v"))))
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
            continue
        # Skip QC-flagged points unless explicitly kept.
        flag = str(pt.get("qc_flag") or "ok")
        if flag not in {"ok", ""}:
            continue
        try:
            q = float(pt.get("q", 1.0))
        except (TypeError, ValueError):
            q = 1.0
        try:
            bi = float(pt.get("b_i", 1.0))
        except (TypeError, ValueError):
            bi = 1.0
        xs.append(x)
        ys.append(y)
        zs.append(z)
        qs.append(max(0.0, q))
        bs.append(max(0.0, bi))
    return (
        np.asarray(xs, dtype=np.float64),
        np.asarray(ys, dtype=np.float64),
        np.asarray(zs, dtype=np.float64),
        np.asarray(qs, dtype=np.float64),
        np.asarray(bs, dtype=np.float64),
    )
