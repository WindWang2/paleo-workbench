#!/usr/bin/env python3
"""Oracle fixture generator for CONV-10: representative_facies +
point_to_surface descriptors (M6 leaf on the existing class-grid kernel).

Imports the REAL implementation
(paleo_workbench.mapping.well_prediction_surface) and freezes outputs so the
C++ port can be verified. Every expectation in this file is produced by
executing the real module — nothing is hand-computed.

Divergences (documented, NOT frozen):
  * repair_invalid_geometry is monkeypatched to identity — same precedent as
    generate_polygonization_fixtures.py (the C++ kernel has no shapely).
  * Only clip_ring-free projects are frozen for point_to_surface_features:
    the polygon-level shapely clip is not ported; the grid-level inclusive
    clip is already frozen in class_grid_oracle.json.

Regenerate with:

    python3 tools/oracle/generate_representative_facies_fixtures.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import _legacy_reference

_legacy_reference.ensure_legacy_reference()  # archived-reference shim

from paleo_workbench.mapping import well_prediction_surface as wps  # noqa: E402
from paleo_workbench.mapping.geological_pipeline import (  # noqa: E402
    polygonization as poly,
)


def _identity_repair(geom):
    """Leave GeoJSON polygons untouched (C++ kernel has no shapely repair)."""
    return geom


poly.repair_invalid_geometry = _identity_repair

OUT = (
    REPO_ROOT
    / "libs"
    / "mapping_kernel"
    / "mapping_kernel_tests"
    / "fixtures"
)


def _picked(record) -> list | None:
    if record is None:
        return None
    facies, mean_p, thickness = record
    return [facies, mean_p, thickness]


def _point(x, y, facies, *, well_id="", well_name="", probability=None,
           task_id="", thickness=None) -> dict:
    return {
        "x": x, "y": y, "facies": facies,
        "well_id": well_id, "well_name": well_name,
        "probability": probability, "task_id": task_id,
        "thickness": thickness,
    }


def representative_cases() -> list[dict]:
    cases = []

    def case(cid, regions, horizon="", *, doc=""):
        cases.append({
            "id": cid,
            "regions": regions,
            "horizon": horizon,
            "doc": doc,
            "expected": _picked(wps.representative_facies(regions, horizon=horizon)),
        })

    # --- the two pinned behaviours of tests/test_well_prediction_surface.py
    case("thickest_wins_even_if_lower_probability", [
        {"facies": "三角洲", "top": 0, "bottom": 10, "probability": 0.4},
        {"facies": "滨浅湖", "top": 10, "bottom": 40, "probability": 0.9},
        {"facies": "三角洲", "top": 40, "bottom": 45, "probability": 0.8},
    ])
    case("same_class_thickness_sums", [
        {"facies": "三角洲", "top": 0, "bottom": 20, "probability": 0.5},
        {"facies": "滨浅湖", "top": 20, "bottom": 25, "probability": 0.9},
        {"facies": "三角洲", "top": 25, "bottom": 40, "probability": 0.5},
    ])
    # --- no thickness at all: probability only (weight 1.0 per record)
    case("no_thickness_probability_only", [
        {"facies": "A", "probability": 0.6},
        {"facies": "B", "probability": 0.9},
        {"facies": "A", "probability": 0.7},
    ])
    # --- full tie: first inserted facies wins (stable order)
    case("tie_first_inserted_wins", [
        {"facies": "A", "probability": 0.5},
        {"facies": "B", "probability": 0.5},
    ])
    # --- thickness tie broken by mean probability
    case("thickness_tie_mean_probability_decides", [
        {"facies": "A", "top": 0, "bottom": 10, "probability": 0.2},
        {"facies": "B", "top": 0, "bottom": 5, "probability": 0.95},
        {"facies": "B", "top": 5, "bottom": 10, "probability": 0.95},
    ])
    # --- horizon filtering (substring, stratigraphic_unit or horizon key)
    case("horizon_substring_filters", [
        {"facies": "三角洲", "top": 0, "bottom": 50,
         "stratigraphic_unit": "T1", "probability": 0.9},
        {"facies": "滨浅湖", "top": 50, "bottom": 55,
         "stratigraphic_unit": "D63下", "probability": 0.4},
    ], horizon="D63")
    case("horizon_no_match_keeps_all", [
        {"facies": "三角洲", "top": 0, "bottom": 50, "probability": 0.9},
        {"facies": "滨浅湖", "top": 50, "bottom": 55, "probability": 0.4},
    ], horizon="T9")
    case("horizon_falls_back_to_horizon_key", [
        {"facies": "三角洲", "top": 0, "bottom": 30,
         "horizon": "Sq1", "probability": 0.5},
        {"facies": "滨浅湖", "top": 30, "bottom": 35, "probability": 0.4},
    ], horizon="Sq1")
    case("horizon_match_is_substring_not_equality", [
        {"facies": "三角洲", "top": 0, "bottom": 30,
         "stratigraphic_unit": "Sq1底", "probability": 0.5},
    ], horizon="Sq1")
    case("horizon_whitespace_stripped", [
        {"facies": "滨浅湖", "top": 0, "bottom": 8,
         "stratigraphic_unit": "D63", "probability": 0.6},
        {"facies": "三角洲", "top": 0, "bottom": 50, "probability": 0.9},
    ], horizon="  D63 ")
    # --- probability key fallbacks
    case("confidence_key_used_when_no_probability", [
        {"facies": "A", "confidence": 0.8},
        {"facies": "B", "confidence": 0.3},
    ])
    case("probability_zero_falls_through_to_confidence", [
        {"facies": "A", "probability": 0.0, "confidence": 0.85},
        {"facies": "B", "probability": 0.4},
    ])
    case("probability_unparseable_no_fallback", [
        {"facies": "A", "probability": "abc", "confidence": 0.85,
         "top": 0, "bottom": 4},
        {"facies": "B", "probability": 0.1, "top": 0, "bottom": 1},
    ])
    # --- numeric coercion
    case("string_numbers_parse", [
        {"facies": "A", "top": "0", "bottom": "40", "probability": "0.9"},
        {"facies": "B", "top": 40, "bottom": 44, "probability": 0.2},
    ])
    case("non_finite_string_treated_missing", [
        {"facies": "A", "top": "inf", "bottom": 10, "probability": 0.7},
        {"facies": "B", "top": 0, "bottom": 6, "probability": 0.2},
    ])
    case("negative_interval_thickness_abs", [
        {"facies": "A", "top": 40, "bottom": 10, "probability": 0.3},
        {"facies": "B", "top": 0, "bottom": 20, "probability": 0.9},
    ])
    # --- skipping rules
    case("non_dict_and_blank_facies_skipped", [
        "junk", 42, [1, 2], {"facies": "   "},
        {"facies": "A", "top": 0, "bottom": 12, "probability": 0.4},
    ])
    case("falsy_facies_falls_to_next_key", [
        {"facies": "", "label": "B", "top": 0, "bottom": 30, "probability": 0.6},
        {"facies": 0, "name": "C", "top": 0, "bottom": 5, "probability": 0.9},
    ])
    case("all_blank_returns_none", [{"facies": ""}, {"label": "  "}])
    case("null_regions_returns_none", None)
    case("empty_list_returns_none", [])
    # --- Unicode / PEP 515 float parsing fidelity
    case("ideographic_space_strips_like_python", [
        {"facies": "　三角洲　", "top": 0, "bottom": 10, "probability": 0.2},
        {"facies": "三角洲", "top": 10, "bottom": 25, "probability": 0.9},
    ])
    case("underscore_digits_parse", [
        {"facies": "A", "top": "1_0", "bottom": "40", "probability": "0.8_5"},
        {"facies": "B", "top": 0, "bottom": 5, "probability": 0.1},
    ])
    case("underflow_string_is_zero_not_missing", [
        {"facies": "A", "top": "1e-400", "bottom": 10, "probability": 0.6},
        {"facies": "B", "top": 0, "bottom": 9, "probability": 0.1},
    ])
    case("mixed_none_probability_partial", [
        {"facies": "A", "top": 0, "bottom": 10, "probability": 0.2},
        {"facies": "A", "top": 10, "bottom": 20},
        {"facies": "B", "top": 0, "bottom": 9, "probability": 0.99},
    ])
    return cases


def task_region_cases() -> list[dict]:
    def run(summary) -> list:
        return wps._task_regions(SimpleNamespace(result_summary=summary))

    return [
        {
            "id": "intervals_preferred",
            "summary": {"spatial": {"type": "WELL_INTERVALS", "intervals": [
                {"facies": "A", "top": 0, "bottom": 5},
                "junk",
            ]},
                "predicted_regions": [{"facies": "WRONG"}]},
            "expected": run({"spatial": {"type": "WELL_INTERVALS", "intervals": [
                {"facies": "A", "top": 0, "bottom": 5},
                "junk",
            ]},
                "predicted_regions": [{"facies": "WRONG"}]}),
        },
        {
            "id": "well_intervals_fallback",
            "summary": {"spatial": {"intervals": [], "well_intervals": [
                {"facies": "B", "top": 1, "bottom": 2},
            ]}},
            "expected": run({"spatial": {"intervals": [], "well_intervals": [
                {"facies": "B", "top": 1, "bottom": 2},
            ]}}),
        },
        {
            "id": "predicted_regions_fallback_no_spatial",
            "summary": {"predicted_regions": [{"facies": "C"}],
                        "is_mock": True},
            "expected": run({"predicted_regions": [{"facies": "C"}],
                             "is_mock": True}),
        },
        {
            "id": "predicted_regions_when_intervals_absent",
            "summary": {"spatial": {"type": "WELL_INTERVALS"},
                        "predicted_regions": [{"facies": "D"}]},
            "expected": run({"spatial": {"type": "WELL_INTERVALS"},
                             "predicted_regions": [{"facies": "D"}]}),
        },
        {
            "id": "truthy_non_list_intervals_falls_through",
            "summary": {"spatial": {"intervals": "x"},
                        "predicted_regions": [{"facies": "E"}]},
            "expected": run({"spatial": {"intervals": "x"},
                             "predicted_regions": [{"facies": "E"}]}),
        },
        {
            "id": "empty_summary",
            "summary": {},
            "expected": run({}),
        },
    ]


def spatial_point_cases() -> list[dict]:
    def run(summary, task_id) -> list:
        points = wps._spatial_point_features(
            SimpleNamespace(result_summary=summary, id=task_id))
        return [_point(p.x, p.y, p.facies, well_id=p.well_id,
                       well_name=p.well_name, probability=p.probability,
                       task_id=p.task_id, thickness=p.thickness)
                for p in points]

    summary_full = {"spatial": {"features": [
        {"type": "Feature",
         "geometry": {"type": "Point", "coordinates": [3.0, 4.0]},
         "properties": {"facies": "分流河道", "probability": 0.7,
                        "well_id": "w1", "well_name": "W1"}},
        {"type": "Feature",
         "geometry": {"type": "Point", "coordinates": [5.0, 6.0]},
         "properties": {"label": "河口坝", "confidence": 0.55, "well": "W2"}},
        {"type": "Feature",
         "geometry": {"type": "Point", "coordinates": ["abc", 6.0]},
         "properties": {"facies": "非有限坐标应丢弃"}},
        {"type": "Feature",
         "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
         "properties": {"facies": "非点几何应丢弃"}},
        {"type": "Feature",
         "geometry": {"type": "Point", "coordinates": [1.0]},
         "properties": {"facies": "坐标不足应丢弃"}},
        {"type": "Feature",
         "geometry": {"type": "Point", "coordinates": [7.0, 8.0]},
         "properties": {"facies": "   "}},
        "junk",
    ]}}
    return [
        {
            "id": "point_features_parsed_and_filtered",
            "summary": summary_full,
            "task_id": "pred_9",
            "expected": run(summary_full, "pred_9"),
        },
        {
            "id": "features_not_a_list",
            "summary": {"spatial": {"features": "x"}},
            "task_id": "t",
            "expected": run({"spatial": {"features": "x"}}, "t"),
        },
        {
            "id": "no_spatial",
            "summary": {},
            "task_id": "t",
            "expected": run({}, "t"),
        },
    ]


def point_feature_cases() -> list[dict]:
    def run(points) -> list:
        pairs = wps.point_features(points)
        return [{"geometry": g, "properties": props} for g, props in pairs]

    full = [
        wps.WellFaciesPoint(x=1.5, y=-2.0, facies="三角洲", well_id="w1",
                            well_name="W1", probability=0.8, task_id="p1",
                            thickness=30.0),
    ]
    bare = [
        wps.WellFaciesPoint(x=0.0, y=0.0, facies="滨浅湖"),
    ]
    return [
        {"id": "full_fields", "points": [
            _point(p.x, p.y, p.facies, well_id=p.well_id,
                   well_name=p.well_name, probability=p.probability,
                   task_id=p.task_id, thickness=p.thickness)
            for p in full],
         "expected": run(full)},
        {"id": "optional_keys_absent", "points": [
            _point(p.x, p.y, p.facies, well_id=p.well_id,
                   well_name=p.well_name, probability=p.probability,
                   task_id=p.task_id, thickness=p.thickness)
            for p in bare],
         "expected": run(bare)},
        {"id": "empty", "points": [], "expected": run([])},
    ]


def extent_cases() -> list[dict]:
    cases = []

    def points_arg(rows) -> list:
        return [wps.WellFaciesPoint(**row) for row in rows]

    pts_spread = [{"x": 0.0, "y": 5.0, "facies": "A"},
                  {"x": 10.0, "y": 25.0, "facies": "B"}]
    cases.append({
        "id": "extent_from_points_padding",
        "kind": "points",
        "points": pts_spread,
        "expected": list(wps._extent_from_points(points_arg(pts_spread))),
    })
    pts_tiny = [{"x": 2.0, "y": 3.0, "facies": "A"},
                {"x": 2.2, "y": 3.0, "facies": "B"}]
    cases.append({
        "id": "extent_from_points_min_span_clamp",
        "kind": "points",
        "points": pts_tiny,
        "expected": list(wps._extent_from_points(points_arg(pts_tiny))),
    })
    square = SimpleNamespace(
        workarea=SimpleNamespace(
            boundary=[[0, 1], [10, 1], [10, 11], [0, 11], [0, 1]]))
    got = wps._extent_from_workarea(square)
    cases.append({
        "id": "extent_from_workarea_bbox",
        "kind": "workarea",
        "boundary": square.workarea.boundary,
        "expected": None if got is None else list(got),
    })
    short = SimpleNamespace(workarea=SimpleNamespace(boundary=[[0, 0], [5, 5]]))
    got = wps._extent_from_workarea(short)
    cases.append({
        "id": "extent_from_workarea_too_few_vertices",
        "kind": "workarea",
        "boundary": short.workarea.boundary,
        "expected": None if got is None else list(got),
    })
    cases.append({
        "id": "clip_ring_closed_square",
        "kind": "clip_ring",
        "boundary": square.workarea.boundary,
        "expected": wps._clip_ring(square),
    })
    triangle = SimpleNamespace(workarea=SimpleNamespace(
        boundary=[[0, 0], [4, 0], [2, 3]]))
    cases.append({
        "id": "clip_ring_too_few_vertices",
        "kind": "clip_ring",
        "boundary": triangle.workarea.boundary,
        "expected": wps._clip_ring(triangle),
    })
    return cases


def surface_cases() -> list[dict]:
    cases = []
    corners_center = [
        _point(0.0, 0.0, "A"), _point(10.0, 0.0, "A"),
        _point(0.0, 10.0, "A"), _point(10.0, 10.0, "A"),
        _point(5.0, 5.0, "B"),
    ]

    def run(points, *, project=None, grid_n=80) -> dict:
        pts = [wps.WellFaciesPoint(**row) for row in points]
        # point_to_surface_features guards the empty case before touching
        # the extent — mirror that order instead of resolving eagerly.
        extent = None if not pts else (
            wps._extent_from_workarea(project) or wps._extent_from_points(pts))
        features = wps.point_to_surface_features(
            pts, project=project, grid_n=grid_n)
        return {
            "extent": None if extent is None else list(extent),
            "features": [{"geometry": g, "properties": props}
                         for g, props in features],
        }

    two_points = [_point(0.0, 0.0, "三角洲"), _point(10.0, 0.0, "滨浅湖")]
    got = run(two_points, grid_n=8)
    cases.append({"id": "two_points_no_project", "points": two_points,
                  "grid_n": 8, "crs": None, **got})

    single = [_point(2.0, 3.0, "扇三角洲")]
    got = run(single, grid_n=5)
    cases.append({"id": "single_point_one_class", "points": single,
                  "grid_n": 5, "crs": None, **got})

    got = run(corners_center, grid_n=7)
    cases.append({"id": "island_makes_hole", "points": corners_center,
                  "grid_n": 7, "crs": None, **got})

    projected = SimpleNamespace(
        coordinate=SimpleNamespace(project_crs="EPSG:32650"), workarea=None)
    got = run(two_points, project=projected, grid_n=6)
    cases.append({"id": "projected_crs_unit_label", "points": two_points,
                  "grid_n": 6, "crs": "EPSG:32650", **got})

    geographic = SimpleNamespace(
        coordinate=SimpleNamespace(project_crs="EPSG:4326"), workarea=None)
    got = run(two_points, project=geographic, grid_n=6)
    cases.append({"id": "geographic_crs_approx_m2", "points": two_points,
                  "grid_n": 6, "crs": "EPSG:4326", **got})

    got = run(corners_center, project=geographic, grid_n=7)
    cases.append({"id": "geographic_island_holes", "points": corners_center,
                  "grid_n": 7, "crs": "EPSG:4326", **got})

    got = run(two_points, grid_n=1)
    cases.append({"id": "grid_n_clamped_to_two", "points": two_points,
                  "grid_n": 1, "crs": None, **got})

    got = run([])
    cases.append({"id": "empty_points", "points": [],
                  "grid_n": 8, "crs": None, **got})
    return cases


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    doc = {
        "generator": "tools/oracle/generate_representative_facies_fixtures.py",
        "notes": [
            "Every expected value is produced by executing the real",
            "paleo_workbench.mapping.well_prediction_surface functions",
            "(private helpers imported and called directly).",
            "repair_invalid_geometry is monkeypatched to identity (C++ has",
            "no shapely) — same precedent as the polygonization oracle.",
            "point_to_surface_features cases are clip_ring-free on the",
            "polygon level; the grid-level inclusive clip is frozen in",
            "class_grid_oracle.json (clip_square).",
        ],
        "representative_facies_cases": representative_cases(),
        "task_region_cases": task_region_cases(),
        "spatial_point_cases": spatial_point_cases(),
        "point_feature_cases": point_feature_cases(),
        "extent_cases": extent_cases(),
        "surface_cases": surface_cases(),
    }
    target = OUT / "representative_facies_oracle.json"
    target.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    print(
        f"wrote {target} ({target.stat().st_size} bytes; "
        f"{len(doc['representative_facies_cases'])} representative cases, "
        f"{len(doc['task_region_cases'])} task-region cases, "
        f"{len(doc['spatial_point_cases'])} spatial-point cases, "
        f"{len(doc['point_feature_cases'])} point-feature cases, "
        f"{len(doc['extent_cases'])} extent cases, "
        f"{len(doc['surface_cases'])} surface cases)"
    )


if __name__ == "__main__":
    main()
