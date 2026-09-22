#!/usr/bin/env python3
"""Oracle fixture generator for the CONV-01 map-pipeline runner (swarm 01).

Imports the REAL implementation (paleo_workbench mapping geological_pipeline +
services) and freezes the full "well records -> extract_factors ->
interpolate_factor -> contour layer -> facies polygon layer" chain to JSON so
the C++ runner (libs/application map_pipeline_runner) is verified against the
Python product, not against hand-written expectations.

Regenerate with (venv python that can import paleo_workbench):
    cd <worktree-root> && ../main/.venv/bin/python \
        tools/oracle/generate_map_pipeline_fixtures.py

The generator also ASSERTS that shapely's repair_invalid_geometry is an
identity on the traced cell-boundary rings (the C++ frozen kernel does not
port repair): if the Python product ever changes geometry here, generation
fails loudly instead of freezing an oracle the C++ port cannot reproduce.
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

from paleo_workbench.mapping.geological_pipeline.contouring import (  # noqa: E402
    generate_contour_layer,
)
from paleo_workbench.mapping.geological_pipeline.interpolator import (  # noqa: E402
    interpolate_factor,
)
from paleo_workbench.mapping.geological_pipeline.models import (  # noqa: E402
    InterpolationOptions,
)
from paleo_workbench.mapping.geological_pipeline.pipeline import (  # noqa: E402
    GeologicalMappingPipeline,
)
from paleo_workbench.mapping.geological_pipeline.polygonization import (  # noqa: E402
    _polygonize_raster_boundaries,
    generate_facies_polygon_layer,
)
from paleo_workbench.workflow.factor_grid_result import FactorGridResult  # noqa: E402

OUT = REPO_ROOT / "tests" / "cpp" / "platform" / "fixtures" / "map_pipeline_oracle.json"


def _clean(value):
    """Recursively convert numpy scalars / tuples to JSON-safe plain types."""
    if isinstance(value, np.ndarray):
        return _clean(value.tolist())
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (np.floating, float)):
        v = float(value)
        return None if not math.isfinite(v) else v
    if isinstance(value, (np.integer, int)):
        return int(value)
    return value


def _grid_json(result: FactorGridResult) -> dict:
    """Freeze the interpolated grid exactly as the C++ FactorGrid carries it."""
    stats = result.statistics.to_dict()
    return {
        "grid_x": [float(v) for v in result.grid_x],
        "grid_y": [float(v) for v in result.grid_y],
        # grid_z frozen per cell; NaN -> None (JSON has no NaN).
        "grid_z": [_clean(row) for row in result.grid_z],
        "width": int(result.grid_z.shape[1]),
        "height": int(result.grid_z.shape[0]),
        "statistics": stats,
        "algorithm_parameters": _clean(result.algorithm_parameters),
    }


def _repair_identity_guard(grid_result: FactorGridResult, thresholds, names,
                           expect_features: bool) -> None:
    """Fail loudly when repair/orient changes any traced ring.

    expect_features=False covers the early-return paths (all-NaN / empty
    grids) where the product never reaches repair; the C++ frozen kernel
    returns the same empty set there, so there is nothing to guard.
    """
    if not expect_features:
        return
    # Resolve the same thresholds the product call below will use.
    z = np.asarray(grid_result.grid_z)
    if thresholds is None:
        finite = z[np.isfinite(z)]
        vmin = float(finite.min()) if finite.size else 0.0
        vmax = float(finite.max()) if finite.size else 0.0
        if math.isclose(vmin, vmax):
            thresholds = [vmin]
        else:
            thresholds = [vmin + (vmax - vmin) * 0.333, vmin + (vmax - vmin) * 0.666]
    else:
        thresholds = sorted(set(float(t) for t in thresholds))
    # The product path calls repair_invalid_geometry inside
    # generate_facies_polygon_layer; trace the same classes WITHOUT repair
    # (the kernel helper) and require identical coordinates.
    from paleo_workbench.mapping.topology import repair_invalid_geometry

    original_repair = repair_invalid_geometry
    repaired_seen = 0

    def spying_repair(geom):
        nonlocal repaired_seen
        out = original_repair(geom)
        if _clean(out) != _clean(geom):
            raise AssertionError(
                "repair_invalid_geometry changed traced geometry; the C++ "
                "kernel (repair=identity) can no longer reproduce the Python "
                f"product. First divergence: {geom} -> {out}"
            )
        repaired_seen += 1
        return out

    import paleo_workbench.mapping.geological_pipeline.polygonization as pol

    pol.repair_invalid_geometry = spying_repair
    try:
        generate_facies_polygon_layer(
            grid_result, thresholds=list(thresholds), facies_names=list(names)
        )
    finally:
        pol.repair_invalid_geometry = original_repair
    assert repaired_seen > 0, "spy never invoked: product stopped repairing"


# The frozen 8-well fixture (tests/test_geological_mapping_pipeline.py
# sample_well_dataset): porosity %, EPSG:4326, horizon T1.
EIGHT_WELL_RECORDS = [
    {"well_id": "W1", "name": "井-1", "x": 114.10, "y": 22.50, "孔隙度": 18.5},
    {"well_id": "W2", "name": "井-2", "x": 114.25, "y": 22.52, "孔隙度": 22.3},
    {"well_id": "W3", "name": "井-3", "x": 114.38, "y": 22.48, "孔隙度": 15.2},
    {"well_id": "W4", "name": "井-4", "x": 114.15, "y": 22.65, "孔隙度": 24.1},
    {"well_id": "W5", "name": "井-5", "x": 114.30, "y": 22.68, "孔隙度": 19.8},
    {"well_id": "W6", "name": "井-6", "x": 114.42, "y": 22.62, "孔隙度": 12.4},
    {"well_id": "W7", "name": "井-7", "x": 114.20, "y": 22.80, "孔隙度": 26.5},
    {"well_id": "W8", "name": "井-8", "x": 114.35, "y": 22.82, "孔隙度": 21.0},
]


def _run_case(name, records, factor_name, unit, crs, target_horizon, method,
              grid_n, power, contour_levels, thresholds, facies_names,
              min_neighbors=1, search_radius=None, expected_error=None):
    """Run the real chain and freeze every stage. expected_error freezes the
    ValueError branch (the C++ runner must surface the same message)."""
    case = {
        "request": {
            "factor_name": factor_name,
            "unit": unit,
            "crs": crs,
            "target_horizon": target_horizon,
            "method": method,
            "grid_n": grid_n,
            "power": power,
            "min_neighbors": min_neighbors,
            "search_radius": search_radius,
            "contour_levels": contour_levels,
            "class_thresholds": thresholds,
            "facies_names": facies_names,
        },
        "records": records,
    }
    pipeline = GeologicalMappingPipeline()
    dataset = pipeline.extract_factors(
        records,
        factor_name,
        target_horizon=target_horizon,
        unit=unit,
        crs=crs,
    )
    case["extract"] = {
        "points": [
            {
                "well_id": p.well_id,
                "well_name": p.well_name,
                "x": p.x,
                "y": p.y,
                "value": p.value,
                "unit": p.unit,
                "qc_flag": p.qc_flag,
            }
            for p in dataset.points
        ],
        "valid_count": len(dataset.valid_points),
        "metadata": _clean(dataset.metadata),
    }

    options = InterpolationOptions(
        method=method,
        grid_n=grid_n,
        power=power,
        min_neighbors=min_neighbors,
        search_radius=search_radius,
        crs=crs,
    )
    if expected_error is not None:
        try:
            interpolate_factor(dataset, options)
        except ValueError as exc:
            case["error"] = str(exc)
            assert str(exc) == expected_error, (
                f"{name}: error text drifted: {exc!r}"
            )
            return case
        raise AssertionError(f"{name}: expected ValueError {expected_error!r}")

    result = interpolate_factor(dataset, options)
    case["grid"] = _grid_json(result)

    if contour_levels is not None:
        c_layer = generate_contour_layer(result, levels=list(contour_levels))
    else:
        c_layer = generate_contour_layer(result)
    case["contours"] = {
        "levels": [float(v) for v in (c_layer.levels or [])],
        "features": _clean(list(c_layer.features)),
        "feature_count": len(c_layer.features),
    }

    if facies_names is not None:
        p_layer = generate_facies_polygon_layer(
            result, thresholds=thresholds, facies_names=list(facies_names)
        )
    elif thresholds is not None:
        p_layer = generate_facies_polygon_layer(result, thresholds=thresholds)
    else:
        p_layer = generate_facies_polygon_layer(result)
    case["polygons"] = {
        "features": _clean(list(p_layer.features)),
        "feature_count": len(p_layer.features),
    }
    _repair_identity_guard(result, thresholds,
                           facies_names or ["低值相带", "中值相带", "高值相带"],
                           expect_features=len(p_layer.features) > 0)
    return case


def main() -> int:
    cases = {}

    # 1. The canonical 8-well IDW flow (user-flow acceptance case):
    #    explicit contour levels + explicit thresholds (mirrors
    #    test_contour_generation_marching_squares / test_facies_polygonization).
    cases["eight_well_idw"] = _run_case(
        "eight_well_idw", EIGHT_WELL_RECORDS, "孔隙度", None, "EPSG:4326", "T1",
        method="idw", grid_n=30, power=2.0,
        contour_levels=[15.0, 18.0, 21.0, 24.0],
        thresholds=[16.0, 22.0],
        facies_names=["致密相带", "常规储层", "优质甜点"],
    )

    # 2. Kriging branch + fully default levels/thresholds/names/colors
    #    (nice ladder 7, 1/3-2/3 span, 低值相带/中值相带/高值相带).
    cases["eight_well_kriging_defaults"] = _run_case(
        "eight_well_kriging_defaults", EIGHT_WELL_RECORDS, "孔隙度", None,
        "EPSG:4326", "T1",
        method="kriging", grid_n=20, power=2.0,
        contour_levels=None, thresholds=None, facies_names=None,
    )

    # 2b. The exact request the MainWindow 地质因子图 dialog issues for the
    #     builtin fixture (IDW, grid_n=30, default levels + thresholds +
    #     names + colors) — the E2E assertions pin THIS case's counts.
    cases["eight_well_idw_defaults"] = _run_case(
        "eight_well_idw_defaults", EIGHT_WELL_RECORDS, "孔隙度", None,
        "EPSG:4326", "T1",
        method="idw", grid_n=30, power=2.0,
        contour_levels=None, thresholds=None, facies_names=None,
    )

    # 3. QC filtering: W8 flagged bad -> 7 valid points interpolate; the
    #    extent still spans all 8 wells (models.extent includes every point).
    qc_records = [dict(r) for r in EIGHT_WELL_RECORDS]
    qc_records[7] = dict(qc_records[7], qc_flag="bad")
    cases["qc_filtered_idw"] = _run_case(
        "qc_filtered_idw", qc_records, "孔隙度", None, "EPSG:4326", "T1",
        method="idw", grid_n=24, power=2.0,
        contour_levels=[15.0, 18.0, 21.0, 24.0],
        thresholds=[16.0, 22.0],
        facies_names=["致密相带", "常规储层", "优质甜点"],
    )

    # 3b. Projected CRS (EPSG:3857 is in BOTH implementations' projected
    #     exception tables — the C++ kernel has no pyproj, so other
    #     projected ids stay honestly unverifiable): area_unit
    #     "{crs}-unit²", no area_approx_m2, verified-planar annotation.
    cases["projected_crs_idw"] = _run_case(
        "projected_crs_idw",
        [
            {"well_id": "A", "name": "A", "x": 512000.0, "y": 4120000.0, "value": 8.0},
            {"well_id": "B", "name": "B", "x": 514000.0, "y": 4120000.0, "value": 14.0},
            {"well_id": "C", "name": "C", "x": 512000.0, "y": 4123000.0, "value": 20.0},
            {"well_id": "D", "name": "D", "x": 514000.0, "y": 4123000.0, "value": 26.0},
        ],
        "value", None, "EPSG:3857", "T1",
        method="idw", grid_n=16, power=2.0,
        contour_levels=[10.0, 15.0, 20.0],
        thresholds=[12.0, 20.0],
        facies_names=["低值相", "中值相", "高值相"],
    )

    # 4. Undeclared CRS: distance policy falls back to planar with the
    #    honest unverified annotation; area_unit label unknown-unit².
    undeclared = [dict(r) for r in EIGHT_WELL_RECORDS]
    cases["undeclared_crs_idw"] = _run_case(
        "undeclared_crs_idw", undeclared, "孔隙度", None, "", "T1",
        method="idw", grid_n=20, power=2.0,
        contour_levels=[15.0, 18.0, 21.0, 24.0],
        thresholds=[16.0, 22.0],
        facies_names=["致密相带", "常规储层", "优质甜点"],
    )

    # 5. Failure branch: a single valid point must raise the exact Python
    #    validate() message (C++ std::invalid_argument text parity).
    cases["insufficient_points"] = _run_case(
        "insufficient_points", EIGHT_WELL_RECORDS[:1], "孔隙度", None,
        "EPSG:4326", "T1",
        method="idw", grid_n=20, power=2.0,
        contour_levels=None, thresholds=None, facies_names=None,
        expected_error=(
            "Insufficient sample points (1); at least 2 valid points "
            "required for spatial interpolation."
        ),
    )

    # 6. All-NaN grid through the real chain: min_neighbors above the sample
    #    count leaves every cell nodata -> 0 contour features, 0 polygons.
    cases["all_nodata_min_neighbors"] = _run_case(
        "all_nodata_min_neighbors",
        [
            {"well_id": "A", "name": "A", "x": 0.0, "y": 0.0, "value": 10.0},
            {"well_id": "B", "name": "B", "x": 10.0, "y": 10.0, "value": 20.0},
        ],
        "value", None, "", "T1",
        method="idw", grid_n=16, power=2.0, min_neighbors=3,
        contour_levels=None, thresholds=None, facies_names=None,
    )

    # 7. Partial NaN via a search radius that leaves the grid centre nodata
    #    while corner neighbourhoods carry gradients: contour/polygon
    #    features must skip NaN cells exactly like Python.
    cases["search_radius_partial_nan"] = _run_case(
        "search_radius_partial_nan",
        [
            {"well_id": "A", "name": "A", "x": 0.0, "y": 0.0, "value": 10.0},
            {"well_id": "B", "name": "B", "x": 10.0, "y": 0.0, "value": 50.0},
            {"well_id": "C", "name": "C", "x": 0.0, "y": 10.0, "value": 100.0},
            {"well_id": "D", "name": "D", "x": 10.0, "y": 10.0, "value": 200.0},
        ],
        "value", None, "", "T1",
        method="idw", grid_n=20, power=2.0, search_radius=6.5,
        contour_levels=[15.0, 100.0, 185.0],
        thresholds=[60.0, 140.0],
        facies_names=["低值相", "中值相", "高值相"],
    )

    # 8. Constant field: nice ladder empty (isclose vmin/vmax), default
    #    thresholds [vmin] -> exactly one polygon, area_percent 100.
    cases["constant_field_defaults"] = _run_case(
        "constant_field_defaults",
        [
            {"well_id": "A", "name": "A", "x": 0.0, "y": 0.0, "value": 20.0},
            {"well_id": "B", "name": "B", "x": 10.0, "y": 0.0, "value": 20.0},
            {"well_id": "C", "name": "C", "x": 0.0, "y": 10.0, "value": 20.0},
            {"well_id": "D", "name": "D", "x": 10.0, "y": 10.0, "value": 20.0},
        ],
        "value", None, "EPSG:4326", "T1",
        method="idw", grid_n=16, power=2.0,
        contour_levels=None, thresholds=None, facies_names=None,
    )

    # 9. Audit #1150 through the chain: a (0,0) well is a legal coordinate
    #    and mixed y-key records are skipped, not cross-paired.
    audit_records = [
        {"well_id": "W0", "name": "origin", "x": 0.0, "y": 0.0, "value": 12.0},
        {"well_id": "W1", "name": "w1", "x": 4.0, "y": 1.0, "value": 18.0},
        {"well_id": "BAD", "x": 2.0, "lat": 3.0, "value": 15.0},
    ]
    cases["zero_coordinate_kept"] = _run_case(
        "zero_coordinate_kept", audit_records, "value", None, "", "T1",
        method="idw", grid_n=20, power=2.0,
        contour_levels=[13.0, 15.0, 17.0],
        thresholds=[14.0, 16.0],
        facies_names=["低", "中", "高"],
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps({"generator": "generate_map_pipeline_fixtures.py",
                    "cases": cases}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"froze {len(cases)} cases -> {OUT}")
    for name, case in cases.items():
        n_c = case.get("contours", {}).get("feature_count", "-")
        n_p = case.get("polygons", {}).get("feature_count", "-")
        print(f"  {name}: contours={n_c} polygons={n_p} "
              f"error={case.get('error') is not None}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
