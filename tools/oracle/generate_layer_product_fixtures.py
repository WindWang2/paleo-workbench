#!/usr/bin/env python3
"""Oracle fixture generator for the CONV-03 layer-products slice.

Imports the REAL implementations
(paleo_workbench.mapping.geological_pipeline.contouring /
.polygonization) and freezes the full GeoJSON feature packing of
``generate_contour_layer`` / ``generate_facies_polygon_layer`` — geometry,
properties (Python dict key order), levels and QC metadata — to JSON so the
C++ port in libs/mapping_kernel/src/layer_products.cpp can be verified
sample-exactly.  Regenerate with:

    python3 tools/oracle/generate_layer_product_fixtures.py

Shapely repair is OUT OF SCOPE (same discipline as the polygonization
oracle): ``repair_invalid_geometry`` is monkeypatched to identity, so the
freeze is the raw raster-trace geometry.  Clip-to-ring is not frozen: the
Python clip kernels hard-require shapely and the C++ slice does not carry a
clip parameter (documented in
docs/development/cpp-conversion-swarm-20/ledgers/03-decisions.md).  Styles
(layer ``style`` / ``categories``) are UI data and are not frozen either.
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
from paleo_workbench.mapping.geological_pipeline.contouring import (  # noqa: E402
    generate_contour_layer,
)
from paleo_workbench.mapping.geological_pipeline.polygonization import (  # noqa: E402
    generate_facies_polygon_layer,
)
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


def _make_axes(h: int, w: int, extent: tuple[float, float, float, float]):
    xmin, ymin, xmax, ymax = extent
    x = np.linspace(xmin, xmax, w, dtype=np.float64)
    y = np.linspace(ymin, ymax, h, dtype=np.float64)
    return x, y


def _grid(name: str, z: np.ndarray, extent, *, crs="", unit="",
          factor="oracle") -> dict:
    h, w = z.shape
    x, y = _make_axes(h, w, extent)
    return {
        "name": name,
        "z": z,
        "x": x,
        "y": y,
        "extent": extent,
        "crs": crs,
        "unit": unit,
        "factor": factor,
    }


def _grids() -> dict[str, dict]:
    grids: list[dict] = []

    # Diagonal ramp: nice/interval/quantile ladders + default facies bands.
    ramp = (np.arange(8, dtype=np.float64)[None, :]
            + np.arange(8, dtype=np.float64)[:, None])
    grids.append(_grid("ramp8", ramp, (0.0, 0.0, 8.0, 8.0), unit="m"))

    # #977 regression (test_gis_mapping_batch5): 4x4 diagonal ramp splits one
    # facies band into two corner components -> 4 polygons / 3 names.
    batch = np.array(
        [
            [0.1, 0.2, 0.3, 0.4],
            [0.2, 0.3, 0.5, 0.6],
            [0.3, 0.5, 0.7, 0.8],
            [0.4, 0.6, 0.8, 0.9],
        ],
        dtype=np.float64,
    )
    grids.append(_grid("batch4", batch, (500000.0, 3400000.0, 520000.0, 3420000.0),
                       factor="砂岩厚度"))

    # Islands / donut / nested rings (same shapes as the polygonization oracle).
    islands = np.zeros((10, 10), dtype=np.float64)
    islands[1:4, 1:4] = 8.0
    islands[6:9, 6:9] = 3.0
    islands[2:4, 7:9] = 5.0
    grids.append(_grid("islands10", islands, (0.0, 0.0, 10.0, 10.0)))

    donut = np.zeros((10, 10), dtype=np.float64)
    donut[2:8, 2:8] = 4.0
    donut[4:6, 4:6] = 0.0
    grids.append(_grid("donut10", donut, (0.0, 0.0, 10.0, 10.0), unit="%"))

    nested = np.zeros((12, 12), dtype=np.float64)
    nested[1:11, 1:11] = 4.0
    nested[3:9, 3:9] = 0.0
    nested[5:7, 5:7] = 4.0
    grids.append(_grid("nested12", nested, (0.0, 0.0, 12.0, 12.0)))

    # Single-cell spike: contour is_closed=True, facies hole assignment.
    spike = np.zeros((7, 7), dtype=np.float64)
    spike[3, 3] = 100.0
    grids.append(_grid("spike7", spike, (0.0, 0.0, 70.0, 70.0), unit="%"))

    # NaN holes inside a ramp.
    holed = np.array([[float(i + j) for j in range(10)] for i in range(10)])
    holed[4:6, 4:6] = np.nan
    grids.append(_grid("holed10", holed, (0.0, 0.0, 20.0, 20.0)))

    # Flat / all-NaN / all-Inf / 1x1 / strip: the early-return branches.
    grids.append(_grid("constant8", np.full((8, 8), 5.0), (0.0, 0.0, 8.0, 8.0)))
    grids.append(_grid("nan6", np.full((6, 6), np.nan), (0.0, 0.0, 6.0, 6.0)))
    grids.append(_grid("inf6", np.full((6, 6), np.inf), (0.0, 0.0, 6.0, 6.0)))
    grids.append(_grid("one1", np.array([[12.0]]), (0.0, 0.0, 50.0, 50.0)))
    grids.append(_grid("strip1x10",
                       np.array([[float(i) for i in range(10)]]),
                       (0.0, 0.0, 100.0, 10.0)))

    # Negative values: %g labels, negative flevel Python-mod on is_index.
    neg = np.array([[-500.0, -300.0, -100.0],
                    [-400.0, -200.0, -50.0],
                    [-300.0, -100.0, 0.0]])
    grids.append(_grid("neg3", neg, (0.0, 0.0, 3.0, 3.0), unit="°C"))

    # vmin/interval in (-1, 0): math.ceil returns an int in Python, so the
    # ladder start is +0.0 (label "0") — never -0.0 (label "-0").
    neghalf = np.array([[-0.5, 0.0, 0.5, 1.0],
                        [0.0, 0.5, 1.0, 1.5],
                        [0.5, 1.0, 1.5, 2.0],
                        [1.0, 1.5, 2.0, 2.5]])
    grids.append(_grid("neghalf4", neghalf, (0.0, 0.0, 4.0, 4.0), unit="m"))

    # Micro / macro spans: %g exponent labels on the contour ladder.
    micro = np.array([[1.0e-6, 2.0e-6, 3.0e-6],
                      [2.0e-6, 4.0e-6, 2.0e-6],
                      [3.0e-6, 2.0e-6, 1.0e-6]])
    grids.append(_grid("micro3", micro, (0.0, 0.0, 3.0, 3.0)))
    macro = np.array([[1.0e8, 2.0e8, 3.0e8],
                      [2.0e8, 5.0e8, 2.0e8],
                      [3.0e8, 2.0e8, 1.0e8]])
    grids.append(_grid("macro3", macro, (0.0, 0.0, 3.0, 3.0)))

    # Adversarial matrix from test_polygon_quality_adversarial: plain ramp
    # plus a NaN-moated 2x2 island for the min_area drop counting.
    plain = np.array([[j * 0.4 + i * 0.8 for j in range(12)] for i in range(12)])
    grids.append(_grid("plain12", plain, (0.0, 0.0, 12.0, 12.0), unit="%"))
    moat = plain.copy()
    moat[5:7, 5:7] = 50.0
    moat[4:8, 4] = np.nan
    moat[4:8, 7] = np.nan
    moat[4, 4:8] = np.nan
    moat[7, 4:8] = np.nan
    grids.append(_grid("moat12", moat, (0.0, 0.0, 12.0, 12.0), unit="%"))

    # CRS-labelled variants (area_unit / area_approx_m2 / area_warnings).
    geo = np.full((12, 12), 0.5)
    geo[:6] = 0.2
    grids.append(_grid("geodeg12", geo, (0.0, 0.0, 10.0, 10.0),
                       crs="EPSG:4326", unit="1", factor="砂岩含量"))
    grids.append(_grid("geoproj12", geo, (0.0, 0.0, 1000.0, 1000.0),
                       crs="EPSG:32650", unit="1", factor="砂岩含量"))
    grids.append(_grid("geonone12", geo, (0.0, 0.0, 1000.0, 1000.0),
                       crs="", unit="1", factor="砂岩含量"))

    # Checkerboard: saddle contours + many small polygons.
    ii, jj = np.indices((8, 8))
    checker = ((ii + jj) % 2).astype(np.float64) * 10.0
    grids.append(_grid("checker8", checker, (0.0, 0.0, 80.0, 80.0)))

    # Hunt a binary grid whose class polygonization promotes an unmatched
    # hole to an exterior island (holes_promoted_to_exterior > 0) — the same
    # hunt the polygonization oracle runs, at the layer-product level.
    # (No seed promotes in 400 tries; the fallback freezes the QC plumbing.)
    promote = None
    for seed in range(400):
        rng = np.random.default_rng(seed)
        z = (rng.random((8, 8)) >= 0.45).astype(np.float64)
        if z.min() == z.max():
            continue
        res = _factor_result(_grid("tmp", z, (0.0, 0.0, 8.0, 8.0)))
        layer = generate_facies_polygon_layer(res, thresholds=[0.5])
        qc = layer.metadata["polygon_qc"]
        if qc["holes_promoted_to_exterior"] > 0:
            promote = z
            break
    if promote is not None:
        grids.append(_grid("promote8", promote, (0.0, 0.0, 8.0, 8.0)))
    else:
        # Fallback: 1-cell-wide frame plus disjoint blob still freezes the
        # counter (likely 0) so C++ must match.
        z = np.zeros((8, 8), dtype=np.float64)
        z[0, :] = 1.0
        z[-1, :] = 1.0
        z[:, 0] = 1.0
        z[:, -1] = 1.0
        z[3:5, 3:5] = 1.0
        grids.append(_grid("promote8", z, (0.0, 0.0, 8.0, 8.0)))

    return {g["name"]: g for g in grids}


def _grid_json(g: dict) -> dict:
    return {
        "x": [float(v) for v in g["x"]],
        "y": [float(v) for v in g["y"]],
        # float32 grid_z values promoted to float64 — exact JSON round-trip.
        "z": [[None if not math.isfinite(float(v)) else float(v) for v in row]
              for row in np.asarray(g["z"], dtype=np.float32)],
        "extent": [float(v) for v in g["extent"]],
        "crs": g["crs"],
        "unit": g["unit"],
        "factor": g["factor"],
    }


def _factor_result(g: dict) -> FactorGridResult:
    return FactorGridResult(
        grid_z=g["z"],
        grid_x=g["x"],
        grid_y=g["y"],
        factor_name=g["factor"],
        algorithm_id="idw",
        crs=g["crs"] or None,
        unit=g["unit"] or None,
    )


def _features_json(layer) -> list[dict]:
    out = []
    for feat in layer.features:
        out.append({
            "type": feat["type"],
            "geometry": json.loads(json.dumps(feat["geometry"])),
            "properties": {k: feat["properties"][k] for k in feat["properties"]},
        })
    return out


def _contour_cases(cases: list[dict], grids: dict) -> None:
    specs: list[tuple[str, str, dict]] = [
        ("contour_ramp8_nice", "ramp8", {}),
        ("contour_ramp8_explicit", "ramp8", {"levels": [2.0, 5.0, 9.0]}),
        ("contour_ramp8_interval", "ramp8", {"interval": 2.0}),
        ("contour_ramp8_quantile", "ramp8", {"leveling_mode": "quantile"}),
        ("contour_ramp8_smooth", "ramp8", {"levels": [3.0], "smooth": 1}),
        ("contour_batch4_nice", "batch4", {}),
        ("contour_batch4_explicit", "batch4", {"levels": [0.3, 0.6]}),
        ("contour_islands10_interval", "islands10", {"interval": 2.5}),
        ("contour_donut10_nice", "donut10", {}),
        ("contour_nested12_nice", "nested12", {}),
        ("contour_spike7_explicit", "spike7", {"levels": [50.0]}),
        ("contour_holed10_interval", "holed10", {"interval": 3.0}),
        ("contour_constant8_nice", "constant8", {}),
        ("contour_constant8_explicit", "constant8",
         {"levels": [1.0, 5.0, 9.0]}),
        ("contour_nan6_nice", "nan6", {}),
        ("contour_inf6_nice", "inf6", {}),
        ("contour_one1_nice", "one1", {}),
        ("contour_strip1x10_nice", "strip1x10", {}),
        ("contour_neg3_interval", "neg3", {"interval": 100.0}),
        ("contour_neg3_nice", "neg3", {}),
        # Branch pins: simplify>0 (RDP inside stitch), interval<=0 falls
        # through to nice while still recording contour_interval, and an
        # explicit empty levels list.
        ("contour_ramp8_simplify", "ramp8", {"levels": [3.0], "simplify": 0.6}),
        ("contour_ramp8_interval_zero", "ramp8", {"interval": 0.0}),
        ("contour_ramp8_explicit_empty", "ramp8", {"levels": []}),
        ("contour_neghalf4_interval", "neghalf4", {"interval": 1.0}),
        ("contour_micro3_nice", "micro3", {}),
        ("contour_macro3_nice", "macro3", {}),
        ("contour_plain12_quantile", "plain12", {"leveling_mode": "quantile"}),
        ("contour_checker8_explicit", "checker8", {"levels": [5.0]}),
    ]
    for cid, gname, kw in specs:
        g = grids[gname]
        res = _factor_result(g)
        layer = generate_contour_layer(
            res,
            levels=kw.get("levels"),
            interval=kw.get("interval"),
            leveling_mode=kw.get("leveling_mode", "nice"),
            simplify_tolerance=kw.get("simplify", 0.0),
            smooth_iterations=kw.get("smooth", 0),
        )
        cases.append({
            "id": cid,
            "kind": "contour",
            "grid": gname,
            "factor": g["factor"],
            "unit": g["unit"],
            "crs": g["crs"],
            "params": {
                "levels_in": kw.get("levels"),
                "interval": kw.get("interval"),
                "leveling_mode": kw.get("leveling_mode", "nice"),
                "simplify_tolerance": kw.get("simplify", 0.0),
                "smooth_iterations": kw.get("smooth", 0),
            },
            "levels": [float(v) for v in layer.levels],
            "contour_interval": (
                None if layer.contour_interval is None
                else float(layer.contour_interval)),
            "contour_qc": dict(layer.metadata["contour_qc"]),
            "features": _features_json(layer),
        })


def _facies_cases(cases: list[dict], grids: dict) -> None:
    specs: list[tuple[str, str, dict]] = [
        ("facies_ramp8_default", "ramp8", {}),
        ("facies_ramp8_explicit", "ramp8",
         {"thresholds": [6.0, 2.0, 6.0]}),  # unsorted + duplicate → sorted(set)
        ("facies_ramp8_names_short", "ramp8",
         {"thresholds": [2.0, 4.0, 6.0], "names": ["甲", "乙", "丙"]}),
        # Names shorter than thresholds+1: class ids cap at len(names)-1.
        ("facies_ramp8_names_cap", "ramp8",
         {"thresholds": [1.0, 4.0, 7.0], "names": ["甲", "乙"]}),
        # Explicit per-class colors override the default palette.
        ("facies_ramp8_colors", "ramp8",
         {"thresholds": [2.0, 6.0],
          "colors": ["#111111", "#222222", "#333333"]}),
        ("facies_batch4_default", "batch4", {}),
        ("facies_islands10_explicit", "islands10", {"thresholds": [1.0, 6.0]}),
        ("facies_donut10_default", "donut10", {}),
        ("facies_nested12_explicit", "nested12", {"thresholds": [2.0]}),
        ("facies_spike7_explicit", "spike7",
         {"thresholds": [50.0], "names": ["背景", "尖峰"]}),
        ("facies_holed10_explicit", "holed10",
         {"thresholds": [3.0, 9.0]}),
        ("facies_constant8_default", "constant8", {}),
        ("facies_constant8_explicit", "constant8",
         {"thresholds": [20.0, 30.0], "names": ["Low", "Medium", "High"]}),
        ("facies_nan6_default", "nan6", {}),
        ("facies_nan6_minarea", "nan6",
         {"min_area": 5.0}),  # early return still echoes small_polygon_threshold
        ("facies_inf6_default", "inf6", {}),
        ("facies_one1_default", "one1", {}),
        ("facies_strip1x10_explicit", "strip1x10",
         {"thresholds": [3.0, 7.0]}),
        ("facies_checker8_explicit", "checker8", {"thresholds": [5.0]}),
        ("facies_plain12_explicit", "plain12", {"thresholds": [4.0, 8.0]}),
        # min_area: drops counted, None/0 keep everything.
        ("facies_moat12_minarea", "moat12",
         {"thresholds": [40.0], "min_area": 5.0}),
        ("facies_moat12_keep", "moat12", {"thresholds": [40.0]}),
        ("facies_moat12_minarea_zero", "moat12",
         {"thresholds": [40.0], "min_area": 0.0}),
        ("facies_moat12_minarea_eq", "moat12",
         {"thresholds": [40.0], "min_area": 4.0}),  # area == min_area kept
        # CRS label matrix: deg² + area_approx_m2 / {crs}-unit² / unknown.
        ("facies_geodeg12_default", "geodeg12", {}),
        ("facies_geoproj12_default", "geoproj12", {}),
        ("facies_geonone12_default", "geonone12", {}),
        # Thresholds fully outside [vmin, vmax].
        ("facies_ramp8_outside_low", "ramp8", {"thresholds": [-100.0]}),
        ("facies_ramp8_outside_high", "ramp8", {"thresholds": [100.0]}),
        # Hole promotion (or its pinned zero fallback) at the layer level.
        ("facies_promote8_explicit", "promote8", {"thresholds": [0.5]}),
    ]
    for cid, gname, kw in specs:
        g = grids[gname]
        res = _factor_result(g)
        layer = generate_facies_polygon_layer(
            res,
            thresholds=kw.get("thresholds"),
            facies_names=kw.get("names"),
            colors=kw.get("colors"),
            min_area=kw.get("min_area"),
        )
        cases.append({
            "id": cid,
            "kind": "facies",
            "grid": gname,
            "factor": g["factor"],
            "unit": g["unit"],
            "crs": g["crs"],
            "params": {
                "thresholds_in": kw.get("thresholds"),
                "names_in": kw.get("names"),
                "colors_in": kw.get("colors"),
                "min_area": kw.get("min_area"),
            },
            "polygon_qc": json.loads(json.dumps(layer.metadata["polygon_qc"])),
            "features": _features_json(layer),
        })


def _mean_units() -> list[dict]:
    """Pin the numpy float32 mask-mean semantics (pairwise float32 sum, then
    a float32 division) that ``mean_value`` depends on."""
    rng = np.random.default_rng(20)
    out = []
    for n in (3, 7, 8, 100, 127, 128, 129, 200, 255, 300):
        vals = rng.uniform(-50.0, 50.0, n).astype(np.float32)
        out.append({
            "n": n,
            "values": [float(v) for v in vals],
            "mean": float(np.mean(vals)),
        })
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    grids = _grids()
    cases: list[dict] = []
    _contour_cases(cases, grids)
    _facies_cases(cases, grids)

    doc = {
        "grids": {name: _grid_json(g) for name, g in grids.items()},
        "cases": cases,
        "mean_units": _mean_units(),
    }
    target = OUT / "layer_products_oracle.json"
    target.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    n_contour = sum(1 for c in cases if c["kind"] == "contour")
    n_facies = sum(1 for c in cases if c["kind"] == "facies")
    n_features = sum(len(c["features"]) for c in cases)
    empty = [c["id"] for c in cases if not c["features"]]
    print(f"wrote {target} ({target.stat().st_size} bytes, "
          f"{n_contour} contour + {n_facies} facies cases, "
          f"{n_features} features total)")
    if empty:
        print("empty-feature cases (early-return branches):", empty)
    approx = [
        (c["id"], c["features"][0]["properties"].get("area_approx_m2"))
        for c in cases
        if c["kind"] == "facies" and c["features"]
        and "area_approx_m2" in c["features"][0]["properties"]
    ]
    if approx:
        print("geographic-CRS cases with area_approx_m2:", approx)


if __name__ == "__main__":
    main()
