#!/usr/bin/env python3
"""Oracle fixture generator for nearest-neighbor class grids (M6).

Imports the REAL implementation
(paleo_workbench.mapping.well_prediction_surface.nearest_neighbor_class_grid)
and freezes outputs so the C++ port can be verified. Inclusive PIP clip uses
geometry_planar.point_in_ring_scalar_inclusive — not the interpolator
even-odd mask. Regenerate with:

    python3 tools/oracle/generate_class_grid_fixtures.py
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import _legacy_reference

_legacy_reference.ensure_legacy_reference()  # archived-reference shim

from paleo_workbench.mapping.geometry_planar import (  # noqa: E402
    point_in_ring_scalar,
    point_in_ring_scalar_inclusive,
)
from paleo_workbench.mapping.well_prediction_surface import (  # noqa: E402
    WellFaciesPoint,
    nearest_neighbor_class_grid,
)

OUT = (
    REPO_ROOT
    / "libs"
    / "mapping_kernel"
    / "mapping_kernel_tests"
    / "fixtures"
)


def _grid_json(arr: np.ndarray) -> list:
    out = []
    for row in np.asarray(arr):
        out.append([
            None if not math.isfinite(float(v)) else float(v) for v in row
        ])
    return out


def _axis_json(arr: np.ndarray) -> list[float]:
    return [float(v) for v in np.asarray(arr, dtype=np.float64)]


def _pts(*triples: tuple[float, float, str]) -> list[WellFaciesPoint]:
    return [WellFaciesPoint(x=x, y=y, facies=f) for x, y, f in triples]


def _case(cid: str, points, extent, grid_n, clip=None) -> dict:
    z, gx, gy, names = nearest_neighbor_class_grid(
        points, extent=extent, grid_n=grid_n, clip_ring=clip,
    )
    return {
        "id": cid,
        "points": [[p.x, p.y, p.facies] for p in points],
        "extent": list(extent),
        "grid_n": int(grid_n),
        "clip_ring": None if clip is None else [list(pt) for pt in clip],
        "grid_x": _axis_json(gx),
        "grid_y": _axis_json(gy),
        "grid_z": _grid_json(z),
        "facies_names": list(names),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)]
    # A point on the right edge is inside inclusive PIP, outside even-odd
    # (x < crossing_x fails when x == edge).
    edge_pt = (10.0, 5.0)

    cases = [
        _case("two_class_split",
              _pts((0.0, 0.0, "三角洲"), (10.0, 0.0, "滨浅湖")),
              (-1.0, -1.0, 11.0, 1.0), 20),
        _case("one_point",
              _pts((5.0, 5.0, "均一")),
              (0.0, 0.0, 10.0, 10.0), 8),
        _case("coincident_first_wins",
              _pts((1.0, 1.0, "A"), (1.0, 1.0, "B"), (8.0, 8.0, "C")),
              (0.0, 0.0, 10.0, 10.0), 6),
        _case("midpoint_tie",
              _pts((0.0, 0.0, "left"), (10.0, 0.0, "right")),
              (0.0, -1.0, 10.0, 1.0), 11),
        _case("grid_n_clamp",
              _pts((0.0, 0.0, "p")),
              (0.0, 0.0, 1.0, 1.0), 1),
        _case("first_seen_order",
              _pts((0.0, 0.0, "C"), (5.0, 0.0, "A"), (10.0, 0.0, "B"),
                   (0.0, 5.0, "A")),
              (-1.0, -1.0, 11.0, 6.0), 9),
        _case("clip_square",
              _pts((2.0, 2.0, "内"), (12.0, 12.0, "外")),
              (-2.0, -2.0, 14.0, 14.0), 10, clip=square),
        _case("three_classes",
              _pts((0.0, 0.0, "a"), (10.0, 0.0, "b"), (5.0, 8.0, "c")),
              (-1.0, -1.0, 11.0, 9.0), 12),
        _case("nonsquare_extent",
              _pts((0.0, 0.0, "W"), (4.0, 20.0, "E")),
              (-1.0, -1.0, 5.0, 21.0), 8),
        _case("default_grid_n",
              _pts((0.0, 0.0, "x"), (1.0, 1.0, "y")),
              (0.0, 0.0, 1.0, 1.0), 80),
    ]

    inclusive = point_in_ring_scalar_inclusive(*edge_pt, square)
    even_odd = point_in_ring_scalar(*edge_pt, square)
    pip = {
        "edge_point": list(edge_pt),
        "ring": [list(p) for p in square],
        "inclusive": bool(inclusive),
        "even_odd": bool(even_odd),
    }

    empty_error = "point-to-surface needs at least one well facies point"

    doc = {
        "cases": cases,
        "pip": pip,
        "empty_error": empty_error,
    }
    target = OUT / "class_grid_oracle.json"
    target.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {target} ({target.stat().st_size} bytes, "
          f"{len(cases)} class-grid cases; "
          f"inclusive={inclusive} even_odd={even_odd})")


if __name__ == "__main__":
    main()
