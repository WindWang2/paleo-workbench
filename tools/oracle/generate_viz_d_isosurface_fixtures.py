#!/usr/bin/env python3
"""Oracle for the VIZ-D isosurface core (CONV-VIZ V5).

Loads the FROZEN native marching-tetrahedra implementation
(native/seismic_3d_core::marching_cubes_3d, pybind "0.2.17a0" — the exact
extractor the workbench injects into geoviz via
isosurface.set_isosurface_extractor) from the sibling main worktree's built
extension (read-only) and freezes (verts, faces) pairs for the C++ port in
libs/seismic_viewer/src/isosurface_core.cpp.

Run with the interpreter that can import the built extension:

    /opt/miniconda3/bin/python3 tools/oracle/generate_viz_d_isosurface_fixtures.py
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
# Prefer the sibling main worktree's built extension; fall back to the
# module built from THIS worktree's frozen source into build/viz-d (same
# gitlink, same algorithm).
MAIN_NATIVE = (REPO_ROOT.parent / "main" / "native" / "seismic_3d_core")
LOCAL_BUILD = REPO_ROOT / "build" / "viz-d"
for candidate in (MAIN_NATIVE, LOCAL_BUILD):
    if candidate.exists():
        sys.path.insert(0, str(candidate))

import seismic_3d_core  # noqa: E402  (the frozen native oracle)

OUT = REPO_ROOT / "tests" / "cpp" / "viz_d" / "fixtures"
OUT.mkdir(parents=True, exist_ok=True)


def _num(value):
    value = float(value)
    if math.isnan(value):
        return "nan"
    if math.isinf(value):
        return "inf" if value > 0 else "-inf"
    return value


def _nums(values) -> list:
    return [_num(v) for v in np.asarray(values, dtype=np.float64).reshape(-1)]


def cases() -> dict:
    out = {}

    def run(case_id, volume, iso):
        verts, faces = seismic_3d_core.marching_cubes_3d(
            np.ascontiguousarray(volume, dtype=np.float32), float(iso)
        )
        out[case_id] = {
            "volume": _nums(volume),
            "shape": list(volume.shape),
            "isovalue": float(iso),
            "verts": _nums(verts),
            "faces": [int(v) for v in np.asarray(faces, dtype=np.int64).reshape(-1)],
        }

    # Sphere field crossing 0.5 at radius ~2.
    i, j, k = np.meshgrid(*[np.arange(6.0)] * 3, indexing="ij")
    sphere = ((i - 2.5) ** 2 + (j - 2.5) ** 2 + (k - 2.5) ** 2) / 12.5
    run("sphere", sphere.astype(np.float32), 0.5)
    # Isovalue exactly on grid values (eps nudge path).
    grid = np.zeros((4, 4, 4), dtype=np.float32)
    grid[1:3, 1:3, 1:3] = 1.0
    run("exact_iso", grid, 1.0)
    # NaN cube -> hole, never NaN vertices.
    nanvol = sphere.astype(np.float32).copy()
    nanvol[2, 2, 2] = np.float32("nan")
    run("nan_cube", nanvol, 0.5)
    # Everything below / above the iso -> empty mesh.
    run("empty_below", np.full((3, 3, 3), -1.0, dtype=np.float32), 0.5)
    run("empty_above", np.full((3, 3, 3), 2.0, dtype=np.float32), 0.5)
    # Negative isovalues.
    run("negative_iso", (-sphere).astype(np.float32), -0.25)
    return out


def main() -> None:
    fixture = {
        "generator": "tools/oracle/generate_viz_d_isosurface_fixtures.py",
        "native": "native/seismic_3d_core@0.2.17a0 (main worktree build, read-only)",
        "cases": cases(),
    }
    path = OUT / "viz_d_isosurface_oracle.json"
    path.write_text(json.dumps(fixture, indent=1), encoding="utf-8")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
