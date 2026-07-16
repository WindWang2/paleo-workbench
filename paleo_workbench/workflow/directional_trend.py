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

# Default anisotropy: elongate along strike (a > b).
_DEFAULT_A = 1.0
_DEFAULT_B = 0.4
_EPS = 1e-15


def azimuth_to_rad(azimuth_deg: float) -> float:
    """Convert azimuth in degrees (0 = +Y, clockwise toward +X) to radians."""
    return math.radians(float(azimuth_deg) % 360.0)


def rotate_to_uv(
    dx: np.ndarray,
    dy: np.ndarray,
    *,
    azimuth_deg: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Rotate offset vectors into strike-aligned (u, v).

    u: along major axis (strike); v: across strike.
    """
    th = azimuth_to_rad(azimuth_deg)
    # Rotate so that the strike direction (azimuth from north) becomes +u.
    # Pointing north (0,1) at az=0 → u=1, v=0 after: u = dy cos + dx sin ...
    cos_t = math.cos(th)
    sin_t = math.sin(th)
    u = dx * sin_t + dy * cos_t
    v = dx * cos_t - dy * sin_t
    return u, v


def directional_distance(
    u: np.ndarray,
    v: np.ndarray,
    *,
    a: float,
    b: float,
) -> np.ndarray:
    """d = √((u/a)² + (v/b)²) with safe semi-axes."""
    aa = max(float(a), _EPS)
    bb = max(float(b), _EPS)
    return np.sqrt((u / aa) ** 2 + (v / bb) ** 2)


def directional_weights(
    d: np.ndarray,
    *,
    q: np.ndarray | float = 1.0,
    b_i: np.ndarray | float = 1.0,
) -> np.ndarray:
    """w = exp(-d²) · q · b_i."""
    w = np.exp(-(d**2)) * np.asarray(q, dtype=np.float64) * np.asarray(
        b_i, dtype=np.float64
    )
    w = np.where(np.isfinite(w), w, 0.0)
    w = np.maximum(w, 0.0)
    return w


def trend_value_at(
    x0: float,
    y0: float,
    xs: np.ndarray,
    ys: np.ndarray,
    zs: np.ndarray,
    *,
    azimuth_deg: float = 0.0,
    a: float = _DEFAULT_A,
    b: float = _DEFAULT_B,
    q: np.ndarray | None = None,
    b_i: np.ndarray | None = None,
) -> float:
    """Evaluate T(x0, y0) with directional weights over sample points."""
    xs = np.asarray(xs, dtype=np.float64)
    ys = np.asarray(ys, dtype=np.float64)
    zs = np.asarray(zs, dtype=np.float64)
    n = len(zs)
    if n == 0:
        return float("nan")
    q_arr = np.ones(n, dtype=np.float64) if q is None else np.asarray(q, dtype=np.float64)
    b_arr = np.ones(n, dtype=np.float64) if b_i is None else np.asarray(b_i, dtype=np.float64)
    dx = xs - float(x0)
    dy = ys - float(y0)
    u, v = rotate_to_uv(dx, dy, azimuth_deg=azimuth_deg)
    d = directional_distance(u, v, a=a, b=b)
    w = directional_weights(d, q=q_arr, b_i=b_arr)
    sw = float(np.sum(w))
    if sw <= _EPS:
        # Degenerate: fall back to nearest sample.
        i = int(np.argmin(d))
        return float(zs[i])
    return float(np.sum(w * zs) / sw)


def directional_trend_grid(
    xs: np.ndarray,
    ys: np.ndarray,
    zs: np.ndarray,
    grid_x: np.ndarray,
    grid_y: np.ndarray,
    *,
    azimuth_deg: float = 0.0,
    a: float = _DEFAULT_A,
    b: float = _DEFAULT_B,
    q: np.ndarray | None = None,
    b_i: np.ndarray | None = None,
) -> np.ndarray:
    """Evaluate directional trend on a regular grid → shape (len(grid_y), len(grid_x))."""
    xs = np.asarray(xs, dtype=np.float64)
    ys = np.asarray(ys, dtype=np.float64)
    zs = np.asarray(zs, dtype=np.float64)
    grid_x = np.asarray(grid_x, dtype=np.float64)
    grid_y = np.asarray(grid_y, dtype=np.float64)
    n = len(zs)
    if n == 0 or len(grid_x) == 0 or len(grid_y) == 0:
        return np.full((len(grid_y), len(grid_x)), np.nan)

    q_arr = np.ones(n, dtype=np.float64) if q is None else np.asarray(q, dtype=np.float64)
    b_arr = np.ones(n, dtype=np.float64) if b_i is None else np.asarray(b_i, dtype=np.float64)

    # Vectorized over grid cells: (H, W, N)
    X, Y = np.meshgrid(grid_x, grid_y)  # (H, W)
    dx = X[:, :, np.newaxis] - xs  # (H, W, N)
    dy = Y[:, :, np.newaxis] - ys
    u, v = rotate_to_uv(dx, dy, azimuth_deg=azimuth_deg)
    d = directional_distance(u, v, a=a, b=b)
    w = directional_weights(d, q=q_arr, b_i=b_arr)
    sw = np.sum(w, axis=2)
    num = np.sum(w * zs, axis=2)
    out = np.full(sw.shape, np.nan, dtype=np.float64)
    ok = sw > _EPS
    out[ok] = num[ok] / sw[ok]
    # Degenerate cells: nearest sample
    if np.any(~ok):
        nearest = np.argmin(d, axis=2)
        out[~ok] = zs[nearest[~ok]]
    return out


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
