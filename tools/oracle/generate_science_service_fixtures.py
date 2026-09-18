#!/usr/bin/env python3
"""Service-level oracle for the CONV-28 native science service layer.

Freezes the numeric core of the C++ service composition against the REAL
Python production leaves (no hand-written expectations):

  * factor pipeline: normalize_factor_samples (workflow/sample_normalization)
    -> IDWInterpolator / _pure_numpy_kriging
    (mapping/geological_pipeline/interpolator) -> FactorGridResult
    statistics -> generate_contour_layer (geological_pipeline/contouring);
  * curve resample: resample_axis + interp_gap_preserving
    (workflow/curve_operations);
  * geomodel build: build_volume_shell (viz/geomodel/builders).

Composition notes (documented seams):
  * The extract step (records -> factor points) is NOT re-frozen here — it
    has its own frozen oracle (generate_extract_fixtures.py). Cases feed
    records whose x/y/value extraction is unambiguous and construct the
    equivalent GeologicalFactor points on the Python side.
  * Service-contract behaviour with no Python counterpart (stable error
    codes for empty inputs / resource guards, envelope structure) is frozen
    literally and marked "source": "cpp-contract" — the C++ replay test
    asserts those exact strings.
  * Geomodel volume for the synthetic flat model is analytic ("source":
    "analytic": flat sheets between two horizons form exact boxes);
    writer-byte parity stays with the CONV-22 export oracle.
  * The DTW log-match service level is covered by C++ internal tests
    against the frozen kernel (this box has no PySide6 for
    viz.dtw_log_matcher import chains).

Display-only Qt dependencies (map render backend / geoviz) are stubbed with
PEP 562 module __getattr__ fakes so the pure numeric modules import without
a Qt runtime; the numeric functions under test are the production code.

Run with a numpy-capable interpreter:

    /home/kevin/oracle-venvs/fusion/bin/python \
        tools/oracle/generate_science_service_fixtures.py
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
import types
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))


def _stub_module(name: str) -> None:
    mod = types.ModuleType(name)

    def _getattr(attr):  # noqa: ANN001
        class _Dummy:  # display-only backend placeholder
            def __init__(self, *a, **k):  # noqa: ANN002, ANN003
                pass

            def __call__(self, *a, **k):  # noqa: ANN002, ANN003
                return None

        return _Dummy

    mod.__dict__["__getattr__"] = _getattr
    sys.modules[name] = mod


_stub_module("paleo_workbench.mapping.map_render_backend")
_stub_module("geoviz")
_stub_module("paleo_workbench.viz.selection_context")

from paleo_workbench.mapping.geological_pipeline.contouring import (  # noqa: E402
    generate_contour_layer,
)
from paleo_workbench.mapping.geological_pipeline.interpolator import (  # noqa: E402
    IDWInterpolator,
    _pure_numpy_kriging,
)
from paleo_workbench.mapping.geological_pipeline.models import (  # noqa: E402
    GeologicalFactor,
    GeologicalFactorDataset,
    InterpolationOptions,
)
from paleo_workbench.workflow.sample_normalization import (  # noqa: E402
    normalize_factor_samples,
)
from paleo_workbench.workflow.curve_operations import (  # noqa: E402
    interp_gap_preserving,
    resample_axis,
)
from paleo_workbench.workflow.crs_policy import (  # noqa: E402
    resolve_distance_policy,
)
from paleo_workbench.viz.geomodel.builders import (  # noqa: E402
    build_horizon_from_grid,
    build_volume_shell,
)

OUT = (
    REPO_ROOT
    / "libs"
    / "science_service"
    / "science_service_tests"
    / "fixtures"
)


def _num(v):
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if isinstance(v, (np.floating, np.integer)):
        v = v.item()
    return v


def _grid_json(arr) -> list:
    return [
        [None if not math.isfinite(float(v)) else float(v) for v in row]
        for row in np.asarray(arr)
    ]


def _records_to_samples(records: list[dict]) -> list[dict]:
    """The service feeds extract output into normalize_factor_samples; with
    unambiguous x/y/value records the extract result is the identity view."""
    out = []
    for rec in records:
        item = {"x": float(rec["x"]), "y": float(rec["y"]),
                "value": float(rec["value"])}
        if rec.get("well_id"):
            item["well_id"] = rec["well_id"]
        if rec.get("qc_flag") and rec["qc_flag"] != "ok":
            item["qc_flag"] = rec["qc_flag"]
        out.append(item)
    return out


def _dataset_from_points(points: list[dict]) -> GeologicalFactorDataset:
    ds = GeologicalFactorDataset(factor_name="gr", unit="", crs="")
    for i, p in enumerate(points):
        # normalize_factor_samples emits the sample under "z" (its canonical
        # record key); input dicts used "value".
        value = p.get("value", p.get("z"))
        ds.add_point(GeologicalFactor(
            name="gr", value=float(value), x=float(p["x"]),
            y=float(p["y"]), well_id=str(p.get("well_id", f"W{i}")),
        ))
    return ds


def _factor_case(cid: str, records: list[dict], *, policy: str = "mean",
                 method: str = "idw", grid_n: int = 10, power: float = 2.0,
                 max_neighbors=None, search_radius=None,
                 variogram: str = "spherical", crs: str = "",
                 with_contours: bool = False) -> dict:
    request = {
        "factor_name": "gr",
        "records": records,
        "duplicate_policy": policy,
        "method": method,
        "grid_n": grid_n,
        "power": power,
        "crs": crs,
    }
    if max_neighbors is not None:
        request["max_neighbors"] = max_neighbors
    if search_radius is not None:
        request["search_radius"] = search_radius
    try:
        points, report = normalize_factor_samples(
            _records_to_samples(records), policy=policy)
    except ValueError as exc:
        return {
            "id": cid, "kind": "factor", "request": request, "ok": False,
            "error": {"code": "factor.normalize", "message": str(exc)},
        }
    ds = _dataset_from_points(points)
    if not ds.valid_points:
        return {
            "id": cid, "kind": "factor", "request": request, "ok": False,
            "error": {"code": "factor.no_samples",
                      "message": "no valid sample points", "source": "cpp-contract"},
        }
    opts = InterpolationOptions(
        method=method, grid_n=grid_n, power=power,
        max_neighbors=max_neighbors, search_radius=search_radius,
        variogram_model=variogram, crs=crs or None)
    try:
        if method == "kriging":
            xs, ys, zs = ds.to_arrays()
            xmin, ymin, xmax, ymax = ds.extent
            gx = np.linspace(xmin, xmax, grid_n, dtype=np.float64)
            gy = np.linspace(ymin, ymax, grid_n, dtype=np.float64)
            gz, gvar, params = _pure_numpy_kriging(
                xs, ys, zs, gx, gy, variogram)
            grid_result = {
                "grid_x": [float(v) for v in gx],
                "grid_y": [float(v) for v in gy],
                "grid_z": np.asarray(gz),
            }
            kriging_params = {
                k: _num(v) for k, v in params.items()
                if isinstance(v, (int, float, str, bool, type(None)))
            }
        else:
            result = IDWInterpolator().interpolate(ds, opts)
            grid_result = {
                "grid_x": [float(v) for v in result.grid_x],
                "grid_y": [float(v) for v in result.grid_y],
                "grid_z": np.asarray(result.grid_z),
            }
            kriging_params = None
    except ValueError as exc:
        # The service maps the kernel's frozen ValueError text onto the
        # factor.interpolate diagnostic code.
        return {
            "id": cid, "kind": "factor", "request": request, "ok": False,
            "error": {"code": "factor.interpolate",
                      "message": f"ValueError: {exc}"},
        }

    gz = np.asarray(grid_result["grid_z"], dtype=np.float32)
    finite = gz[np.isfinite(gz)].astype(np.float64)
    stats = {
        "min": _num(float(finite.min())) if finite.size else None,
        "max": _num(float(finite.max())) if finite.size else None,
        "mean": _num(float(finite.mean())) if finite.size else None,
        "std": _num(float(finite.std())) if finite.size else None,
        "valid_count": int(finite.size),
        "total_count": int(gz.size),
    }

    expected: dict = {
        "id": cid, "kind": "factor", "request": request, "ok": True,
        "grid_x": grid_result["grid_x"],
        "grid_y": grid_result["grid_y"],
        "grid_z": _grid_json(grid_result["grid_z"]),
        "stats": stats,
        "normalization": {
            "policy": report.policy,
            "n_input": report.n_input,
            "n_valid": report.n_valid,
            "n_nonfinite_dropped": report.n_nonfinite_dropped,
            "n_duplicate_groups": report.n_duplicate_groups,
            "n_duplicates_merged": report.n_duplicates_merged,
        },
    }
    if kriging_params is not None:
        expected["kriging_params"] = kriging_params
    if crs:
        policy_info = resolve_distance_policy(crs, None)
        expected["distance_policy"] = {
            "policy": policy_info["policy"],
            "annotation": policy_info["annotation"],
            "warning": policy_info.get("warning"),
        }

    if with_contours:
        # generate_contour_layer needs a FactorGridResult; rebuild the light
        # container from the arrays we already have.
        from paleo_workbench.workflow.factor_grid_result import FactorGridResult
        fr = FactorGridResult(
            grid_z=np.asarray(grid_result["grid_z"], dtype=np.float32),
            grid_x=np.asarray(grid_result["grid_x"], dtype=np.float64),
            grid_y=np.asarray(grid_result["grid_y"], dtype=np.float64),
            factor_name="gr", algorithm_id="idw", crs=crs or None)
        layer = generate_contour_layer(fr, leveling_mode="nice")
        meta = getattr(layer, "metadata", None) or {}
        features = getattr(layer, "features", None) or []
        expected["contour"] = {
            "levels": [_num(float(v)) for v in meta.get("levels", [])],
            "n_features": len(features),
        }
    return expected


def _curve_case(cid: str, depth, values, step: float) -> dict:
    new_depth = resample_axis(list(depth), step)
    new_values = interp_gap_preserving(new_depth, list(depth), list(values))
    return {
        "id": cid, "kind": "curve_resample",
        "request": {"depth": list(depth), "values": list(values),
                    "step": step},
        "ok": True,
        "out_depth": [_num(float(v)) for v in new_depth],
        "out_values": [_num(float(v)) for v in new_values],
    }


def _horizon(rows: int, cols: int, z: float) -> dict:
    return {
        "rows": rows, "cols": cols,
        "origin": [0.0, 0.0], "spacing": [1.0, 1.0],
        "vertical_domain": "depth", "unit": "m",
        "z": [[z] * cols for _ in range(rows)],
    }


def _geomodel_case(cid: str, top: dict, base: dict, *,
                   analytic_volume: float | None = None,
                   build_hex: bool = False) -> dict:
    top_g = build_horizon_from_grid("top", top["z"])
    base_g = build_horizon_from_grid("base", base["z"])
    cols, rows = top["cols"], top["rows"]
    x1 = top["origin"][0] + (cols - 1) * top["spacing"][1]
    y1 = top["origin"][1] + (rows - 1) * top["spacing"][0]
    boundary = [
        [top["origin"][0], top["origin"][1]], [x1, top["origin"][1]],
        [x1, y1], [top["origin"][0], y1],
    ]
    _volume, qc = build_volume_shell(
        top_g, base_g, boundary, object_id=f"volume:{cid}")
    qc = dict(qc)
    # min/max/mean thickness round-trip through float64 exactly; np types are
    # not JSON-serializable.
    for key in ("min_thickness", "max_thickness", "mean_thickness"):
        if key in qc and qc[key] is not None:
            qc[key] = _num(float(qc[key]))
    expected = {
        "id": cid, "kind": "geomodel_build",
        "request": {"top": top, "base": base, "build_hex": build_hex},
        "ok": True,
        "qc": qc,
    }
    if analytic_volume is not None:
        expected["volume"] = {
            "value": analytic_volume, "source": "analytic",
        }
    return expected


def build_horizon_grid(spec: dict):  # noqa: ANN201 - kept for reuse
    return build_horizon_from_grid(spec.get("object_id", "horizon:oracle"),
                                   spec["z"])


RECORDS_4 = [
    {"well_id": "w1", "name": "W1", "x": 0.0, "y": 0.0, "value": 10.0},
    {"well_id": "w2", "name": "W2", "x": 10.0, "y": 0.0, "value": 20.0},
    {"well_id": "w3", "name": "W3", "x": 0.0, "y": 10.0, "value": 30.0},
    {"well_id": "w4", "name": "W4", "x": 10.0, "y": 10.0, "value": 40.0},
]
TWIN = {"well_id": "w5", "name": "W5", "x": 0.0, "y": 0.0, "value": 50.0}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cases: list[dict] = [
        # --- factor pipeline ------------------------------------------------
        _factor_case("idw_basic", RECORDS_4, with_contours=True),
        _factor_case("idw_grid_small", RECORDS_4, grid_n=6),
        _factor_case(
            "idw_knn", RECORDS_4, max_neighbors=2, search_radius=8.0),
        _factor_case("kriging_spherical", RECORDS_4, method="kriging"),
        _factor_case("duplicates_mean", RECORDS_4 + [TWIN]),
        _factor_case("duplicates_error", RECORDS_4 + [TWIN], policy="error"),
        _factor_case("duplicates_keep", RECORDS_4 + [TWIN], policy="keep"),
        _factor_case("single_point_error", [RECORDS_4[0]], grid_n=8),
        _factor_case(
            "nonfinite_records",
            RECORDS_4
            + [{"well_id": "w6", "x": math.inf, "y": 1.0, "value": 5.0},
               {"well_id": "w7", "x": 1.0, "y": math.nan, "value": 6.0}]),
        _factor_case("geographic_crs", RECORDS_4, crs="EPSG:4326"),
        _factor_case("unknown_crs", RECORDS_4, crs="not-a-crs"),
        # cpp-contract cases (no Python counterpart; frozen literally)
        {
            "id": "empty_records", "kind": "factor",
            "request": {"factor_name": "gr", "records": []},
            "ok": False,
            "error": {"code": "factor.no_samples",
                      "message": "factor 'gr' produced no sample points "
                                 "from 0 records",
                      "source": "cpp-contract"},
        },
        {
            "id": "resource_grid_n", "kind": "factor",
            "request": {"factor_name": "gr", "records": RECORDS_4,
                        "grid_n": 3000},
            "ok": False,
            "error": {"code": "resource.grid_n",
                      "message": "grid_n 3000 outside [2, 2000]",
                      "source": "cpp-contract"},
        },
        # --- curve operations ----------------------------------------------
        _curve_case("curve_resample", [0.0, 0.3, 0.7, 1.1, 1.6],
                    [10.0, 11.0, 12.0, 13.0, 14.0], 0.5),
        _curve_case("curve_resample_nan",
                    [0.0, 0.5, 1.0, 1.5, 2.0],
                    [1.0, float("nan"), 3.0, 4.0, 5.0], 0.5),
        {
            "id": "curve_unknown_op", "kind": "curve_resample",
            "request": {"operation": "quantize", "values": [1.0, 2.0]},
            "ok": False,
            "error": {"code": "well.unknown_operation",
                      "message_contains": "unknown curve operation 'quantize'",
                      "source": "cpp-contract"},
        },
        # --- geomodel -------------------------------------------------------
        _geomodel_case(
            "geomodel_flat", _horizon(3, 3, 10.0), _horizon(3, 3, 20.0),
            analytic_volume=40.0),
        _geomodel_case(
            "geomodel_crossed", _horizon(3, 3, 30.0), _horizon(3, 3, 20.0)),
        {
            "id": "geomodel_section", "kind": "geomodel_section",
            "request": {"source": _horizon(3, 3, 10.0),
                        "plane": {"axis": "x", "value": 1.0}},
            "ok": True,
            "polylines": [[[1.0, 0.0, 10.0], [1.0, 1.0, 10.0],
                           [1.0, 2.0, 10.0]]],
            "source": "analytic",
        },
    ]

    payload = {
        "generator": "generate_science_service_fixtures.py",
        "kernel_sources": {
            "factor": "paleo_workbench.mapping.geological_pipeline."
                      "interpolator + workflow.sample_normalization",
            "curve": "paleo_workbench.workflow.curve_operations",
            "geomodel": "paleo_workbench.viz.geomodel.builders",
        },
        "stubs": ["paleo_workbench.mapping.map_render_backend", "geoviz"],
        "cases": cases,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2,
                      allow_nan=True) + "\n"
    # Round-trip guard (Python's reader accepts the NaN/Infinity literals it
    # just wrote; the C++ side reads them with
    # pwb::mapping::parse_json_python_tolerant — the established repo
    # convention for Python-written fixtures).
    json.loads(text)
    (OUT / "science_service_oracle.json").write_text(text, encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    print(f"wrote {len(cases)} cases -> {OUT / 'science_service_oracle.json'}"
          f" (sha256[:16]={digest})")


if __name__ == "__main__":
    main()
