#!/usr/bin/env python3
"""Oracle fixture generator for the C++ interpolator kernel (M6).

Imports the REAL implementation (paleo_workbench.mapping.geological_pipeline.
interpolator) and freezes its outputs to JSON so the C++ port in
libs/mapping_kernel can be verified against the Python numerical core.
Regenerate with:

    python3 tools/oracle/generate_interpolator_fixtures.py

Kriging cases freeze ``_pure_numpy_kriging`` (the disclosed numpy-grid-OLS
fallback). The geoviz WLS engine is a different estimator and is not the
C++ kernel's oracle — matching the conversion plan's "pure algorithm core
first" rule. IDW cases freeze ``IDWInterpolator.interpolate`` / the
all-neighbour and kNN paths as the production engine runs them.
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

from paleo_workbench.mapping.geological_pipeline.interpolator import (  # noqa: E402
    IDWInterpolator,
    _apply_domain_options,
    _deduplicate_samples,
    _model_semivariance,
    _pure_numpy_kriging,
)
from paleo_workbench.mapping.geological_pipeline.models import (  # noqa: E402
    GeologicalFactor,
    GeologicalFactorDataset,
    InterpolationOptions,
)
from paleo_workbench.workflow.factor_grid_result import FactorGridResult  # noqa: E402

OUT = (
    REPO_ROOT
    / "libs"
    / "mapping_kernel"
    / "mapping_kernel_tests"
    / "fixtures"
)


def _dataset(name: str, points: list[tuple[float, float, float]],
             extra: list[GeologicalFactor] | None = None) -> GeologicalFactorDataset:
    ds = GeologicalFactorDataset(factor_name=name, unit="", crs="")
    for i, (x, y, z) in enumerate(points):
        ds.add_point(GeologicalFactor(
            name=name, value=z, x=x, y=y, well_id=f"W{i}", well_name=f"W{i}",
        ))
    if extra:
        for p in extra:
            ds.add_point(p)
    return ds


def _points_json(ds: GeologicalFactorDataset) -> list[list[float]]:
    return [[float(p.x), float(p.y), float(p.value)] for p in ds.points]


def _grid_json(arr: np.ndarray) -> list:
    """Row-major nested list; non-finite → null (JSON has no NaN)."""
    out = []
    for row in np.asarray(arr):
        if row.ndim == 0:
            v = float(row)
            out.append(None if not math.isfinite(v) else v)
            continue
        out.append([
            None if not math.isfinite(float(v)) else float(v) for v in row
        ])
    return out


def _axis_json(arr: np.ndarray) -> list[float]:
    return [float(v) for v in np.asarray(arr, dtype=np.float64)]


def _idw(ds: GeologicalFactorDataset, **kw) -> FactorGridResult:
    opts = InterpolationOptions(method="idw", **kw)
    return IDWInterpolator().interpolate(ds, opts)


def _krige_numpy(ds: GeologicalFactorDataset, **kw) -> tuple[np.ndarray, np.ndarray, dict, np.ndarray, np.ndarray]:
    opts = InterpolationOptions(method="kriging", **kw)
    xs, ys, zs = ds.to_arrays()
    xmin, ymin, xmax, ymax = ds.extent
    grid_n = max(10, int(opts.grid_n))
    grid_x = np.linspace(xmin, xmax, grid_n, dtype=np.float64)
    grid_y = np.linspace(ymin, ymax, grid_n, dtype=np.float64)
    grid_z, grid_var, params = _pure_numpy_kriging(
        xs, ys, zs, grid_x, grid_y,
        model=opts.variogram_model,
        max_neighbors=opts.max_neighbors,
        search_radius=opts.search_radius,
        min_neighbors=opts.min_neighbors,
    )
    result = FactorGridResult(
        grid_z=np.asarray(grid_z, dtype=np.float32),
        grid_x=grid_x,
        grid_y=grid_y,
        factor_name=ds.factor_name,
        algorithm_id="kriging",
        algorithm_parameters=dict(params),
        crs=ds.crs,
        unit=ds.unit,
        variance_grid=np.asarray(grid_var, dtype=np.float32),
    )
    result = _apply_domain_options(result, opts)
    return result, params, grid_x, grid_y


def _case_idw(cid: str, ds_name: str, ds: GeologicalFactorDataset, **kw) -> dict:
    opts = InterpolationOptions(method="idw", **kw)
    res = _idw(ds, **kw)
    if opts.boundary:
        res = _apply_domain_options(res, opts)
    return {
        "id": cid,
        "dataset": ds_name,
        "options": {
            "method": "idw",
            "grid_n": int(opts.grid_n),
            "power": float(opts.power),
            "min_neighbors": int(opts.min_neighbors),
            "max_neighbors": opts.max_neighbors,
            "search_radius": opts.search_radius,
            "boundary": (
                [[float(x), float(y)] for x, y in opts.boundary]
                if opts.boundary else None
            ),
        },
        "algorithm_id": res.algorithm_id,
        "grid_x": _axis_json(res.grid_x),
        "grid_y": _axis_json(res.grid_y),
        "grid_z": _grid_json(res.grid_z),
        "params": {
            "power": float(res.algorithm_parameters["power"]),
            "grid_n": int(res.algorithm_parameters["grid_n"]),
            "n_samples": int(res.algorithm_parameters["n_samples"]),
            "domain_masked_cells": int(
                res.algorithm_parameters.get("domain_masked_cells", 0)
            ),
        },
    }


def _case_krige(cid: str, ds_name: str, ds: GeologicalFactorDataset, **kw) -> dict:
    opts = InterpolationOptions(method="kriging", **kw)
    res, params, grid_x, grid_y = _krige_numpy(ds, **kw)
    return {
        "id": cid,
        "dataset": ds_name,
        "options": {
            "method": "kriging",
            "grid_n": int(opts.grid_n),
            "variogram_model": opts.variogram_model,
            "min_neighbors": int(opts.min_neighbors),
            "max_neighbors": opts.max_neighbors,
            "search_radius": opts.search_radius,
            "boundary": (
                [[float(x), float(y)] for x, y in opts.boundary]
                if opts.boundary else None
            ),
        },
        "algorithm_id": "kriging",
        "grid_x": _axis_json(res.grid_x),
        "grid_y": _axis_json(res.grid_y),
        "grid_z": _grid_json(res.grid_z),
        "variance": _grid_json(res.variance_grid),
        "params": {
            "method": params.get("method"),
            "model": params.get("model"),
            "range": float(params["range"]),
            "sill": float(params["sill"]),
            "nugget": float(params["nugget"]),
            "n_samples": int(params["n_samples"]),
            "duplicates_merged": int(params.get("duplicates_merged", 0)),
            "variogram_bins": int(params.get("variogram_bins", 0)),
            "variogram_fit": params.get("variogram_fit"),
            "domain_masked_cells": int(
                res.algorithm_parameters.get("domain_masked_cells", 0)
            ),
        },
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    wells8 = _dataset("porosity", [
        (114.10, 22.50, 18.5),
        (114.25, 22.52, 22.3),
        (114.38, 22.48, 15.2),
        (114.15, 22.65, 24.1),
        (114.30, 22.68, 19.8),
        (114.42, 22.62, 12.4),
        (114.20, 22.80, 26.5),
        (114.35, 22.82, 21.0),
    ])
    unit = _dataset("unit", [
        (0.0, 0.0, 1.0),
        (10.0, 0.0, 3.0),
        (0.0, 8.0, 2.0),
        (10.0, 8.0, 4.0),
        (4.0, 3.0, 2.5),
        (7.0, 6.0, 3.5),
    ])
    # Three clustered + one far — radius pruning / min_neighbors NaNs.
    sparse = _dataset("sparse", [
        (0.0, 0.0, 1.0),
        (0.4, 0.1, 1.2),
        (0.2, 0.5, 0.8),
        (20.0, 20.0, 9.0),
    ])
    constant = _dataset("constant", [
        (0.0, 0.0, 5.0),
        (1.0, 0.0, 5.0),
        (0.0, 1.0, 5.0),
        (1.0, 1.0, 5.0),
    ])
    # Two coincident samples + a distinct third (dedup on kriging path).
    dups = _dataset("dups", [
        (0.0, 0.0, 1.0),
        (0.0, 0.0, 3.0),  # mean 2.0 at origin
        (4.0, 3.0, 5.0),
        (1.0, 4.0, 4.0),
    ])
    # Exact-hit: a sample lands on a linspace node of the padded extent.
    exact_pts = [
        (0.0, 0.0, 10.0),
        (6.0, 0.0, 20.0),
        (0.0, 6.0, 30.0),
        (6.0, 6.0, 40.0),
    ]
    exact_ds = _dataset("exact", exact_pts)
    xmin, ymin, xmax, ymax = exact_ds.extent
    gx = np.linspace(xmin, xmax, 12)
    gy = np.linspace(ymin, ymax, 12)
    exact_ds.add_point(GeologicalFactor(
        name="exact", value=99.0, x=float(gx[4]), y=float(gy[7]),
        well_id="HIT", well_name="HIT",
    ))

    datasets = {
        "wells8": wells8,
        "unit": unit,
        "sparse": sparse,
        "constant": constant,
        "dups": dups,
        "exact": exact_ds,
    }

    ring = [(1.0, 1.0), (9.0, 1.0), (9.0, 7.0), (1.0, 7.0), (1.0, 1.0)]

    cases = [
        _case_idw("idw_wells8_n16_p2", "wells8", wells8, grid_n=16, power=2.0),
        _case_idw("idw_wells8_n12_p1", "wells8", wells8, grid_n=12, power=1.0),
        _case_idw("idw_wells8_n12_p3", "wells8", wells8, grid_n=12, power=3.0),
        _case_idw("idw_unit_n12", "unit", unit, grid_n=12, power=2.0),
        _case_idw("idw_knn3", "unit", unit, grid_n=12, power=2.0, max_neighbors=3),
        _case_idw("idw_radius", "sparse", sparse, grid_n=12, power=2.0,
                  search_radius=2.0),
        _case_idw("idw_min_neighbors", "sparse", sparse, grid_n=12, power=2.0,
                  search_radius=2.0, min_neighbors=3),
        _case_idw("idw_exact_hit", "exact", exact_ds, grid_n=12, power=2.0),
        _case_idw("idw_grid_n_clamp", "unit", unit, grid_n=3, power=2.0),
        _case_idw("idw_domain", "unit", unit, grid_n=14, power=2.0, boundary=ring),
        _case_krige("krige_unit_sph", "unit", unit, grid_n=12,
                    variogram_model="spherical"),
        _case_krige("krige_unit_exp", "unit", unit, grid_n=12,
                    variogram_model="exponential"),
        _case_krige("krige_unit_gau", "unit", unit, grid_n=12,
                    variogram_model="gaussian"),
        _case_krige("krige_wells8_sph", "wells8", wells8, grid_n=14,
                    variogram_model="spherical"),
        _case_krige("krige_constant", "constant", constant, grid_n=10,
                    variogram_model="spherical"),
        _case_krige("krige_dups", "dups", dups, grid_n=10,
                    variogram_model="spherical"),
        _case_krige("krige_knn3", "unit", unit, grid_n=12,
                    variogram_model="spherical", max_neighbors=3),
        _case_krige("krige_domain", "unit", unit, grid_n=12,
                    variogram_model="spherical", boundary=ring),
        _case_krige("krige_unknown_model", "unit", unit, grid_n=10,
                    variogram_model="not-a-model"),
    ]

    # Extent / validate / linspace / variogram units.
    empty = GeologicalFactorDataset(factor_name="empty")
    one = _dataset("one", [(2.0, 3.0, 1.0)])
    coloc = _dataset("coloc", [(1.0, 1.0, 1.0), (1.0, 1.0, 2.0)])
    same_x = _dataset("same_x", [(5.0, 0.0, 1.0), (5.0, 4.0, 2.0)])
    h = np.array([0.0, 0.5, 1.0, 2.0, 10.0], dtype=np.float64)
    dx, dy, dz, ndup = _deduplicate_samples(
        np.array([0.0, 0.0, 1.0, 1.0 + 1e-12], dtype=np.float64),
        np.array([0.0, 0.0, 1.0, 1.0], dtype=np.float64),
        np.array([1.0, 3.0, 5.0, 7.0], dtype=np.float64),
    )

    units = {
        "extent": [
            {"points": [], "result": list(empty.extent)},
            {"points": _points_json(one), "result": list(one.extent)},
            {"points": _points_json(same_x), "result": list(same_x.extent)},
            {"points": _points_json(wells8), "result": list(wells8.extent)},
            {"points": _points_json(unit), "result": list(unit.extent)},
        ],
        "validate": [
            {
                "points": [],
                "issues": empty.validate(),
            },
            {
                "points": _points_json(one),
                "issues": one.validate(),
            },
            {
                "points": _points_json(coloc),
                "issues": coloc.validate(),
            },
            {
                "points": _points_json(unit),
                "issues": unit.validate(),
            },
        ],
        "linspace": {
            "start": 114.10 - 0.032,
            "stop": 114.42 + 0.032,
            "num": 16,
            "result": [float(v) for v in np.linspace(
                114.10 - 0.032, 114.42 + 0.032, 16, dtype=np.float64)],
        },
        "semivariance": {
            "h": [float(v) for v in h],
            "nugget": 0.1,
            "psill": 2.0,
            "range": 5.0,
            "spherical": [float(v) for v in _model_semivariance(
                h, 0.1, 2.0, 5.0, "spherical")],
            "exponential": [float(v) for v in _model_semivariance(
                h, 0.1, 2.0, 5.0, "exponential")],
            "gaussian": [float(v) for v in _model_semivariance(
                h, 0.1, 2.0, 5.0, "gaussian")],
        },
        "dedup": {
            "x": [float(v) for v in dx],
            "y": [float(v) for v in dy],
            "z": [float(v) for v in dz],
            "duplicates": int(ndup),
        },
        "qc_filter": {
            "points": [
                [0.0, 0.0, 1.0],
                [1.0, 0.0, 2.0],
                [0.0, 1.0, float("nan")],
            ],
            "qc": ["ok", "bad", "ok"],
            "valid_count": 1,
        },
    }

    # QC-filter unit: one valid + one bad-qc + one non-finite value.
    qc_ds = GeologicalFactorDataset(factor_name="qc")
    qc_ds.add_point(GeologicalFactor(name="qc", value=1.0, x=0.0, y=0.0))
    qc_ds.add_point(GeologicalFactor(
        name="qc", value=2.0, x=1.0, y=0.0, qc_flag="bad"))
    qc_ds.add_point(GeologicalFactor(
        name="qc", value=float("nan"), x=0.0, y=1.0))
    units["qc_filter"]["points"] = [
        [float(p.x), float(p.y),
         None if not math.isfinite(p.value) else float(p.value)]
        for p in qc_ds.points
    ]
    units["qc_filter"]["valid_count"] = len(qc_ds.valid_points)
    units["qc_filter"]["issues"] = qc_ds.validate()

    doc = {
        "datasets": {name: {"points": _points_json(ds)}
                     for name, ds in datasets.items()},
        "cases": cases,
        "units": units,
    }
    target = OUT / "interpolator_oracle.json"
    target.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {target} ({target.stat().st_size} bytes, "
          f"{len(cases)} interpolation cases)")


if __name__ == "__main__":
    main()
