#!/usr/bin/env python3
"""Oracle fixture generator for the C++ polygonization kernel (M6 slice 3).

Imports the REAL implementation
(paleo_workbench.mapping.geological_pipeline.polygonization) and freezes its
numerical outputs to JSON so the C++ port in libs/mapping_kernel can be
verified sample-exactly. Regenerate with:

    python3 tools/oracle/generate_polygonization_fixtures.py

Shapely repair is OUT OF SCOPE for this kernel. The generator monkeypatches
``paleo_workbench.mapping.geological_pipeline.polygonization.repair_invalid_geometry``
to identity so the freeze is the pure raster-trace / hole-assignment kernel
(no make_valid / orient). Clip-to-ring and GIS feature packing are not frozen.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import paleo_workbench.mapping.geological_pipeline.polygonization as poly  # noqa: E402
from paleo_workbench.workflow.factor_grid_result import FactorGridResult  # noqa: E402

OUT = (
    REPO_ROOT
    / "libs"
    / "mapping_kernel"
    / "mapping_kernel_tests"
    / "fixtures"
)


def _identity_repair(geom):
    """Leave GeoJSON polygons untouched (C++ kernel has no shapely repair)."""
    return geom


poly.repair_invalid_geometry = _identity_repair


def _grid_json(z: np.ndarray) -> list:
    out = []
    for row in np.asarray(z, dtype=np.float64):
        out.append([
            None if not math.isfinite(float(v)) else float(v) for v in row
        ])
    return out


def _axis_json(arr: np.ndarray) -> list[float]:
    return [float(v) for v in np.asarray(arr, dtype=np.float64)]


def _class_json(arr: np.ndarray) -> list[list[int]]:
    return [[int(v) for v in row] for row in np.asarray(arr)]


def _ring_json(ring) -> list[list[float]]:
    return [[float(p[0]), float(p[1])] for p in ring]


def _polys_json(geoms: list[dict]) -> list[dict]:
    out = []
    for geom in geoms:
        coords = geom.get("coordinates") or []
        if not coords:
            continue
        out.append({
            "exterior": _ring_json(coords[0]),
            "holes": [_ring_json(h) for h in coords[1:]],
        })
    return out


def _make_axes(h: int, w: int, extent: tuple[float, float, float, float]):
    xmin, ymin, xmax, ymax = extent
    x = np.linspace(xmin, xmax, w, dtype=np.float64)
    y = np.linspace(ymin, ymax, h, dtype=np.float64)
    return x, y


def _extent_of(x: np.ndarray, y: np.ndarray) -> tuple[float, float, float, float]:
    """FactorGridResult.extent: axis min/max (not linspace spacing)."""
    return (float(np.min(x)), float(np.min(y)), float(np.max(x)), float(np.max(y)))


def _facies_thresholds(z: np.ndarray, thresholds):
    """Classification block copied from generate_facies_polygon_layer."""
    finite = z[np.isfinite(z)]
    vmin, vmax = float(finite.min()), float(finite.max())
    thresholds_is_explicit = thresholds is not None
    if thresholds is None:
        if math.isclose(vmin, vmax):
            th = [vmin]
        else:
            th = [vmin + (vmax - vmin) * 0.333, vmin + (vmax - vmin) * 0.666]
    else:
        th = sorted(set(float(t) for t in thresholds))
    if len(th) == 2:
        n_names = 3
    elif len(th) == 1 and math.isclose(vmin, vmax):
        n_names = 1
    else:
        n_names = len(th) + 1
    h, w = z.shape
    class_grid = np.zeros((h, w), dtype=np.int16)
    for idx, t in enumerate(th):
        class_grid[z >= t] = min(idx + 1, n_names - 1)
    return {
        "thresholds": [float(t) for t in th],
        "n_classes": int(n_names),
        "vmin": vmin,
        "vmax": vmax,
        "thresholds_source": (
            "explicit" if thresholds_is_explicit else "data_derived_default"
        ),
        "class_grid": _class_json(class_grid),
    }


def _factor_result(z: np.ndarray, x: np.ndarray, y: np.ndarray) -> FactorGridResult:
    return FactorGridResult(
        grid_z=z,
        grid_x=x,
        grid_y=y,
        factor_name="oracle",
        algorithm_id="idw",
        crs="",
        unit="",
    )


def _grids() -> dict[str, dict]:
    # Compact integer-friendly extents so pt_key round(,6) is the identity.
    islands_z = np.zeros((10, 10), dtype=np.float64)
    islands_z[1:4, 1:4] = 8.0
    islands_z[6:9, 6:9] = 3.0
    islands_z[2:4, 7:9] = 5.0

    donut_z = np.zeros((10, 10), dtype=np.float64)
    donut_z[2:8, 2:8] = 4.0
    donut_z[4:6, 4:6] = 0.0

    nested_z = np.zeros((12, 12), dtype=np.float64)
    nested_z[1:11, 1:11] = 4.0
    nested_z[3:9, 3:9] = 0.0
    nested_z[5:7, 5:7] = 4.0

    single_z = np.zeros((8, 8), dtype=np.float64)
    single_z[3, 4] = 7.0

    nodata_z = np.zeros((8, 8), dtype=np.float64)
    nodata_z[1:6, 1:6] = 2.0
    nodata_z[0, 0] = np.nan
    nodata_z[3:5, 3:5] = np.nan

    ramp = np.arange(8, dtype=np.float64)[None, :] + np.arange(8, dtype=np.float64)[:, None]

    constant = np.full((8, 8), 5.0)

    yy, xx = np.ogrid[:12, :12]
    dist_sq = (xx - 5.5) ** 2 + (yy - 5.5) ** 2
    ring_z = np.where(dist_sq <= 4, 10.0, np.where(dist_sq <= 16, 2.0, 10.0)).astype(
        np.float64
    )

    # Two-row / two-col strips (a 1-row linspace axis collapses ymin==ymax
    # and yields zero-area rings that the kernel skips).
    strip_z = np.array(
        [
            [0.0, 1.0, 1.0, 1.0, 0.0, 2.0, 2.0, 0.0],
            [0.0, 1.0, 1.0, 1.0, 0.0, 2.0, 2.0, 0.0],
        ],
        dtype=np.float64,
    )
    col_z = np.array(
        [
            [0.0, 0.0],
            [1.0, 1.0],
            [1.0, 1.0],
            [0.0, 0.0],
            [2.0, 2.0],
            [2.0, 2.0],
            [2.0, 2.0],
            [0.0, 0.0],
        ],
        dtype=np.float64,
    )
    degen_z = np.array([[0.0, 1.0, 1.0, 1.0, 0.0, 2.0, 2.0, 0.0]], dtype=np.float64)

    fields = {
        "islands": {"z": islands_z, "extent": (0.0, 0.0, 10.0, 10.0)},
        "donut": {"z": donut_z, "extent": (0.0, 0.0, 10.0, 10.0)},
        "nested": {"z": nested_z, "extent": (0.0, 0.0, 12.0, 12.0)},
        "single": {"z": single_z, "extent": (0.0, 0.0, 8.0, 8.0)},
        "nodata": {"z": nodata_z, "extent": (0.0, 0.0, 8.0, 8.0)},
        "ramp": {"z": ramp, "extent": (0.0, 0.0, 8.0, 8.0)},
        "constant": {"z": constant, "extent": (0.0, 0.0, 8.0, 8.0)},
        "ring": {"z": ring_z, "extent": (0.0, 0.0, 12.0, 12.0)},
        "strip": {"z": strip_z, "extent": (0.0, 0.0, 8.0, 2.0)},
        "column": {"z": col_z, "extent": (0.0, 0.0, 2.0, 8.0)},
        "degen": {"z": degen_z, "extent": (0.0, 0.0, 8.0, 1.0)},
    }

    # Hunt a compact binary grid whose hole-assignment promotes a ring.
    promote = None
    for seed in range(400):
        rng = np.random.default_rng(seed)
        z = (rng.random((8, 8)) >= 0.45).astype(np.float64)
        x, y = _make_axes(8, 8, (0.0, 0.0, 8.0, 8.0))
        cg = (z >= 0.5).astype(np.int16)
        _, qc = poly._polygonize_raster_boundaries(
            cg, z, _extent_of(x, y), 1
        )
        if qc["holes_promoted_to_exterior"] > 0:
            promote = z
            fields["promote"] = {"z": promote, "extent": (0.0, 0.0, 8.0, 8.0)}
            fields["promote_seed"] = seed  # marker; stripped below
            break
    if promote is None:
        # Fallback: a 1-cell-wide frame plus a disjoint blob. Still freezes
        # the promotion counter (likely 0) so C++ must match.
        z = np.zeros((8, 8), dtype=np.float64)
        z[0, :] = 1.0
        z[-1, :] = 1.0
        z[:, 0] = 1.0
        z[:, -1] = 1.0
        z[3:5, 3:5] = 1.0
        fields["promote"] = {"z": z, "extent": (0.0, 0.0, 8.0, 8.0)}

    out = {}
    promote_seed = fields.pop("promote_seed", None)
    for name, spec in fields.items():
        z = spec["z"]
        h, w = z.shape
        x, y = _make_axes(h, w, spec["extent"])
        out[name] = {
            "x": x,
            "y": y,
            "z": z,
            "extent": list(_extent_of(x, y)),
        }
    if promote_seed is not None:
        out["promote"]["seed"] = int(promote_seed)
    return out


def _units() -> dict:
    sq_ccw = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]
    sq_cw = list(reversed(sq_ccw))
    tri = [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [0.0, 0.0]]
    degenerate = [[1.0, 2.0], [3.0, 2.0], [5.0, 2.0], [1.0, 2.0]]
    collinear_h = [
        [0.0, 0.0], [1.0, 0.0], [2.0, 0.0], [3.0, 0.0],
        [3.0, 2.0], [0.0, 2.0], [0.0, 0.0],
    ]
    collinear_v = [
        [0.0, 0.0], [2.0, 0.0], [2.0, 1.0], [2.0, 2.0], [2.0, 3.0],
        [0.0, 3.0], [0.0, 2.0], [0.0, 1.0], [0.0, 0.0],
    ]
    diagonal = [
        [0.0, 0.0], [1.0, 1.0], [2.0, 2.0], [2.0, 0.0], [0.0, 0.0],
    ]
    backtrack = [
        [0.0, 0.0], [2.0, 0.0], [1.0, 0.0], [2.0, 2.0], [0.0, 2.0], [0.0, 0.0],
    ]
    short = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 0.0]]
    unclosed = [[0.0, 0.0], [2.0, 0.0], [2.0, 2.0]]

    small = {
        "type": "Polygon",
        "coordinates": [
            [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]
        ],
    }
    large = {
        "type": "Polygon",
        "coordinates": [
            [[0.0, 0.0], [4.0, 0.0], [4.0, 4.0], [0.0, 4.0], [0.0, 0.0]],
            [[1.0, 1.0], [1.0, 2.0], [2.0, 2.0], [2.0, 1.0], [1.0, 1.0]],
        ],
    }
    kept, dropped = poly._filter_small_polygons([small, large], 2.0)
    kept0, dropped0 = poly._filter_small_polygons([small, large], 0.0)
    kept_eq, dropped_eq = poly._filter_small_polygons([small], 1.0)

    return {
        "shoelace": [
            {"ring": sq_ccw, "result": float(poly.calculate_shoelace_area(sq_ccw))},
            {"ring": sq_cw, "result": float(poly.calculate_shoelace_area(sq_cw))},
            {"ring": tri, "result": float(poly.calculate_shoelace_area(tri))},
            {"ring": [[0.0, 0.0], [1.0, 0.0]],
             "result": float(poly.calculate_shoelace_area([[0.0, 0.0], [1.0, 0.0]]))},
            {"ring": unclosed, "result": float(poly.calculate_shoelace_area(unclosed))},
        ],
        "signed": [
            {"ring": sq_ccw, "result": float(poly.calculate_signed_area(sq_ccw))},
            {"ring": sq_cw, "result": float(poly.calculate_signed_area(sq_cw))},
            {"ring": tri, "result": float(poly.calculate_signed_area(tri))},
            {"ring": unclosed, "result": float(poly.calculate_signed_area(unclosed))},
        ],
        "centroid": [
            {"ring": sq_ccw, "result": [float(v) for v in poly.ring_area_centroid(sq_ccw)]},
            {"ring": tri, "result": [float(v) for v in poly.ring_area_centroid(tri)]},
            {"ring": degenerate,
             "result": [float(v) for v in poly.ring_area_centroid(degenerate)]},
            {"ring": [], "result": [float(v) for v in poly.ring_area_centroid([])]},
            {"ring": [[4.0, 5.0]],
             "result": [float(v) for v in poly.ring_area_centroid([[4.0, 5.0]])]},
        ],
        "simplify": [
            {"ring": collinear_h,
             "result": poly.simplify_collinear_ring(collinear_h)},
            {"ring": collinear_v,
             "result": poly.simplify_collinear_ring(collinear_v)},
            {"ring": diagonal, "result": poly.simplify_collinear_ring(diagonal)},
            {"ring": backtrack, "result": poly.simplify_collinear_ring(backtrack)},
            {"ring": short, "result": poly.simplify_collinear_ring(short)},
        ],
        "filter": {
            "geoms": _polys_json([small, large]),
            "min_area": 2.0,
            "kept": _polys_json(kept),
            "dropped": int(dropped),
            "min_area_zero_dropped": int(dropped0),
            "min_area_equal_dropped": int(dropped_eq),
            "equal_geoms": _polys_json([small]),
            "min_area_equal_kept": _polys_json(kept_eq),
        },
        "default_thresholds": [
            {"vmin": 0.0, "vmax": 9.0,
             "result": (
                 [0.0 + 9.0 * 0.333, 0.0 + 9.0 * 0.666]
                 if not math.isclose(0.0, 9.0)
                 else [0.0]
             )},
            {"vmin": 5.0, "vmax": 5.0, "result": [5.0]},
            {"vmin": 1.0, "vmax": 1.0 + 1e-16,
             "result": (
                 [1.0]
                 if math.isclose(1.0, 1.0 + 1e-16)
                 else [1.0 + (1e-16) * 0.333, 1.0 + (1e-16) * 0.666]
             )},
        ],
        "unique_thresholds": {
            "input": [3.0, 1.0, 2.0, 1.0, 2.0, 0.5],
            "result": sorted(set(float(t) for t in [3.0, 1.0, 2.0, 1.0, 2.0, 0.5])),
        },
    }


def _polygonize_case(cid: str, name: str, g: dict, target: int,
                     class_grid: np.ndarray) -> dict:
    geoms, qc = poly._polygonize_raster_boundaries(
        class_grid, g["z"], tuple(g["extent"]), target
    )
    return {
        "id": cid,
        "kind": "polygonize",
        "grid": name,
        "target_class": int(target),
        "class_grid": _class_json(class_grid),
        "polygons": _polys_json(geoms),
        "holes_promoted_to_exterior": int(qc["holes_promoted_to_exterior"]),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    grids = _grids()
    cases: list[dict] = []

    # Classification: default 1/3–2/3, explicit, constant field, nodata.
    for name, th in (
        ("ramp", None),
        ("ramp", [4.0, 8.0, 4.0]),
        ("constant", None),
        ("constant", [5.0]),
        ("nodata", None),
        ("ring", [5.0]),
        ("islands", [1.0, 6.0]),
    ):
        g = grids[name]
        info = _facies_thresholds(g["z"], th)
        cases.append({
            "id": f"classify_{name}_{info['thresholds_source']}",
            "kind": "classify",
            "grid": name,
            "thresholds_in": None if th is None else [float(t) for t in th],
            **info,
        })

    # Raster polygonize: islands, donut, nested (island in lake), nodata,
    # single-cell, strip, promote, each present class.
    raster_specs = [
        ("islands", (grids["islands"]["z"] > 0).astype(np.int16), [1]),
        ("donut", (grids["donut"]["z"] > 0).astype(np.int16), [1]),
        ("nested", (grids["nested"]["z"] > 0).astype(np.int16), [1]),
        ("single", (grids["single"]["z"] > 0).astype(np.int16), [1]),
        ("nodata", np.where(np.isfinite(grids["nodata"]["z"])
                            & (grids["nodata"]["z"] > 0), 1, 0).astype(np.int16), [1]),
        ("ring", (grids["ring"]["z"] >= 5.0).astype(np.int16), [0, 1]),
        ("strip", (grids["strip"]["z"] >= 1.0).astype(np.int16), [1]),
        ("column", (grids["column"]["z"] >= 1.0).astype(np.int16), [1]),
        ("degen", (grids["degen"]["z"] >= 1.0).astype(np.int16), [1]),
        ("promote", (grids["promote"]["z"] >= 0.5).astype(np.int16), [1]),
        ("constant", np.ones((8, 8), dtype=np.int16), [1]),
    ]
    for name, class_grid, targets in raster_specs:
        for target in targets:
            cases.append(_polygonize_case(
                f"poly_{name}_c{target}", name, grids[name], target, class_grid
            ))

    # polygonize_factor_grid: default median + explicit level.
    for name, level in (("ramp", None), ("ramp", 7.0), ("islands", None),
                        ("nodata", None), ("constant", None)):
        g = grids[name]
        res = _factor_result(g["z"], g["x"], g["y"])
        out = poly.polygonize_factor_grid(res, level=level)
        cases.append({
            "id": f"factor_{name}_{'median' if level is None else 'level'}",
            "kind": "factor",
            "grid": name,
            "level_in": None if level is None else float(level),
            "level": float(out["level"]),
            "n_polygons": int(out["n_polygons"]),
            "holes_promoted_to_exterior": int(out["counts"]["holes_promoted_to_exterior"]),
            "polygons": _polys_json(out["polygons"]),
        })

    doc = {
        "grids": {
            name: {
                "x": _axis_json(g["x"]),
                "y": _axis_json(g["y"]),
                "z": _grid_json(g["z"]),
                "extent": g["extent"],
                **({"seed": g["seed"]} if "seed" in g else {}),
            }
            for name, g in grids.items()
        },
        "cases": cases,
        "units": _units(),
    }
    target = OUT / "polygonization_oracle.json"
    target.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    n_poly = sum(1 for c in cases if c["kind"] == "polygonize")
    n_cls = sum(1 for c in cases if c["kind"] == "classify")
    n_fac = sum(1 for c in cases if c["kind"] == "factor")
    promoted = [
        (c["id"], c["holes_promoted_to_exterior"])
        for c in cases
        if c.get("holes_promoted_to_exterior", 0)
    ]
    print(
        f"wrote {target} ({target.stat().st_size} bytes, "
        f"{n_poly} polygonize + {n_cls} classify + {n_fac} factor cases)"
    )
    if promoted:
        print("holes_promoted_to_exterior:", promoted)
    else:
        print("holes_promoted_to_exterior: none in raster cases")
    if "seed" in grids.get("promote", {}):
        print("promote grid seed:", grids["promote"]["seed"])


if __name__ == "__main__":
    main()
