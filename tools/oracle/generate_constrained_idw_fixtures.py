#!/usr/bin/env python3
"""Freeze constrained-IDW oracle fixtures from the REAL Python implementation.

Uses the repo product venv (PySide6 needed by the adapter's contour-level import
chain): /home/kevin/projects/paleo_project/main/.venv/bin/python

For every adapter scenario the generator:
  1. monkeypatches ``drawing.single_factor.constrained_engine``.
     ``generate_constrained_idw`` with a spy that records the EXACT engine
     inputs the host adapter built (wells / boundaries / barriers / directions /
     config dataclasses, asdict) — no mirroring, no hand-derived expectations
     (ledger 05-decisions D1);
  2. calls the real ``run_constrained_idw`` and freezes the returned grid
     (grid_x / grid_y / grid_z with null for NaN) plus the adapter contract
     scalars (n_points, min/max/mean, radii, duplicate drops);
  3. freezes the engine ``diagnostics`` dict for branch-level parity evidence
     (D11).

Engine-direct cases (no adapter) cover the engine's own error branches and the
``extract_contours=False`` surface-only pass (D3): its grid must equal the
extract_contours=True run on the same inputs.

Run:  .venv/bin/python tools/oracle/generate_constrained_idw_fixtures.py
"""
from __future__ import annotations

import dataclasses
import json
import math
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import _legacy_reference

_legacy_reference.ensure_legacy_reference()  # archived-reference shim

from paleo_workbench.project.models import (  # noqa: E402
    ConstraintLayers,
    ConstraintLine,
)
from paleo_workbench.workflow import constrained_idw_adapter as cia  # noqa: E402
from paleo_workbench.workflow.constrained_idw_adapter import (  # noqa: E402
    _ensure_haiyou_engine,
    run_constrained_idw,
)

ENGINE = _ensure_haiyou_engine()
OUT = (
    REPO
    / "libs/mapping_kernel/mapping_kernel_tests/fixtures/constrained_idw_oracle.json"
)

#: Diagnostics set by the surface path of ``generate_constrained_idw`` — the
#: exact key set the C++ kernel reproduces (contour-extraction keys are not
#: ported, D1/D2). ``barrier_buffer_fill_value`` (a NaN display-legacy entry)
#: and ``生成等值线条数`` (contour output; verified as the ONLY key differing
#: between extract_contours=True/False runs on identical inputs) are excluded.
SURFACE_DIAGNOSTIC_KEYS = [
    "active_barrier_count", "active_direction_count", "along_track_stretch",
    "barrier_buffer_applies_to_surface", "barrier_buffer_auto_applied",
    "barrier_buffer_distance", "barrier_buffer_filled_cells",
    "barrier_buffer_forced_zero_cells", "barrier_buffer_masked_grid_points",
    "barrier_contour_core_stop_distance", "barrier_contour_stop_grid_points",
    "barrier_surface_blank_distance", "bfs_gap_fill_skipped",
    "bfs_reach_cells", "blocked_well_grid_relations", "control_point_count",
    "data_hull_buffer_meters", "data_hull_domain_skipped", "data_hull_limited",
    "direction_coverage_percent", "direction_distance_grid_points",
    "explicit_interpolation_area_count", "interpolation_mask_radius_effective",
    "outside_interpolation_area_grid_points", "plain_distance_grid_points",
    "region_count", "vectorized_idw", "well_anchor_anisotropic",
    "well_anchor_core_cells", "well_anchor_count", "well_anchor_limited_count",
    "well_anchor_max_residual", "well_anchor_residual_cells",
    "well_anchor_smooth_cells", "well_coverage_limited",
    "使用方向距离的网格点数", "分割区域数", "参与井点数", "孤立井点数",
    "密集井点数", "打断线屏蔽网格点数", "打断线缓冲距离", "扩展补值网格点数",
    "控制点数", "插值区外网格点数", "方向线覆盖百分比", "无效网格点数",
    "显式插值区数", "普通距离网格点数", "有效打断线数", "有效方向线数",
    "有效网格点数", "补值网格点数",
    "被打断线过滤的井点-网格关系数量",
]


def _surface_diagnostics(diag: dict) -> dict:
    out = {}
    for key in SURFACE_DIAGNOSTIC_KEYS:
        value = diag.get(key)
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            out[key] = float(value)
    return out


def _spy_capture(captured: dict):
    real = ENGINE["generate_constrained_idw"]

    first_call = {"done": False}

    def spy(wells, boundaries, barriers, directions, levels, config,
            cancellation_token=None, **_kw):
        # The adapter re-enters generate for its cross-validation folds
        # (smaller train sets, extract_contours=False); capture only the
        # FIRST call — the real surface pass the expectations come from.
        is_surface_pass = not first_call["done"]
        first_call["done"] = True
        result = real(
            wells, boundaries, barriers, directions, levels, config,
            cancellation_token=cancellation_token,
        )
        if not is_surface_pass:
            return result
        captured["wells"] = [dataclasses.asdict(w) for w in wells]
        captured["boundaries"] = [dataclasses.asdict(b) for b in boundaries]
        captured["barriers"] = [dataclasses.asdict(b) for b in barriers]
        captured["directions"] = [dataclasses.asdict(d) for d in directions]
        captured["levels"] = [float(v) for v in levels]
        captured["config"] = dataclasses.asdict(config)
        captured["_raw_config"] = config
        captured["_raw_wells"] = list(wells)
        captured["_raw_boundaries"] = list(boundaries)
        captured["_raw_barriers"] = list(barriers)
        captured["_raw_directions"] = list(directions)
        captured["diagnostics"] = _surface_diagnostics(result.diagnostics)
        return result

    return spy, real


def _grid_rows(gz: np.ndarray) -> list:
    return [
        [None if not np.isfinite(v) else float(v) for v in row]
        for row in np.asarray(gz, dtype=float)
    ]


_RAW_CAPTURES: dict[str, dict] = {}


def run_case(name: str, points: list[dict], *, grid_n: int, power: float = 2.0,
             break_polylines=None, layers=None, crs: str | None = None) -> dict:
    captured: dict = {}
    spy, real = _spy_capture(captured)
    ENGINE["generate_constrained_idw"] = spy
    try:
        result = run_constrained_idw(
            points, grid_n=grid_n, power=power, layers=layers,
            break_polylines=break_polylines, crs=crs,
        )
    finally:
        ENGINE["generate_constrained_idw"] = real
    _RAW_CAPTURES[name] = captured

    layers_payload = None
    if layers is not None:
        layers_payload = [
            {
                "id": layer.id,
                "lines": [
                    {
                        "id": line.id,
                        "role": line.role,
                        "coordinates": [[float(x), float(y)]
                                        for x, y in line.coordinates],
                        "semi_major": (float(line.semi_major)
                                       if line.semi_major is not None else None),
                        "semi_minor": (float(line.semi_minor)
                                       if line.semi_minor is not None else None),
                        "active": bool(line.active),
                    }
                    for line in layer.lines
                ],
            }
            for layer in layers
        ]
    return {
        "kind": "adapter",
        "name": name,
        "adapter_inputs": {
            "points": [
                {"x": float(p["x"]), "y": float(p["y"]),
                 "value": float(p["value"])}
                for p in points
            ],
            "break_polylines": (
                [[[float(x), float(y)] for x, y in poly]
                 for poly in break_polylines]
                if break_polylines is not None
                else None
            ),
            "layers": layers_payload,
            "crs": crs,
            "grid_n": int(grid_n),
            "power": float(power),
        },
        "engine_inputs": {
            k: v for k, v in captured.items() if not k.startswith("_raw_")
        },
        "expected": {
            "grid_x": [float(v) for v in np.asarray(result["grid_x"])],
            "grid_y": [float(v) for v in np.asarray(result["grid_y"])],
            "grid_z": _grid_rows(result["grid_z"]),
            "n_points": int(result["n_points"]),
            "n_break_lines": int(result["n_break_lines"]),
            "n_direction_lines": int(result["n_direction_lines"]),
            "duplicate_wells_dropped": int(result["duplicate_wells_dropped"]),
            "min": float(result["min"]),
            "max": float(result["max"]),
            "mean": float(result["mean"]),
            "search_radius": float(result["search_radius"]),
            "decluster_radius": float(result["decluster_radius"]),
        },
    }


def run_engine_case(name: str, *, wells: list, boundaries: list, barriers: list,
                    directions: list, config) -> dict:
    """Engine-direct case: no adapter glue, exact ValueError text on failure."""
    try:
        result = ENGINE["generate_constrained_idw"](
            wells, boundaries, barriers, directions, [], config
        )
    except ValueError as exc:
        return {
            "kind": "engine_error",
            "name": name,
            "engine_inputs": {
                "wells": [dataclasses.asdict(w) for w in wells],
                "boundaries": [dataclasses.asdict(b) for b in boundaries],
                "barriers": [dataclasses.asdict(b) for b in barriers],
                "directions": [dataclasses.asdict(d) for d in directions],
                "levels": [],
                "config": dataclasses.asdict(config),
            },
            "expected_error": str(exc),
        }
    return {
        "kind": "engine",
        "name": name,
        "engine_inputs": {
            "wells": [dataclasses.asdict(w) for w in wells],
            "boundaries": [dataclasses.asdict(b) for b in boundaries],
            "barriers": [dataclasses.asdict(b) for b in barriers],
            "directions": [dataclasses.asdict(d) for d in directions],
            "levels": [],
            "config": dataclasses.asdict(config),
            "diagnostics": _surface_diagnostics(result.diagnostics),
        },
        "expected": {
            "grid_x": [float(v) for v in np.asarray(result.grid_x)],
            "grid_y": [float(v) for v in np.asarray(result.grid_y)],
            "grid_z": _grid_rows(result.grid_z),
        },
    }


def _pts(*triples: tuple[float, float, float]) -> list[dict]:
    return [{"x": x, "y": y, "value": v} for x, y, v in triples]


def _sample_points(n: int, seed: int) -> list[dict]:
    """Same deterministic sampler as tests/test_constrained_idw_integration.py."""
    rng = np.random.default_rng(seed)
    xs = rng.uniform(0.0, 10.0, size=n)
    ys = rng.uniform(0.0, 10.0, size=n)
    vals = (np.sin(xs) + np.cos(ys) + 2.0) / 4.0
    return [{"x": float(x), "y": float(y), "value": float(v)}
            for x, y, v in zip(xs, ys, vals)]


def _direction_layer(layer_id: str, lines: list[dict]) -> list:
    return [
        ConstraintLayers(
            id=layer_id,
            name=layer_id,
            lines=[
                ConstraintLine(
                    id=spec["id"],
                    name=spec.get("name", spec["id"]),
                    role="direction",
                    coordinates=spec["coordinates"],
                    semi_major=spec.get("semi_major"),
                    semi_minor=spec.get("semi_minor"),
                )
                for spec in lines
            ],
        )
    ]


def main() -> None:
    cases: list[dict] = []

    # 1. Plane field, no constraints — no-barrier batch path, coverage domain.
    cases.append(run_case(
        "plain_plane_9w",
        _pts(
            (0.0, 0.0, 0.5), (10.0, 0.0, 5.5), (0.0, 10.0, 5.5),
            (10.0, 10.0, 10.5), (5.0, 0.0, 3.0), (0.0, 5.0, 3.0),
            (5.0, 10.0, 8.0), (10.0, 5.0, 8.0), (5.0, 5.0, 5.5),
        ),
        grid_n=50,
    ))

    # 2. Full-spanning fault through thickness field (#370 scenario) —
    #    batch kernel + LOS + region labels + barrier blank corridor.
    cases.append(run_case(
        "barrier_fault_thickness",
        _pts(
            (0.0, 0.0, 20.0), (5.0, 0.0, 40.0), (10.0, 0.0, 60.0),
            (0.0, 10.0, 30.0), (10.0, 10.0, 80.0),
        ),
        grid_n=50,
        break_polylines=[[(0.0, 5.0), (10.0, 5.0)]],
    ))

    # 3. Dead-end barrier (#382 scenario) — LOS leakage guard at grid 40.
    cases.append(run_case(
        "barrier_deadend_382",
        _pts(
            (-4.0, -4.0, 1.0), (-4.0, 0.0, 1.0), (-4.0, 4.0, 1.0),
            (4.0, -4.0, 10.0), (4.0, 0.0, 10.0), (4.0, 4.0, 10.0),
        ),
        grid_n=40,
        break_polylines=[[(0.0, -8.0), (0.0, 1.0)]],
    ))

    # 4. Duplicate coordinate wells (#399) — first-wins everywhere.
    cases.append(run_case(
        "dup_wells_399",
        _pts(
            (0.0, 0.0, 1.0), (4.0, 0.0, 1.0), (0.0, 4.0, 1.0),
            (4.0, 4.0, 1.0), (2.0, 2.0, 1.0), (2.0, 2.0, 0.1),
        ),
        grid_n=25,
    ))

    # 5. Direction line only — batch anisotropic path + along-track blend
    #    (ratio floored at 16 by the adapter).
    cases.append(run_case(
        "direction_line_8w",
        _sample_points(8, seed=0),
        grid_n=30,
        layers=_direction_layer(
            "cl-2",
            [{"id": "dir-1", "name": "axis",
              "coordinates": [[0.0, 5.0], [10.0, 5.0]],
              "semi_major": 2.0, "semi_minor": 0.5}],
        ),
    ))

    # 6. Direction + barrier — per-cell curve-corridor path, region labels,
    #    anisotropic anchoring, double along-track blend.
    cases.append(run_case(
        "direction_barrier_9w",
        _pts(
            (1.0, 1.5, 0.2), (3.0, 2.0, 0.4), (4.0, 8.0, 0.7),
            (6.0, 1.0, 0.35), (7.5, 3.0, 0.55), (8.5, 7.5, 0.8),
            (2.5, 6.0, 0.5), (6.5, 5.5, 0.62), (9.0, 2.5, 0.45),
        ),
        grid_n=30,
        break_polylines=[[(0.0, 4.5), (7.0, 4.5)]],
        layers=_direction_layer(
            "cl-3",
            [{"id": "dir-1", "name": "channel",
              "coordinates": [[0.5, 2.5], [9.5, 3.5]],
              "semi_major": 3.0, "semi_minor": 0.5}],
        ),
    ))

    # 7. Two crossing direction lines — multi-direction junction dual-angle
    #    blend in build_grid_direction_cache.
    cases.append(run_case(
        "two_directions_junction",
        _sample_points(10, seed=4),
        grid_n=30,
        layers=_direction_layer(
            "cl-4",
            [
                {"id": "dir-a", "name": "a",
                 "coordinates": [[0.0, 3.0], [10.0, 4.0]],
                 "semi_major": 2.5, "semi_minor": 0.5},
                {"id": "dir-b", "name": "b",
                 "coordinates": [[4.0, 10.0], [6.0, 0.0]],
                 "semi_major": 3.0, "semi_minor": 0.6},
            ],
        ),
    ))

    # 8. Geographic CRS (#400) — explicit sub-cell degree barrier buffer.
    cases.append(run_case(
        "degree_crs_400",
        _pts(
            (0.2, 0.0, 20.0), (0.2, 0.5, 30.0), (0.2, 1.0, 40.0),
            (0.8, 0.0, 60.0), (0.8, 0.5, 70.0), (0.8, 1.0, 80.0),
        ),
        grid_n=60,
        break_polylines=[[(0.5, -0.2), (0.5, 1.2)]],
        crs="EPSG:4326 / WGS84",
    ))

    # 9–11. Engine-direct cases (D3/D12): reuse the EXACT engine inputs the
    # adapter passed for the fault scenario, with extract_contours=False and
    # with the two engine error branches — nothing hand-derived.
    cap = _RAW_CAPTURES["barrier_fault_thickness"]
    fault_cfg = cap["_raw_config"]
    surface_only_cfg = dataclasses.replace(fault_cfg, extract_contours=False)
    cases.append(run_engine_case(
        "engine_surface_only", wells=cap["_raw_wells"],
        boundaries=cap["_raw_boundaries"], barriers=cap["_raw_barriers"],
        directions=cap["_raw_directions"], config=surface_only_cfg,
    ))
    cases.append(run_engine_case(
        "engine_error_too_few_wells",
        wells=cap["_raw_wells"][:2], boundaries=cap["_raw_boundaries"],
        barriers=[], directions=[], config=fault_cfg,
    ))
    cases.append(run_engine_case(
        "engine_error_no_boundary",
        wells=cap["_raw_wells"], boundaries=[],
        barriers=[], directions=[], config=fault_cfg,
    ))
    # Third engine branch: a boundary polygon without vertices (axes build).
    Boundary = ENGINE["Boundary"]
    cases.append(run_engine_case(
        "engine_error_empty_exterior",
        wells=cap["_raw_wells"],
        boundaries=[Boundary(exterior=())],
        barriers=[], directions=[], config=fault_cfg,
    ))

    payload = {
        "_meta": {
            "generator": "tools/oracle/generate_constrained_idw_fixtures.py",
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "upstream": "WWX9/haiyou-visualization @ 5b8f8f98 (vendored, see "
                        "paleo_workbench/_vendored/haiyou_constrained_idw/ATTRIBUTION.md)",
            "note": "adapter cases capture the EXACT engine inputs via a spy "
                    "on generate_constrained_idw; expectations come from the "
                    "real run_constrained_idw — nothing hand-derived.",
        },
        "cases": cases,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")
    total_cells = sum(
        len(c["expected"]["grid_z"]) * len(c["expected"]["grid_z"][0])
        for c in cases
        if c.get("expected", {}).get("grid_z")
    )
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")
    print(f"cases: {len(cases)} ({sum(1 for c in cases if 'expected' in c)} "
          f"numeric, {total_cells} grid cells)")
    for c in cases:
        label = c["name"]
        if "expected_error" in c:
            print(f"  {label}: error<{c['expected_error']}>")
        elif "expected" in c and "n_points" in c["expected"]:
            print(f"  {label}: {c['expected']['n_points']} wells, "
                  f"grid {len(c['expected']['grid_z'])}x"
                  f"{len(c['expected']['grid_x'])}")


if __name__ == "__main__":
    main()
