"""Numerical correctness regression tests for the constrained-IDW algorithm.

Locks the fixes for the constrained/plain-IDW algorithm correctness issue group:

- #369 边界井落插值域外：hull 缓冲区死代码 → 最外圈井不被锚定、R² 均值伪造
- #370 断层走廊被填充为观测最小值而非空值
- #382 4096 域单元阈值两侧 line-of-sight 语义不一致
- #399 重复坐标井 anchor last-wins 与 exact-hit first-wins 不一致
- #400 米制常数直接用于度 CRS 工程

Style follows ``tests/test_factor_interpolation_correctness.py`` (tight, justified
tolerances; NaN-aware grid comparisons).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from paleo_workbench.workflow import constrained_idw_adapter as cia
from paleo_workbench.workflow.constrained_idw_adapter import (
    run_constrained_idw,
)


def _pts(*triples: tuple[float, float, float]) -> list[dict]:
    return [{"x": x, "y": y, "value": v} for x, y, v in triples]


def _nearest_cell(gx, gy, x: float, y: float) -> tuple[int, int]:
    col = int(np.argmin(np.abs(np.asarray(gx) - x)))
    row = int(np.argmin(np.abs(np.asarray(gy) - y)))
    return row, col


# --------------------------------------------------------------------------- #
# #369 — boundary wells inside the interpolation domain; R² without faking
# --------------------------------------------------------------------------- #


def test_369_hull_wells_anchored_finite_and_equal_to_observations():
    """Hull (outermost) wells must sit inside the domain and be residual-anchored.

    z = 0.5 + 0.5·x + 0.5·y is an exact plane; every well's nearest grid node
    must be finite and reproduce the observed value (previously the raw hull
    ring excluded the corner wells from anchoring).
    """
    pts = _pts(
        (0.0, 0.0, 0.5),
        (10.0, 0.0, 5.5),
        (0.0, 10.0, 5.5),
        (10.0, 10.0, 10.5),  # hull corners
        (5.0, 0.0, 3.0),
        (0.0, 5.0, 3.0),
        (5.0, 10.0, 8.0),
        (10.0, 5.0, 8.0),  # hull edge midpoints
        (5.0, 5.0, 5.5),  # interior
    )
    result = run_constrained_idw(pts, grid_n=50, power=2.0)
    gz, gx, gy = result["grid_z"], result["grid_x"], result["grid_y"]
    for p in pts:
        row, col = _nearest_cell(gx, gy, p["x"], p["y"])
        assert math.isfinite(float(gz[row, col])), (
            f"well ({p['x']}, {p['y']}) nearest cell is outside the domain"
        )
        assert float(gz[row, col]) == pytest.approx(p["value"], rel=1e-6, abs=1e-4)


def test_369_exact_surface_r_squared_approaches_one():
    """LOO R² on an exactly reproduced plane must be ≈1.0 (was 0.12–0.69)."""
    pts = _pts(
        (0.0, 0.0, 0.5),
        (10.0, 0.0, 5.5),
        (0.0, 10.0, 5.5),
        (10.0, 10.0, 10.5),
        (5.0, 5.0, 5.5),
        (2.0, 2.0, 2.5),
        (8.0, 2.0, 5.5),
    )
    result = run_constrained_idw(pts, grid_n=50, power=2.0)
    assert result["r_squared"] > 0.99
    assert result["r_squared_n_skipped"] == 0
    # Grid max must express the observed max (10.5) — not fall short of it.
    assert result["max"] == pytest.approx(10.5, rel=0.02)
    # and the surface must actually reach it somewhere on the map.
    assert np.nanmax(result["grid_z"]) == pytest.approx(10.5, rel=0.02)


def test_369_boundary_geometry_keeps_promised_3_percent_buffer():
    """The documented 3% outward hull buffer must be measurable on the domain."""
    pts = _pts(
        (0.0, 0.0, 0.5),
        (10.0, 0.0, 5.5),
        (0.0, 10.0, 5.5),
        (10.0, 10.0, 10.5),
        (5.0, 5.0, 5.5),
    )
    from shapely.geometry import Point, Polygon

    wells = cia._build_wells(pts)
    _boundary, exterior = cia._boundary_from_samples(pts, wells)
    poly = Polygon(exterior)
    buf = 0.03 * 10.0
    for w in wells:
        dist = poly.boundary.distance(Point(w.x, w.y))
        assert dist >= buf * 0.99, (
            f"well ({w.x}, {w.y}) not buffered inside the domain (dist {dist})"
        )
    assert poly.contains(Point(5.0, 5.0))
    # Buffered hull bbox extends ≥ buf past the sample bbox on every side.
    xs = [w.x for w in wells]
    ys = [w.y for w in wells]
    assert min(p[0] for p in exterior) <= min(xs) - buf * 0.99
    assert max(p[0] for p in exterior) >= max(xs) + buf * 0.99
    assert min(p[1] for p in exterior) <= min(ys) - buf * 0.99
    assert max(p[1] for p in exterior) >= max(ys) + buf * 0.99


def test_369_loo_fidelity_counts_missing_instead_of_fabricating_mean():
    """Wells whose bilinear window hits nodata are excluded, never mean-faked."""
    xs = np.linspace(0.0, 4.0, 5)
    ys = np.linspace(0.0, 4.0, 5)
    # Exact plane z = x + y → bilinear sampling reproduces every well exactly.
    gx, gy = np.meshgrid(xs, ys)
    grid_z = gx + gy
    grid_z[0, :] = np.nan  # nodata row → well at (0, 0) window is not finite
    wells = cia._build_wells(_pts((0.0, 0.0, 0.0), (2.0, 2.0, 4.0), (4.0, 4.0, 8.0)))
    r2, skipped = cia._leave_one_out_grid_fidelity(grid_z, xs, ys, wells)
    assert skipped == 1
    # Remaining wells are reproduced exactly; the mean-fake path would have
    # yielded r2 ≈ 0 for this configuration.
    assert r2 == pytest.approx(1.0)
