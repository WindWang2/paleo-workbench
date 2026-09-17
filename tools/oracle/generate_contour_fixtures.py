#!/usr/bin/env python3
"""Oracle fixture generator for the C++ contouring kernel (M6).

Imports the REAL implementation (paleo_workbench.mapping.geological_pipeline.
contouring) and freezes its outputs to JSON so the C++ port in
libs/mapping_kernel can be verified sample-exactly. Regenerate with:

    python3 tools/oracle/generate_contour_fixtures.py
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from paleo_workbench.mapping.geological_pipeline import contouring as py  # noqa: E402

OUT = REPO_ROOT / "libs" / "mapping_kernel" / "mapping_kernel_tests" / "fixtures"


def grid_fields() -> dict[str, dict]:
    rng = np.random.default_rng(20260917)
    x = np.linspace(0.0, 10.0, 21)
    y = np.linspace(0.0, 8.0, 17)
    xx, yy = np.meshgrid(x, y)
    smooth = np.sin(xx * 0.8) * np.cos(yy * 0.6) + 0.05 * xx

    saddle = np.array(
        [[1.0, 2.0, 3.0, 4.0], [2.0, 1.0, 4.0, 3.0], [3.0, 4.0, 1.0, 2.0],
         [4.0, 3.0, 2.0, 1.0]],
        dtype=float,
    )

    holes = smooth.copy()
    holes[5:9, 6:12] = np.nan
    holes[0, 0] = np.nan

    noisy = smooth + rng.normal(0.0, 0.15, smooth.shape)
    flat = np.full((6, 6), 2.5)

    return {
        "smooth": {"x": x, "y": y, "z": smooth},
        "saddle": {"x": np.arange(4.0), "y": np.arange(4.0), "z": saddle},
        "holes": {"x": x, "y": y, "z": holes},
        "noisy": {"x": x, "y": y, "z": noisy},
        "flat": {"x": np.arange(6.0), "y": np.arange(6.0), "z": flat},
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fields = grid_fields()

    cases = []
    for name, g in fields.items():
        z = g["z"]
        finite = z[np.isfinite(z)]
        vmin, vmax = float(finite.min()), float(finite.max())
        levels = py.calculate_nice_contour_levels(vmin, vmax, 7)
        quant = py.calculate_quantile_contour_levels(z)
        for level in levels + [vmin + 0.37 * (vmax - vmin)]:
            for tol, iters in ((0.0, 0), (0.15, 0), (0.0, 1), (0.1, 2)):
                polys = py._marching_squares_pure_python(
                    z, g["x"], g["y"], float(level),
                    simplify_tol=tol, smooth_iterations=iters,
                )
                cases.append({
                    "grid": name,
                    "level": float(level),
                    "simplify_tol": tol,
                    "smooth_iterations": iters,
                    "polylines": [
                        [[float(p[0]), float(p[1])] for p in poly]
                        for poly in polys
                    ],
                })
        cases.append({
            "grid": name,
            "quantile_levels": quant,
            "nice_levels": levels,
            "vmin": vmin,
            "vmax": vmax,
        })

    # Direct unit oracles for the point utilities.
    points = [[float(k) for k in row]
              for row in (np.linspace(0, 10, 41).reshape(-1, 1)
                          * np.array([1.0, 0.3])).tolist()]
    points.append([10.0, 5.0])
    units = {
        "dp": {
            "points": points,
            "tolerance": 0.5,
            "result": [[float(p[0]), float(p[1])]
                       for p in py.douglas_peucker_2d(points, 0.5)],
        },
        "dp_open_zero_tolerance": {
            "points": [[0.0, 0.0], [1.0, 1.0]],
            "tolerance": 0.0,
            "result": [[0.0, 0.0], [1.0, 1.0]],
        },
        "chaikin_open": {
            "points": [[0.0, 0.0], [1.0, 2.0], [3.0, 1.0]],
            "iterations": 2,
            "result": [[float(p[0]), float(p[1])]
                       for p in py.chaikin_smooth(
                           [[0.0, 0.0], [1.0, 2.0], [3.0, 1.0]], 2)],
        },
        "chaikin_closed": {
            "points": [[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 2.0],
                       [0.0, 0.0]],
            "iterations": 1,
            "result": [[float(p[0]), float(p[1])]
                       for p in py.chaikin_smooth(
                           [[0.0, 0.0], [2.0, 0.0], [2.0, 2.0],
                            [0.0, 2.0], [0.0, 0.0]], 1)],
        },
        "length": {
            "points": [[0.0, 0.0], [3.0, 4.0], [3.0, 10.0]],
            "result": py.calculate_polyline_length(
                [[0.0, 0.0], [3.0, 4.0], [3.0, 10.0]]),
        },
        "nice_edge": {
            "vmin": 0.03, "vmax": 0.097,
            "result": py.calculate_nice_contour_levels(0.03, 0.097, 7),
        },
        "nice_degenerate": {
            "vmin": 2.0, "vmax": 2.0,
            "result": py.calculate_nice_contour_levels(2.0, 2.0, 7),
        },
    }

    doc = {
        "grids": {name: {"x": g["x"].tolist(), "y": g["y"].tolist(),
                         "z": [[None if math.isnan(v) else v for v in row]
                               for row in g["z"].tolist()]}
                  for name, g in fields.items()},
        "cases": cases,
        "units": units,
    }
    target = OUT / "contouring_oracle.json"
    target.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {target} ({target.stat().st_size} bytes, "
          f"{sum(1 for c in cases if 'polylines' in c)} contour cases)")


if __name__ == "__main__":
    main()
