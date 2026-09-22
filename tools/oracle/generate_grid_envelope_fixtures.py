#!/usr/bin/env python3
"""Oracle for the FactorGridResult JSON envelope (factor_grid_result.py, task 18).

Freezes the REAL Python behavior of
``FactorGridResult.from_legacy_task_parameters`` (both nodata encodings,
metadata fallbacks, error messages), ``to_descriptor``, ``to_legacy_dict``,
``GridStatistics.to_dict``, ``encode_legacy_grid_lists`` /
``encode_legacy_axis_list`` and the ``from_engine_dict`` legacy round-trip.

Every expectation value in the fixture is produced by calling the live Python
module — nothing is hand-written.

Run (from the worktree root, NOT the main workspace — see 18-decisions D12):

    /home/kevin/project/oracle-venvs/conv11/bin/python \
        tools/oracle/generate_grid_envelope_fixtures.py
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import _legacy_reference

_legacy_reference.ensure_legacy_reference()  # archived-reference shim

from paleo_workbench.workflow.factor_grid_result import (  # noqa: E402
    FactorGridResult,
    encode_legacy_axis_list,
    encode_legacy_grid_lists,
)

OUT = REPO_ROOT / "libs" / "mapping_kernel" / "mapping_kernel_tests" / "fixtures"
FIXTURE = OUT / "grid_envelope_oracle.json"

NAN = float("nan")
INF = float("inf")


def _cells(arr) -> list:
    flat = np.asarray(arr, dtype=np.float32).reshape(-1)
    return [None if not math.isfinite(float(v)) else float(v) for v in flat]


def _freeze_result(r: FactorGridResult, factor_name: str) -> dict:
    descriptor = r.to_descriptor()
    descriptor_strict = json.dumps(descriptor, ensure_ascii=False, allow_nan=False)
    legacy = r.to_legacy_dict()
    legacy_strict = json.dumps(legacy, ensure_ascii=False, allow_nan=False)
    # Python-side proof of the round-trip contract (pytest
    # test_legacy_round_trip_is_lossless_for_finite_values): read the strict
    # legacy JSON back through the engine path and freeze what survives.
    r2 = FactorGridResult.from_engine_dict(
        json.loads(legacy_strict), factor_name=factor_name
    )
    return {
        "height": int(r.height),
        "width": int(r.width),
        "grid_cells": _cells(r.grid_z),
        "axes": {
            "grid_x": [float(v) for v in r.grid_x.tolist()],
            "grid_y": [float(v) for v in r.grid_y.tolist()],
        },
        "variance_cells": (
            _cells(r.variance_grid) if r.variance_grid is not None else None
        ),
        "stats_to_dict": r.statistics.to_dict(),
        "descriptor": json.loads(descriptor_strict),
        "descriptor_strict_json": descriptor_strict,
        "legacy": json.loads(legacy_strict),
        "legacy_strict_json": legacy_strict,
        "encode_axis_x": encode_legacy_axis_list(r.grid_x),
        "encode_axis_y": encode_legacy_axis_list(r.grid_y),
        "encode_grid_lists": encode_legacy_grid_lists(r.grid_z),
        "roundtrip": {
            "grid_cells": _cells(r2.grid_z),
            "stats_to_dict": r2.statistics.to_dict(),
            "algorithm_id": r2.algorithm_id,
        },
    }


def _run(spec: dict) -> dict:
    try:
        r = FactorGridResult.from_legacy_task_parameters(
            spec["parameters"],
            factor_name=spec["factor_name"],
            crs=spec["crs"],
            unit=spec["unit"],
            metadata=spec["metadata"],
        )
    except (ValueError, KeyError, TypeError) as err:
        return {"error": str(err), "error_type": type(err).__name__}
    return {
        "error": None,
        "error_type": None,
        "result": _freeze_result(r, spec["factor_name"]),
    }


def _case(case_id: str, parameters: dict, *, factor_name="porosity",
          crs=None, unit=None, metadata=None) -> dict:
    spec = {
        "id": case_id,
        "factor_name": factor_name,
        "crs": crs,
        "unit": unit,
        "parameters": parameters,
        "metadata": metadata,
    }
    frozen = _run(spec)
    return {
        "id": case_id,
        "factor_name": factor_name,
        "crs": crs,
        "unit": unit,
        # Raw Python json.dumps bytes (default allow_nan=True → may contain
        # NaN/Infinity literals exactly like legacy project files).
        "parameters": json.dumps(parameters),
        "metadata": None if metadata is None else json.dumps(metadata),
        "error": frozen["error"],
        "error_type": frozen["error_type"],
        **({"result": frozen["result"]} if frozen["error"] is None else {}),
    }


def _grid(x, y, z, **extra) -> dict:
    p = {"grid_x": x, "grid_y": y, "grid_z": z}
    p.update(extra)
    return p


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cases = [
        # --- success: from_legacy_task_parameters core branches -------------
        _case(
            "idw_none_cells",
            _grid([0.0, 1.0], [10.0, 11.0], [[1.0, 2.0], [None, 4.0]],
                  interp_backend="idw", grid="2x2", power=2.0,
                  sample_points=[[0.0, 10.0, 1.0], [1.0, 11.0, 4.0]]),
            crs="EPSG:4326",
        ),
        _case(
            "backend_fallback_kriging_variance",
            _grid([0.0, 1.0], [10.0, 11.0], [[1.0, 2.0], [3.0, 4.0]],
                  backend="kriging", grid="2x2", n_points=4, r_squared=0.5,
                  grid_var=[[0.1, 0.2], [0.3, 0.4]],
                  variance_min=0.1, variance_max=0.4),
            unit="%",
        ),
        _case(
            "unknown_algorithm",
            _grid([0.0, 1.0], [10.0, 11.0], [[1.0, 2.0], [3.0, 4.0]]),
        ),
        _case(
            "descriptor_metadata_full",
            _grid([0.0, 1.0], [10.0, 11.0], [[1.0, 2.0], [3.0, 4.0]],
                  interp_backend="idw", grid="2x2 label", power=3.0,
                  n_break_lines=1, sample_points=[[0.0, 10.0, 1.0]]),
            metadata={
                "algorithm_id": "directional",
                "algorithm_parameters": {
                    "r_squared": 0.9, "grid_label": "old", "n_points": 7,
                    "power": 1.5, "n_break_lines": 4,
                    "legacy_extra": "keep",
                },
                "crs": "EPSG:4326", "unit": "%",
                "generator_version": "py-1.2",
                # Non-string elements pass through verbatim (raw dict access).
                "source_refs": ["asset-1", 2, True],
                "run_ref": 9, "created_at": "2026-09-18T00:00:00Z",
            },
        ),
        _case(
            "metadata_empty_defaults",
            _grid([0.0, 1.0], [10.0, 11.0], [[1.0, 2.0], [3.0, 4.0]],
                  interp_backend="spline"),
            metadata={},
        ),
        _case(
            "all_nodata",
            _grid([0.0, 1.0], [10.0, 11.0],
                  [[None, None], [None, None]], interp_backend="idw"),
        ),
        _case(
            "nan_inf_cells",
            _grid([0.0, 1.0], [10.0, 11.0],
                  [[1.0, NAN], [INF, -INF]], backend="constrained_idw"),
        ),
        _case(
            "kriging_variance_nan",
            _grid([0.0, 1.0], [10.0, 11.0], [[1.0, 2.0], [3.0, 4.0]],
                  backend="kriging", grid_var=[[0.5, None], [NAN, 1.5]]),
        ),
        _case(
            "azimuth_branch",
            _grid([0.0, 1.0], [10.0, 11.0], [[1.0, 2.0], [3.0, 4.0]],
                  interp_backend="directional", azimuth_deg=42.5,
                  semi_major=5.0),
        ),
        _case(
            "azimuth_null_skips_branch",
            _grid([0.0, 1.0], [10.0, 11.0], [[1.0, 2.0], [3.0, 4.0]],
                  interp_backend="directional", azimuth_deg=None),
        ),
        _case(
            "boundary_closed_ring_int_coords",
            _grid([0.0, 1.0], [10.0, 11.0], [[1.0, 2.0], [3.0, 4.0]],
                  interp_backend="idw",
                  grid_boundary=[[0, 10], [1, 10], [1, 11], [0, 10]]),
        ),
        _case(
            "empty_boundary",
            _grid([0.0, 1.0], [10.0, 11.0], [[1.0, 2.0], [3.0, 4.0]],
                  interp_backend="idw", grid_boundary=[]),
        ),
        _case(
            "crs_from_descriptor",
            _grid([0.0, 1.0], [10.0, 11.0], [[1.0, 2.0], [3.0, 4.0]]),
            metadata={"crs": "EPSG:4326", "unit": "%"},
        ),
        _case(
            "crs_explicit_overrides_descriptor",
            _grid([0.0, 1.0], [10.0, 11.0], [[1.0, 2.0], [3.0, 4.0]]),
            crs="EPSG:32650",
            metadata={"crs": "EPSG:4326", "unit": "%"},
        ),
        _case(
            "unit_empty_string_is_explicit",
            _grid([0.0, 1.0], [10.0, 11.0], [[1.0, 2.0], [3.0, 4.0]]),
            unit="",
            metadata={"unit": "%"},
        ),
        _case(
            "empty_backend_chain",
            _grid([0.0, 1.0], [10.0, 11.0], [[1.0, 2.0], [3.0, 4.0]],
                  interp_backend="", backend=""),
        ),
        _case(
            "float32_normalization",
            _grid([0.0, 1.0, 2.0], [10.0, 11.0],
                  [[0.1, 1e40, -1e40], [123456789.0, 3.14, 1e-45]],
                  interp_backend="idw"),
        ),
        _case(
            "int_inputs",
            _grid([0, 1, 2], [5, 6], [[1, 2, 3], [4, 5, 6]],
                  interp_backend="idw", power=2),
            metadata={"algorithm_parameters": {"n_points": 6}},
        ),
        _case(
            "sample_points_empty_falls_back",
            _grid([0.0, 1.0], [10.0, 11.0], [[1.0, 2.0], [3.0, 4.0]],
                  interp_backend="idw", sample_points=[]),
            metadata={"algorithm_parameters": {"n_points": 9}},
        ),
        _case(
            "single_cell",
            _grid([0.0], [10.0], [[7.5]], interp_backend="idw"),
        ),
        _case(
            "rectangular_2x3",
            _grid([0.0, 1.0, 2.0], [10.0, 11.0],
                  [[1.0, 2.0, 3.0], [4.0, 5.0, None]], interp_backend="idw"),
        ),
        _case(
            "grid_null_beats_params_grid_label",
            _grid([0.0, 1.0], [10.0, 11.0], [[1.0, 2.0], [3.0, 4.0]],
                  interp_backend="idw", grid=None),
            metadata={"algorithm_parameters": {"grid_label": "old"}},
        ),
        _case(
            "n_break_lines_null_in_parameters",
            _grid([0.0, 1.0], [10.0, 11.0], [[1.0, 2.0], [3.0, 4.0]],
                  interp_backend="idw", n_break_lines=None),
        ),
        _case(
            "bool_inputs_numericize",
            _grid([True, False], [10.0, 11.0],
                  [[True, False], [3.0, 4.0]], interp_backend="idw"),
        ),
        _case(
            "nested_3d_reshapes",
            _grid([0.0, 1.0], [10.0, 11.0],
                  [[[1.0, 2.0], [3.0, 4.0]]], interp_backend="idw"),
        ),
        _case(
            "flat_grid_z_reshapes",
            _grid([0.0, 1.0], [10.0, 11.0], [1.0, 2.0, 3.0, 4.0],
                  interp_backend="idw"),
        ),
        _case(
            "params_grid_label_power_fallback",
            _grid([0.0, 1.0], [10.0, 11.0], [[1.0, 2.0], [3.0, 4.0]],
                  interp_backend="idw"),
            metadata={"algorithm_parameters": {"grid_label": "carried",
                                               "power": 1.5}},
        ),
        _case(
            "grid_var_null_skips",
            _grid([0.0, 1.0], [10.0, 11.0], [[1.0, 2.0], [3.0, 4.0]],
                  backend="kriging", grid_var=None),
        ),
        _case(
            "nan_backend_is_truthy",
            _grid([0.0, 1.0], [10.0, 11.0], [[1.0, 2.0], [3.0, 4.0]],
                  backend=NAN, grid="NaN grid"),
        ),
        _case(
            "nan_azimuth_gate_is_not_none",
            _grid([0.0, 1.0], [10.0, 11.0], [[1.0, 2.0], [3.0, 4.0]],
                  interp_backend="directional", azimuth_deg=NAN),
        ),
        _case(
            "err_metadata_params_string",
            _grid([0.0, 1.0], [10.0, 11.0], [[1.0, 2.0], [3.0, 4.0]]),
            metadata={"algorithm_parameters": "abc"},
        ),
        # --- errors: exact str(exc) messages --------------------------------
        _case(
            "err_null_axis_x",
            {"grid_x": None, "grid_y": [10.0], "grid_z": [[1.0]]},
        ),
        _case(
            "err_float_axis_x",
            {"grid_x": 5.5, "grid_y": [10.0], "grid_z": [[1.0]]},
        ),
        _case(
            "err_bool_axis_x",
            {"grid_x": True, "grid_y": [10.0], "grid_z": [[1.0]]},
        ),
        _case(
            "err_missing_grid_x",
            {"grid_y": [10.0], "grid_z": [[1.0]]},
        ),
        _case(
            "err_missing_grid_y",
            {"grid_x": [0.0], "grid_z": [[1.0]]},
        ),
        _case(
            "err_missing_grid_z",
            {"grid_x": [0.0], "grid_y": [10.0]},
        ),
        _case(
            "err_empty_axis_x",
            _grid([], [], [], interp_backend="idw"),
        ),
        _case(
            "err_nan_axis_x",
            _grid([0.0, NAN], [10.0, 11.0],
                  [[1.0, 2.0], [3.0, 4.0]], interp_backend="idw"),
        ),
        _case(
            "err_shape_mismatch_x",
            _grid([0.0, 1.0, 2.0], [10.0, 11.0],
                  [[1.0, 2.0], [3.0, 4.0]], interp_backend="idw"),
        ),
        _case(
            "err_shape_mismatch_y",
            _grid([0.0, 1.0], [10.0],
                  [[1.0, 2.0], [3.0, 4.0]], interp_backend="idw"),
        ),
        _case(
            "err_shape_mismatch_flat",
            _grid([0.0, 1.0], [10.0, 11.0], [1.0, 2.0, 3.0, 4.0, 5.0],
                  interp_backend="idw"),
        ),
        _case(
            "err_boundary_nonfinite",
            _grid([0.0, 1.0], [10.0, 11.0], [[1.0, 2.0], [3.0, 4.0]],
                  interp_backend="idw",
                  grid_boundary=[[0.0, INF], [1.0, 10.0]]),
        ),
        _case(
            "err_axis_2d",
            _grid([[0.0, 1.0], [0.0, 1.0]], [10.0, 11.0],
                  [[1.0, 2.0], [3.0, 4.0]], interp_backend="idw"),
        ),
        _case(
            "err_shape_mismatch_3d",
            _grid([0.0, 1.0], [10.0, 11.0],
                  [[[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]],
                  interp_backend="idw"),
        ),
    ]

    n_ok = sum(1 for c in cases if c["error"] is None)
    fixture = {
        "generator": "tools/oracle/generate_grid_envelope_fixtures.py",
        "module": "paleo_workbench.workflow.factor_grid_result",
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "n_cases": len(cases),
        "n_ok": n_ok,
        "n_error": len(cases) - n_ok,
        "cases": cases,
    }
    text = json.dumps(fixture, ensure_ascii=False, indent=1)
    # Self-check: the embedded strict payloads really are strict.
    for c in cases:
        if c["error"] is None:
            result = _run({**c, "parameters": json.loads(c["parameters"]),
                           "metadata": (None if c["metadata"] is None
                                        else json.loads(c["metadata"]))})
            json.loads(result["result"]["descriptor_strict_json"])
            json.loads(result["result"]["legacy_strict_json"])
    FIXTURE.write_text(text, encoding="utf-8")
    print(f"wrote {FIXTURE} ({len(cases)} cases: {n_ok} ok, "
          f"{len(cases) - n_ok} error)")


if __name__ == "__main__":
    main()
