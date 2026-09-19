#!/usr/bin/env python3
"""Oracle for the VIZ-D horizon core (CONV-VIZ V5).

Imports the REAL frozen geoviz reference (geo-viz-engine@08851951,
geoviz_seismic/horizon.py) and freezes fixtures for the C++ port in
libs/seismic_viewer/src/horizon_core.cpp:

  * HorizonParser.parse — numeric scraping, offsets, duplicate last-wins,
    unmatched-points grid;
  * fill_nearest — scipy.ndimage.distance_transform_edt nearest fill with
    max_dist cap (tie-free fixtures; the C++ tie rule is declared);
  * fill_rbf — scipy.interpolate.RBFInterpolator (linear kernel, degree 0,
    k-nearest, smoothing) — asserted within a declared tolerance;
  * extract_along_horizon — single-sample and windowed-RMS extraction with
    NaN grid / clipped indices;
  * horizon_quad_faces — the frozen triangulation.

Run with a numpy/scipy interpreter:

    /opt/miniconda3/bin/python3 tools/oracle/generate_viz_d_horizon_fixtures.py
"""

from __future__ import annotations

import json
import math
import sys
import tempfile
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
ENGINE = REPO_ROOT / "geo-viz-engine" / "packages" / "geoviz_seismic"
sys.path.insert(0, str(ENGINE))

from geoviz_seismic.horizon import (  # noqa: E402
    HorizonAxes,
    HorizonParser,
    extract_along_horizon,
    horizon_quad_faces,
)

OUT = REPO_ROOT / "tests" / "cpp" / "viz_d" / "fixtures"
OUT.mkdir(parents=True, exist_ok=True)

ILINES = np.arange(100, 108, dtype=np.int64)  # 8 inlines
XLINES = np.arange(500, 506, dtype=np.int64)  # 6 crosslines


def _num(value):
    value = float(value)
    if math.isnan(value):
        return "nan"
    if math.isinf(value):
        return "inf" if value > 0 else "-inf"
    return value


def _nums(values) -> list:
    return [_num(v) for v in np.asarray(values, dtype=np.float64).reshape(-1)]


def _axes() -> HorizonAxes:
    return HorizonAxes(ilines=ILINES, xlines=XLINES, nI=len(ILINES), nX=len(XLINES))


def parse_cases() -> dict:
    rng = np.random.default_rng(11)
    # Tie-free sampling: pick distinct (i, j) cells with values.
    cells = [(int(i), int(j)) for i in range(6) for j in range(4)]
    lines = []
    for i, j in cells:
        lines.append(f"{ILINES[i]}\t{XLINES[j]}\t{1100.0 + 7.0 * i - 3.0 * j:.3f}")
    cases = {}

    def run(text: str, case_id: str, **kwargs):
        with tempfile.NamedTemporaryFile("w", suffix=".dat", delete=False) as handle:
            handle.write(text)
            path = handle.name
        parser = HorizonParser(path, **kwargs)
        grid = parser.parse(_axes())
        Path(path).unlink()
        cases[case_id] = {
            "text": text,
            "kwargs": {k: float(v) if not isinstance(v, (int, str)) else v
                       for k, v in kwargs.items()},
            "grid": _nums(grid),
            "shape": [grid.shape[0], grid.shape[1]],
        }

    run("\n".join(lines) + "\n", "basic")
    # Duplicate (il, xl): last wins (2600 overwrites 1500).
    run("\n".join(lines + [f"{ILINES[0]}\t{XLINES[0]}\t2600.0"]) + "\n", "duplicate_last_wins")
    # Offsets shift the file's line numbers onto the axes.
    run("\n".join(f"{il - 10}\t{xl + 5}\t{v}" for il, xl, v in
                  ((ILINES[i], XLINES[j], 1100.0 + 7.0 * i - 3.0 * j)
                   for i in range(6) for j in range(4))) + "\n",
        "offsets", iline_offset=10, xline_offset=-5)
    # Scale on the third column.
    run("\n".join(f"{ILINES[i]}\t{XLINES[j]}\t{1.0 + 0.01 * i + 0.02 * j}"
                  for i in range(6) for j in range(4)) + "\n",
        "scaled", scale=1000.0)
    # No point matches the axes (all out of range) -> all-NaN grid.
    run("999\t999\t1234.5\n888\t777\t4321.0\n", "zero_matched")
    # Whitespace-separated (not tabs), extra columns, comments, floats as il.
    run("# a horizon\n" + "\n".join(
        f"{float(ILINES[i])} {XLINES[j]} {1100.0 + i - j:.2f} extra"
        for i in range(6) for j in range(4)) + "\n", "loose_text")
    # Exponent notation and trailing-dot mantissas: the regex takes
    # `1.05e2` as one number; `1.e3` scans as `1` (dot tail has no digits,
    # the exponent does not glue on); `100.5.` scans as `100.5` then `.`
    # dead-ends.
    run("\n".join(f"{ILINES[i]} {XLINES[j]} {1.05e2:.6g}"
                  for i in range(3) for j in range(3))
        + "\n100 500 1.e3 42\n100.5. 501 7.25\n", "exponent_and_trailing_dot")
    return cases


def fill_cases() -> dict:
    rng = np.random.default_rng(23)
    # RBF cases keep valid-node counts <= `neighbors` (24): both engines fit
    # ALL valid nodes, so no KDTree tie-order ambiguity can pick different
    # (equidistant) neighbour sets — the ledger declares that grids with more
    # valid nodes than `neighbors` are outside bit-parity scope.
    base = 1200.0 + rng.normal(0, 8.0, size=(8, 6))
    small = 1200.0 + rng.normal(0, 8.0, size=(5, 5))
    cases = {}

    def add(case_id, grid, max_dist, kind, **kw):
        if kind == "nearest":
            out = HorizonParser("unused").fill_nearest(grid, max_dist=max_dist)
            tol = 0.0
        else:
            out = HorizonParser("unused").fill_rbf(grid, max_dist=max_dist, **kw)
            tol = 1.0e-6
        cases[case_id] = {
            "kind": kind,
            "grid": _nums(grid),
            "shape": [grid.shape[0], grid.shape[1]],
            "max_dist": max_dist,
            "kwargs": {k: float(v) for k, v in kw.items()},
            "output": _nums(out),
            "tolerance": tol,
        }

    g = base.copy()
    g[0, :] = np.nan
    g[:, 0] = np.nan
    add("edge_gaps_nearest", g, 0, "nearest")
    g2 = base.copy()
    g2[3, 3] = np.nan
    g2[6, 2] = np.nan
    add("interior_gaps_nearest", g2, 0, "nearest")
    g3 = base.copy()
    g3[2:, 2:] = np.nan
    add("corner_block_capped", g3, 2.5, "nearest")
    # RBF family: small grids, all-valid fits.
    r1 = small.copy()
    r1[2:, 2:] = np.nan  # 16 valid nodes, 9 gaps
    add("rbf_corner_block", r1, 0, "rbf", neighbors=24, smoothing=0.0)
    add("rbf_corner_block_capped", r1, 1.5, "rbf", neighbors=24, smoothing=0.0)
    r2 = small.copy()
    r2[2, 2] = np.nan
    add("rbf_single_gap", r2, 0, "rbf", neighbors=24, smoothing=0.0)
    add("rbf_single_gap_smoothing", r2, 0, "rbf", neighbors=24, smoothing=0.5)
    r3 = small.copy()
    r3[0, :] = np.nan  # 20 valid nodes
    add("rbf_edge_row", r3, 0, "rbf", neighbors=24, smoothing=0.0)
    add("no_gaps_nearest", base, 0, "nearest")
    all_nan = np.full((4, 3), np.nan)
    add("all_nan_nearest", all_nan, 0, "nearest")
    return cases


def extract_cases() -> dict:
    rng = np.random.default_rng(31)
    n_i, n_x, n_s = len(ILINES), len(XLINES), 32
    volume = rng.normal(0, 1, size=(n_i, n_x, n_s)).astype(np.float32)
    t0, dt = 100.0, 4.0
    times = t0 + dt * np.arange(n_s)
    cases = {}

    def add(case_id, grid, window):
        out = extract_along_horizon(volume, grid, dt_ms=dt, t0_ms=t0, window=window)
        cases[case_id] = {
            "volume": _nums(volume),
            "shape": [n_i, n_x, n_s],
            "grid": _nums(grid),
            "dt_ms": dt,
            "t0_ms": t0,
            "window": window,
            "output": _nums(out),
        }

    grid = np.repeat(times[8][None, None], n_i, 0).repeat(n_x, 1) + 0.0
    add("flat_window0", grid, 0)
    add("flat_window3", grid, 3)
    # Horizon times off both ends of the volume (clipped indices).
    grid2 = 1200.0 + 6.0 * np.arange(n_i)[:, None] - 5.0 * np.arange(n_x)[None, :]
    add("sloped_out_of_range", grid2, 2)
    # NaN gaps propagate.
    grid3 = grid2.copy()
    grid3[2, 2] = np.nan
    grid3[5, :] = np.nan
    add("nan_gaps", grid3, 3)
    return cases


def faces_cases() -> dict:
    faces = horizon_quad_faces(5, 4)
    empty = horizon_quad_faces(1, 7)
    return {
        "faces_5x4": np.asarray(faces).reshape(-1).tolist(),
        "faces_count": int(np.asarray(faces).shape[0]),
        "empty_1x7": int(np.asarray(empty).size),
    }


def main() -> None:
    fixture = {
        "generator": "tools/oracle/generate_viz_d_horizon_fixtures.py",
        "engine": "geo-viz-engine@08851951",
        "ilines": ILINES.tolist(),
        "xlines": XLINES.tolist(),
        "parse": parse_cases(),
        "fill": fill_cases(),
        "extract": extract_cases(),
        "faces": faces_cases(),
    }
    path = OUT / "viz_d_horizon_oracle.json"
    path.write_text(json.dumps(fixture, indent=1), encoding="utf-8")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
