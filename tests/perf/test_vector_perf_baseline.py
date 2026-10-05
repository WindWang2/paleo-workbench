# -*- coding: utf-8 -*-
"""Shared helper for the active vector-perf-increment SLA benchmarks (#1502).

The original measurement suite at this path (Phase-1 baseline: snap/topo/
render/ffi) was archived by 25da9547 (2026-09-22, "chore: archive retired
Python product implementation") to
legacy/python_reference/tests/perf/test_vector_perf_baseline.py (git mv,
history preserved). Two active SLA benches kept importing ``_grid_squares``
from it, which broke pytest collection on the perf/slow nightly legs with
``ModuleNotFoundError: No module named perf.test_vector_perf_baseline``.

This module carries only the shared helper the active tree still needs —
``_grid_squares``, verbatim from the pre-archive file (see
``git show 25da9547^:tests/perf/test_vector_perf_baseline.py``). The retired
measurement tests themselves stay in the archive (their ``paleo_workbench``
imports no longer resolve in the active tree).

Consumers:
  - tests/perf/test_spatial_index_benchmarks.py (uses ``_grid_squares``)
  - tests/perf/test_incremental_topology_bench.py (imports ``_grid_squares``)
"""
from __future__ import annotations


def _grid_squares(n_vertices: int, span: float = 100.0) -> list[dict]:
    """Square grid polygons totalling ~n_vertices (5 per square ring)."""
    squares = max(1, n_vertices // 5)
    side = max(1, int(squares**0.5))
    cell = span / side
    feats: list[dict] = []
    for i in range(side):
        for j in range(side):
            if len(feats) >= squares:
                break
            x0, y0 = i * cell, j * cell
            feats.append({
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[
                    [x0, y0], [x0 + cell, y0], [x0 + cell, y0 + cell],
                    [x0, y0 + cell], [x0, y0]]]},
                "properties": {"__pwb_fid": f"f{i}-{j}", "facies_name": "delta"},
            })
    return feats
