#!/usr/bin/env python3
"""Oracle fixture generator for the pwb_mapping_kernel pybind facade (CONV-20).

Imports the REAL Python implementations and freezes their outputs so the
pybind module (libs/mapping_bind/src/mapping_bind.cpp, wrapping the
libs/mapping_kernel cores) can be verified bridge-inclusive by
libs/mapping_bind/mapping_bind_tests/smoke.py. Regenerate with:

    <venv-python> libs/mapping_bind/oracle/generate_fixtures.py

Kriging cases run the pure dispatcher with ``sys.modules["geoviz"] = None``
(the golden-baseline convention from docs/development/geopipeline-v12), which
pins the numpy-grid-OLS fallback — the estimator the C++ kernel port actually
implements. With an importable geoviz engine the pure path would freeze a
DIFFERENT (WLS) estimator and the fixture would silently stop matching the
kernel. The three error-message cases and the class-grid cases are env-free.

NaN freezes as JSON null (no NaN literals in fixtures); floats keep Python
repr round-trip via json.dumps(ensure_ascii=False).
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

# Pin the numpy kriging fallback BEFORE any paleo import touches geoviz.
sys.modules.setdefault("geoviz", None)  # type: ignore[assignment]

from paleo_workbench.mapping.geological_pipeline.interpolator import (  # noqa: E402
    interpolate_factor,
)
from paleo_workbench.mapping.geological_pipeline.models import (  # noqa: E402
    GeologicalFactor,
    GeologicalFactorDataset,
    InterpolationOptions,
)
from paleo_workbench.mapping.well_prediction_surface import (  # noqa: E402
    nearest_neighbor_class_grid,
)
from paleo_workbench.mapping.geological_pipeline.pipeline import (  # noqa: E402
    GeologicalMappingPipeline,
)
OUT = (
    REPO_ROOT
    / "libs"
    / "mapping_bind"
    / "mapping_bind_tests"
    / "fixtures"
    / "bind_oracle.json"
)


def _dataset(
    points: list[tuple[float, float, float]],
    *,
    crs: str = "",
    extra: list[GeologicalFactor] | None = None,
) -> GeologicalFactorDataset:
    ds = GeologicalFactorDataset(factor_name="porosity", unit="%", crs=crs)
    for i, (x, y, z) in enumerate(points):
        ds.add_point(GeologicalFactor(
            name="porosity", value=z, x=x, y=y, unit="%", crs=crs,
            well_id=f"W{i}", well_name=f"W{i}",
        ))
    for p in extra or []:
        ds.add_point(p)
    return ds


def _samples_json(ds: GeologicalFactorDataset) -> list[dict]:
    """Point dicts exactly as the facade feeds the kernel (all points).

    Non-finite values freeze as null (JSON has no NaN); smoke.py maps null
    back to float('nan') before calling the module.
    """
    return [
        {"x": float(p.x), "y": float(p.y),
         "value": float(p.value) if math.isfinite(float(p.value)) else None,
         "qc_flag": p.qc_flag}
        for p in ds.points
    ]


def _flat_json(arr: np.ndarray) -> list:
    out = []
    for v in np.asarray(np.asarray(arr).reshape(-1)):
        f = float(v)
        out.append(None if not math.isfinite(f) else f)
    return out


def _options_json(ds: GeologicalFactorDataset,
                  options: InterpolationOptions) -> dict:
    return {
        "method": options.method,
        "grid_n": int(options.grid_n),
        "power": float(options.power),
        "min_neighbors": int(options.min_neighbors),
        "max_neighbors": options.max_neighbors,
        "search_radius": options.search_radius,
        "variogram_model": options.variogram_model,
        "boundary": (
            [[float(x), float(y)] for x, y in options.boundary]
            if options.boundary else None
        ),
        "crs": options.crs or ds.crs,
        "distance_policy": options.distance_policy,
    }


_UNIT_POINTS = [
    (0.0, 0.0, 1.0), (10.0, 0.0, 3.0), (0.0, 8.0, 2.0),
    (10.0, 8.0, 4.0), (4.0, 3.0, 2.5), (7.0, 6.0, 3.5),
]


def _interp_case(
    case_id: str,
    ds: GeologicalFactorDataset,
    options: InterpolationOptions,
) -> dict:
    result = interpolate_factor(ds, options)
    kernel_expect: dict = {
        "algorithm_id": result.algorithm_id,
        "grid_x": [float(v) for v in result.grid_x],
        "grid_y": [float(v) for v in result.grid_y],
        "grid_z": _flat_json(result.grid_z),
        "variance": (
            _flat_json(result.variance_grid)
            if result.variance_grid is not None else None
        ),
        "n_samples": int(result.algorithm_parameters["n_samples"]),
        "domain_masked_cells": int(
            result.algorithm_parameters.get("domain_masked_cells", 0)
        ),
        "distance_policy": result.algorithm_parameters["distance_policy"],
        "distance_policy_annotation":
            result.algorithm_parameters["distance_policy_annotation"],
        "statistics": result.statistics.to_dict(),
    }
    if options.method.lower() == "idw":
        kernel_expect["method"] = "idw"
        kernel_expect["power"] = float(result.algorithm_parameters["power"])
    else:
        kernel_expect["method"] = result.algorithm_parameters["method"]
        kernel_expect["model"] = result.algorithm_parameters["model"]
        kernel_expect["variogram_fit"] = \
            result.algorithm_parameters["variogram_fit"]
        kernel_expect["range"] = float(result.algorithm_parameters["range"])
        kernel_expect["sill"] = float(result.algorithm_parameters["sill"])
        kernel_expect["nugget"] = float(result.algorithm_parameters["nugget"])
        kernel_expect["duplicates_merged"] = int(
            result.algorithm_parameters["duplicates_merged"])
        kernel_expect["variogram_bins"] = int(
            result.algorithm_parameters["variogram_bins"])
    return {
        "id": case_id,
        "points": _samples_json(ds),
        "options": _options_json(ds, options),
        "expected": kernel_expect,
    }


def _opts(method: str = "idw", **kw) -> InterpolationOptions:
    return InterpolationOptions(method=method, **kw)


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)

    wells8 = _dataset([
        (114.10, 22.50, 18.5), (114.25, 22.52, 22.3), (114.38, 22.48, 15.2),
        (114.15, 22.65, 24.1), (114.30, 22.68, 19.8), (114.42, 22.62, 12.4),
        (114.20, 22.80, 26.5), (114.35, 22.82, 21.0),
    ])
    unit = _dataset(_UNIT_POINTS)
    sparse = _dataset([
        (0.0, 0.0, 1.0), (0.4, 0.1, 1.2), (0.2, 0.5, 0.8), (20.0, 20.0, 9.0),
    ])
    constant = _dataset([
        (0.0, 0.0, 5.0), (1.0, 0.0, 5.0), (0.0, 1.0, 5.0), (1.0, 1.0, 5.0),
    ])
    dups = _dataset([
        (0.0, 0.0, 1.0), (0.0, 0.0, 3.0), (4.0, 3.0, 5.0), (1.0, 4.0, 4.0),
    ])
    # Exact hit on a linspace node of the padded extent, plus a NaN-value
    # point that valid_points must drop.
    exact_base = [
        (0.0, 0.0, 10.0), (6.0, 0.0, 20.0), (0.0, 6.0, 30.0), (6.0, 6.0, 40.0),
    ]
    xmin, ymin, xmax, ymax = _dataset(exact_base).extent
    gx = np.linspace(xmin, xmax, 12)
    gy = np.linspace(ymin, ymax, 12)
    exact = _dataset(exact_base, extra=[GeologicalFactor(
        name="porosity", value=99.0, unit="%",
        x=float(gx[4]), y=float(gy[7]), well_id="HIT", well_name="HIT",
    )])
    qc_ds = _dataset(
        [(0.0, 0.0, 1.0), (10.0, 0.0, 3.0), (5.0, 5.0, 9.0)],
        extra=[
            GeologicalFactor(
                name="porosity", value=2.0, x=4.0, y=4.0, unit="%",
                well_id="WQ", well_name="WQ", qc_flag="bad",
            ),
            # NaN value passes construction (only x/y are finite-checked)
            # and must be dropped by valid_points on both paths.
            GeologicalFactor(
                name="porosity", value=float("nan"), x=7.0, y=7.0, unit="%",
                well_id="WN", well_name="WN",
            ),
        ],
    )

    ring = [(1.0, 1.0), (9.0, 1.0), (9.0, 7.0), (1.0, 7.0), (1.0, 1.0)]

    interp_cases = [
        _interp_case("idw_wells8_n16_p2", wells8, _opts(grid_n=16)),
        _interp_case("idw_wells8_n12_p1", wells8, _opts(grid_n=12, power=1.0)),
        _interp_case("idw_knn3", unit, _opts(grid_n=12, max_neighbors=3)),
        _interp_case("idw_radius", sparse, _opts(grid_n=12, search_radius=2.0)),
        _interp_case(
            "idw_radius_min3", sparse,
            _opts(grid_n=12, search_radius=2.0, min_neighbors=3)),
        _interp_case("idw_exact_hit", exact, _opts(grid_n=12)),
        _interp_case("idw_grid_n_clamp", unit, _opts(grid_n=3)),
        _interp_case("idw_domain", unit, _opts(grid_n=14, boundary=ring)),
        _interp_case("idw_qc_filter", qc_ds, _opts(grid_n=10)),
        _interp_case(
            "idw_crs_4326",
            _dataset(_UNIT_POINTS, crs="EPSG:4326"),
            _opts(grid_n=10)),
        _interp_case(
            "idw_crs_unknown",
            _dataset(_UNIT_POINTS, crs="EPSG:99999999"),
            _opts(grid_n=10)),
        _interp_case(
            "krige_unit_sph", unit, _opts("kriging", grid_n=12)),
        _interp_case(
            "krige_unit_exp", unit,
            _opts("kriging", grid_n=12, variogram_model="exponential")),
        _interp_case(
            "krige_wells8_gau", wells8,
            _opts("kriging", grid_n=14, variogram_model="gaussian")),
        _interp_case(
            "krige_constant", constant, _opts("kriging", grid_n=10)),
        _interp_case("krige_dups", dups, _opts("kriging", grid_n=10)),
        _interp_case(
            "krige_knn3", unit,
            _opts("kriging", grid_n=12, max_neighbors=3)),
        _interp_case(
            "krige_radius_min2", sparse,
            _opts("kriging", grid_n=12, search_radius=2.0, min_neighbors=2)),
        _interp_case(
            "krige_domain", unit,
            _opts("kriging", grid_n=12, boundary=ring)),
        _interp_case(
            "krige_unknown_model", unit,
            _opts("kriging", grid_n=10, variogram_model="not-a-model")),
    ]

    def _error(case_id: str, ds: GeologicalFactorDataset, **kw) -> dict:
        options = _opts(**kw)
        try:
            interpolate_factor(ds, options)
        except ValueError as exc:
            message = str(exc)
        else:
            raise AssertionError(f"{case_id}: expected ValueError")
        return {
            "id": case_id,
            "points": _samples_json(ds),
            "options": _options_json(ds, options),
            "expected": {"error": message},
        }

    err_empty = _dataset([])
    err_single = _dataset([(2.0, 3.0, 1.0)])
    err_collocated = _dataset([(1.0, 1.0, 1.0), (1.0, 1.0, 2.0)])
    error_cases = [
        _error("err_empty", err_empty, method="idw", grid_n=10),
        _error("err_single", err_single, method="idw", grid_n=10),
        _error("err_collocated", err_collocated, method="idw", grid_n=10),
        _error(
            "err_boundary_short", unit, method="idw", grid_n=10,
            boundary=[(0.0, 0.0), (1.0, 1.0)]),
        _error(
            "err_bad_policy", unit, method="idw", grid_n=10,
            crs="", distance_policy="furlongs"),
    ]

    # ------------------------------------------------------------- extract ----
    pipeline = GeologicalMappingPipeline()

    def _extract_case(case_id, records, factor_name, *, target_horizon="",
                      unit=None, crs=""):
        ds = pipeline.extract_factors(
            records, factor_name, target_horizon=target_horizon,
            unit=unit, crs=crs)
        return {
            "id": case_id,
            "records": records,
            "factor_name": factor_name,
            "target_horizon": target_horizon,
            "unit": unit,
            "crs": crs,
            "expected": {
                "factor_name": ds.factor_name,
                "unit": ds.unit,
                "target_horizon": ds.target_horizon,
                "crs": ds.crs,
                "points": [
                    {
                        "name": p.name, "value": float(p.value),
                        "unit": p.unit, "well_id": p.well_id,
                        "well_name": p.well_name, "x": float(p.x),
                        "y": float(p.y), "crs": p.crs,
                        "formation": p.formation, "qc_flag": p.qc_flag,
                        "metadata": p.metadata,
                    }
                    for p in ds.points
                ],
                "metadata": ds.metadata,
            },
        }

    extract_cases = [
        _extract_case(
            "extract_aliases", [
                {"well_id": "W1", "x": 1.0, "y": 2.0, "POR": 18.5},
                {"well_id": "W2", "x": 2.0, "y": 3.0, "porosity": 22.1},
                {"well_id": "W3", "x": 3.0, "y": 4.0, "孔隙度": 15.3},
            ], "porosity"),
        _extract_case(
            "extract_zero_coordinates", [
                {"well_id": "W0", "x": 0.0, "y": 0.0, "value": 7.5},
            ], "porosity"),
        _extract_case(
            "extract_family_isolation", [
                {"well_id": "W1", "x": 114.0, "lat": 22.5, "value": 5.0},
            ], "porosity"),
        _extract_case(
            "extract_project_priority", [
                {"well_id": "W1", "project_x": 500000.0, "project_y": 3400000.0,
                 "x": 1.0, "y": 2.0, "value": 5.0},
            ], "porosity"),
        _extract_case(
            "extract_mixed_families", [
                {"well_id": "W1", "project_x": 1.0, "project_y": 2.0,
                 "value": 5.0},
                {"well_id": "W2", "lng": 114.0, "lat": 22.5, "value": 6.0},
            ], "porosity"),
        _extract_case(
            "extract_derived_sand_ratio", [
                {"well_id": "W1", "x": 1.0, "y": 2.0,
                 "H_s": 4.0, "H_t": 8.0},
            ], "砂地比"),
        _extract_case(
            "extract_derived_thickness", [
                {"well_id": "W1", "x": 1.0, "y": 2.0,
                 "base_depth": 120.0, "top_depth": 80.0},
            ], "formation_thickness"),
        _extract_case(
            "extract_invalid_coordinates", [
                {"well_id": "W1", "x": "N/A", "y": 2.0, "value": 5.0},
                {"well_id": "W2", "x": 2.0, "y": 3.0, "value": 6.0},
            ], "porosity"),
        _extract_case(
            "extract_unit_table", [
                {"well_id": "W1", "x": 1.0, "y": 2.0, "value": 5.0},
            ], "porosity"),
        _extract_case(
            "extract_unit_explicit_empty", [
                {"well_id": "W1", "x": 1.0, "y": 2.0, "value": 5.0},
            ], "porosity", unit=""),
        _extract_case(
            "extract_nested_value", [
                {"well_id": "W1", "x": 1.0, "y": 2.0,
                 "attributes": {"value": 12.5}},
            ], "porosity"),
        _extract_case(
            "extract_nested_factor_name", [
                {"well_id": "W1", "x": 1.0, "y": 2.0,
                 "attributes": {"porosity": 11.5}},
            ], "porosity"),
        _extract_case(
            "extract_coordinates_list", [
                {"well_id": "W1", "coordinates": [3.0, 4.0], "val": 8.25},
            ], "porosity"),
        _extract_case(
            "extract_target_horizon", [
                {"well_id": "W1", "x": 1.0, "y": 2.0, "value": 5.0,
                 "formation": "Es3"},
                {"well_id": "W2", "x": 2.0, "y": 3.0, "value": 6.0},
            ], "porosity", target_horizon="Es3"),
        _extract_case(
            "extract_well_fallbacks", [
                {"id": "ONLY_ID", "x": 1.0, "y": 2.0, "value": 5.0},
                {"name": "Only Name", "x": 2.0, "y": 3.0, "value": 6.0},
            ], "porosity"),
        _extract_case(
            "extract_non_dict_skipped", [
                "not-a-record",
                {"well_id": "W1", "x": 1.0, "y": 2.0, "value": 5.0},
            ], "porosity"),
        _extract_case(
            "extract_qc_and_properties", [
                {"well_id": "W1", "x": 1.0, "y": 2.0, "value": 5.0,
                 "qc_flag": "good",
                 "properties": {"source": "core", "reliability": 0.9}},
            ], "porosity"),
        _extract_case("extract_empty_records", [], "porosity"),
    ]

    # ---------------------------------------------------------- class grid ----
    def _class_case(case_id, pts, extent, grid_n=80, clip_ring=None):
        from paleo_workbench.mapping.well_prediction_surface import (
            WellFaciesPoint,
        )

        grid_z, grid_x, grid_y, names = nearest_neighbor_class_grid(
            [WellFaciesPoint(x=x, y=y, facies=f) for x, y, f in pts],
            extent=extent, grid_n=grid_n, clip_ring=clip_ring)
        return {
            "id": case_id,
            "points": [
                {"x": float(x), "y": float(y), "facies": f}
                for x, y, f in pts
            ],
            "extent": [float(v) for v in extent],
            "grid_n": int(grid_n),
            "clip_ring": (
                [[float(x), float(y)] for x, y in clip_ring]
                if clip_ring else None),
            "expected": {
                "grid_x": [float(v) for v in grid_x],
                "grid_y": [float(v) for v in grid_y],
                "grid_z": _flat_json(grid_z),
                "facies_names": list(names),
            },
        }

    class_cases = [
        _class_case(
            "class_two_facies", [
                (1.0, 1.0, "三角洲"), (9.0, 1.0, "滨浅湖"),
                (5.0, 8.0, "三角洲"),
            ], (0.0, 0.0, 10.0, 9.0), grid_n=5),
        _class_case(
            "class_single_facies", [(4.0, 4.0, "浅海")],
            (0.0, 0.0, 8.0, 8.0), grid_n=4),
        _class_case(
            "class_clip_inclusive", [
                (3.0, 3.0, "三角洲"), (7.0, 7.0, "滨浅湖"),
            ], (0.0, 0.0, 10.0, 10.0), grid_n=5,
            clip_ring=[(2.5, 2.5), (7.5, 2.5), (7.5, 7.5), (2.5, 7.5),
                       (2.5, 2.5)]),
        _class_case(
            "class_grid_n_clamp", [(1.0, 1.0, "A")],
            (0.0, 0.0, 2.0, 2.0), grid_n=1),
        _class_case(
            "class_tie_first_seen", [
                (0.0, 0.0, "A"), (0.0, 10.0, "B"),
            ], (-5.0, -5.0, 5.0, 15.0), grid_n=3),
    ]

    try:
        nearest_neighbor_class_grid([], extent=(0.0, 0.0, 1.0, 1.0))
        raise AssertionError("expected ValueError for empty class grid")
    except ValueError as exc:
        class_empty_error = str(exc)

    doc = {
        "interp": {"cases": interp_cases, "errors": error_cases},
        "extract": {"cases": extract_cases},
        "class_grid": {
            "cases": class_cases,
            "empty_error": class_empty_error,
        },
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    print(
        f"wrote {OUT} ({OUT.stat().st_size} bytes; "
        f"{len(interp_cases)} interp + {len(error_cases)} interp errors + "
        f"{len(extract_cases)} extract + {len(class_cases)} class cases)")


if __name__ == "__main__":
    main()
