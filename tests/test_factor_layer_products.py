"""Goal §10-12: pure factor-group layer-descriptor builders + stage wiring.

Part 1 (pure): ``factor_group_layers`` must produce ALL SIX factor-group
children per ``FACTOR_CHILD_ORDER`` from a real ``FactorGridResult``, with
honest absence (no variance grid → no uncertainty child, reported in QC),
capped contours, QC point attributes matching the FACTOR_QC spec fields
(rule/severity/reason), prediction-confidence extraction, and integrated
boundary ring extraction.

Part 2 (Qt, skipped without PySide6): the stage-action wiring —
``overlay_factor_results`` registering 6/6 children, the
``toggle_prediction_confidence`` toggle, and ``create_integrated_boundary``.
"""
from __future__ import annotations

import numpy as np
import pytest

from paleo_workbench.mapping_workspace.layer_groups import FACTOR_CHILD_ORDER
from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.mapping.factor_layer_products import (
    boundary_features_from_polygons,
    classify_prediction_task,
    confidence_overlay_layers,
    factor_group_layers,
    integrated_boundary_action_helpers,
)
from paleo_workbench.project.models import (
    FACTOR_TASK_STATUS_COMPLETE,
    FactorMapTask,
    PredictionTask,
    ProjectDocument,
    UserVectorFeature,
    UserVectorLayer,
    WellTable,
    WellTableRow,
)
from paleo_workbench.workflow.factor_grid_result import FactorGridResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SAMPLE_POINTS = [
    {"x": 1.0, "y": 1.0, "value": 0.9},
    {"x": 4.0, "y": 1.0, "value": 0.4},
    {"x": 1.0, "y": 4.0, "value": 0.6},
    {"x": 4.0, "y": 4.0, "value": 0.2},
    {"x": 2.5, "y": 2.5, "value": 0.5},
]


def _grid(with_variance: bool) -> FactorGridResult:
    x = np.linspace(0.0, 10.0, 24)
    y = np.linspace(0.0, 8.0, 20)
    xx, yy = np.meshgrid(x, y)
    z = (np.sin(xx * 0.4) + np.cos(yy * 0.5)).astype(np.float32)
    variance = (
        np.full_like(z, 0.25, dtype=np.float32) if with_variance else None
    )
    return FactorGridResult(
        grid_z=z,
        grid_x=x,
        grid_y=y,
        factor_name="砂地比",
        algorithm_id="kriging",
        algorithm_parameters={
            "sample_points": _SAMPLE_POINTS,
            "variance_min": 0.1,
            "variance_max": 0.5,
        },
        variance_grid=variance,
    )


def _task() -> FactorMapTask:
    return FactorMapTask(
        name="砂地比",
        target_horizon="T2",
        factor_type="sand_ratio",
        method="克里金",
        status=FACTOR_TASK_STATUS_COMPLETE,
        well_table_id="wtable-1",
        parameters={
            "sample_points": _SAMPLE_POINTS,
            "constraint_diagnostics": {
                "method": "kriging",
                "requested_constraints": ["barrier", "boundary_mask"],
                "applied_constraints": ["anisotropy"],
                "ignored_constraints": ["barrier"],
                "unsupported_constraints": ["boundary_mask"],
                "partial_constraints": [],
                "constraint_diagnostics": [],
            },
        },
        quality_metrics={"duplicate_wells_dropped": 2},
    )


def _document() -> ProjectDocument:
    document = ProjectDocument.new("Factor products")
    document.well_tables.append(WellTable(
        id="wtable-1",
        name="T2 井位",
        rows=[
            WellTableRow(well_id="w1", name="W1", x=1.0, y=1.0),
            WellTableRow(well_id="w2", name="W2", x=4.0, y=1.0),
            WellTableRow(well_id="w3", name="W3", x=2.5, y=4.0),
        ],
    ))
    return document


# ---------------------------------------------------------------------------
# Part 1 — pure builders
# ---------------------------------------------------------------------------


def test_six_children_with_variance_grid():
    descriptors = factor_group_layers(_document(), _task(), grid=_grid(True))
    assert [d["role"] for d in descriptors] == list(FACTOR_CHILD_ORDER)
    by_role = {d["role"]: d for d in descriptors}

    # input: well points from the linked WellTable
    inp = by_role[LayerRole.FACTOR_INPUT]
    assert inp["geometry_kind"] == "point"
    assert len(inp["features"]) == 3
    geometry, attributes = inp["features"][0]
    assert geometry["type"] == "Point"
    assert attributes["well_id"] == "w1"

    # grid: scalar_grid descriptor semantics, metadata not arrays
    grid_child = by_role[LayerRole.FACTOR_GRID]
    assert grid_child["geometry_kind"] == "raster"
    assert grid_child["payload"]["layer_type"] == "scalar_grid"
    metadata = grid_child["metadata"]
    assert metadata["source"] == "live_grid"
    assert metadata["quantity"] == "factor_value"
    assert len(metadata["extent"]) == 4
    assert metadata["width"] == 24 and metadata["height"] == 20
    assert metadata["has_variance_grid"] is True
    assert "grid_z" not in str(grid_child["payload"])  # arrays never cross

    # contour: marching-squares lines from the live grid
    contour = by_role[LayerRole.FACTOR_CONTOUR]
    assert contour["geometry_kind"] == "line"
    assert contour["features"], "analytic grid must yield contour lines"
    assert contour["features"][0][0]["type"] == "LineString"
    assert "level" in contour["features"][0][1]

    # classification: polygons with facies attributes
    classification = by_role[LayerRole.FACTOR_CLASSIFICATION]
    assert classification["geometry_kind"] == "polygon"
    assert classification["features"]
    assert classification["features"][0][0]["type"] in {"Polygon", "MultiPolygon"}
    assert "facies_name" in classification["features"][0][1]

    # uncertainty: stddev descriptor derived from variance_grid
    uncertainty = by_role[LayerRole.FACTOR_UNCERTAINTY]
    assert uncertainty["geometry_kind"] == "raster"
    assert uncertainty["payload"]["layer_type"] == "scalar_grid"
    assert uncertainty["metadata"]["quantity"] == "stddev"
    stats = uncertainty["metadata"]["stddev_statistics"]
    assert stats["min"] == pytest.approx(0.5)  # sqrt(0.25), constant variance
    assert stats["max"] == pytest.approx(0.5)


def test_uncertainty_honest_absence_reported_in_qc():
    descriptors = factor_group_layers(_document(), _task(), grid=_grid(False))
    roles = [d["role"] for d in descriptors]
    assert LayerRole.FACTOR_UNCERTAINTY not in roles
    assert roles == [r for r in FACTOR_CHILD_ORDER if r is not LayerRole.FACTOR_UNCERTAINTY]
    qc = next(d for d in descriptors if d["role"] is LayerRole.FACTOR_QC)
    rules = [m["rule"] for m in qc["metadata"]["markers"]]
    assert "uncertainty_missing" in rules
    marker = next(m for m in qc["metadata"]["markers"] if m["rule"] == "uncertainty_missing")
    assert marker["severity"] == "info"


def test_no_live_grid_children_are_honestly_empty():
    task = _task()
    task.grid_metadata = {"algorithm_id": "kriging", "width": 4, "height": 4,
                          "extent": [0.0, 0.0, 1.0, 1.0]}
    descriptors = factor_group_layers(_document(), task, grid=None)
    by_role = {d["role"]: d for d in descriptors}
    assert by_role[LayerRole.FACTOR_CONTOUR]["features"] == []
    assert "absent_reason" in by_role[LayerRole.FACTOR_CONTOUR]["metadata"]
    assert by_role[LayerRole.FACTOR_CLASSIFICATION]["features"] == []
    assert "absent_reason" in by_role[LayerRole.FACTOR_CLASSIFICATION]["metadata"]
    # grid child degrades to task metadata (descriptor still complete)
    assert by_role[LayerRole.FACTOR_GRID]["metadata"]["source"] == "task_grid_metadata"
    assert by_role[LayerRole.FACTOR_GRID]["metadata"]["algorithm_id"] == "kriging"
    # QC reports the missing grid
    rules = [m["rule"] for m in by_role[LayerRole.FACTOR_QC]["metadata"]["markers"]]
    assert "grid_unavailable" in rules


def test_qc_point_attributes_match_factor_qc_spec_fields():
    descriptors = factor_group_layers(_document(), _task(), grid=_grid(False))
    qc = next(d for d in descriptors if d["role"] is LayerRole.FACTOR_QC)
    assert qc["features"], "markers exist → anchor exists → point features"
    for geometry, attributes in qc["features"]:
        assert geometry["type"] == "Point"
        # FACTOR_QC spec fields (geological_layer_spec factor-qc-v2)
        assert attributes["rule"]
        assert attributes["severity"] in {"info", "warning", "error"}
        assert isinstance(attributes["reason"], str) and attributes["reason"]
    rules = [attrs["rule"] for _, attrs in qc["features"]]
    assert "constraint_ignored:barrier" in rules
    assert "constraint_unsupported:boundary_mask" in rules
    assert "duplicate_wells_dropped" in rules
    ignored = next(attrs for _, attrs in qc["features"]
                   if attrs["rule"] == "constraint_ignored:barrier")
    assert ignored["severity"] == "warning"


def test_contour_limit_truncation_is_reported():
    descriptors = factor_group_layers(
        _document(), _task(), grid=_grid(True), contour_limit=3)
    contour = next(d for d in descriptors if d["role"] is LayerRole.FACTOR_CONTOUR)
    assert len(contour["features"]) == 3
    assert contour["metadata"]["truncated"] is True
    assert contour["metadata"]["feature_count_total"] > 3


def test_input_falls_back_to_task_sample_points():
    task = _task()
    task.well_table_id = None
    descriptors = factor_group_layers(_document(), task, grid=None)
    inp = next(d for d in descriptors if d["role"] is LayerRole.FACTOR_INPUT)
    assert len(inp["features"]) == len(_SAMPLE_POINTS)
    assert inp["metadata"]["well_source"] == "task_parameters"
    assert inp["features"][0][1]["value"] == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# Part 1b — prediction confidence overlays
# ---------------------------------------------------------------------------


def _prediction_feature(probability: float | None) -> dict:
    properties = {"facies": "三角洲前缘", "region_id": "r1"}
    if probability is not None:
        properties["probability"] = probability
    return {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]],
        },
        "properties": properties,
    }


def test_confidence_overlay_extracts_probability_polygons():
    task = PredictionTask(
        name="测井预测",
        input_refs={"well_logs": ["r1"]},
        result_summary={"spatial": {
            "type": "VECTOR_POLYGONS",
            "features": [_prediction_feature(0.82), _prediction_feature(0.64)],
        }},
    )
    assert classify_prediction_task(task) == "well"
    descriptors = confidence_overlay_layers(None, task)
    assert len(descriptors) == 1
    descriptor = descriptors[0]
    assert descriptor["role"] is LayerRole.WELL_FACIES_CONFIDENCE
    assert descriptor["geometry_kind"] == "polygon"
    assert len(descriptor["features"]) == 2
    assert descriptor["features"][0][1]["probability"] == pytest.approx(0.82)
    assert descriptor["metadata"]["probability_min"] == pytest.approx(0.64)


def test_confidence_overlay_seismic_role_and_honest_empty():
    seismic = PredictionTask(
        name="地震预测",
        input_refs={"seismic_volume": ["s1"]},
        result_summary={"spatial": {
            "type": "VECTOR_POLYGONS",
            "features": [_prediction_feature(0.7)],
        }},
    )
    descriptors = confidence_overlay_layers(None, seismic)
    assert len(descriptors) == 1
    assert descriptors[0]["role"] is LayerRole.SEISMIC_FACIES_CONFIDENCE

    # No probability field → honest empty list (no fabricated confidence).
    bare = PredictionTask(
        name="测井预测",
        input_refs={"well_logs": ["r1"]},
        result_summary={"spatial": {
            "type": "VECTOR_POLYGONS",
            "features": [_prediction_feature(None)],
        }},
    )
    assert confidence_overlay_layers(None, bare) == []
    # Unknown category → honest empty list.
    unknown = PredictionTask(name="神秘预测")
    assert classify_prediction_task(unknown) == "unknown"
    assert confidence_overlay_layers(None, unknown) == []


# ---------------------------------------------------------------------------
# Part 1c — integrated boundary rings
# ---------------------------------------------------------------------------


def test_integrated_boundary_rings_include_holes():
    document = ProjectDocument.new("Boundary")
    layer = UserVectorLayer(
        id="draft-1",
        name="综合沉积相（草稿）",
        geometry_kind="polygon",
        features=[UserVectorFeature(
            id="f1",
            geometry={
                "type": "Polygon",
                "coordinates": [
                    [[0, 0], [4, 0], [4, 4], [0, 0]],      # exterior (open)
                    [[1, 1], [2, 1], [2, 2], [1, 1]],      # hole
                ],
            },
            properties={"facies": "三角洲前缘"},
        )],
    )
    document.user_vector_layers.append(layer)
    descriptor = integrated_boundary_action_helpers(document, "draft-1")
    assert descriptor is not None
    assert descriptor["role"] is LayerRole.INTEGRATED_BOUNDARY
    assert descriptor["geometry_kind"] == "line"
    assert len(descriptor["features"]) == 2  # exterior + hole
    exterior, hole = descriptor["features"]
    assert exterior[0]["type"] == "LineString"
    assert exterior[1]["ring"] == "exterior"
    assert exterior[1]["facies"] == "三角洲前缘"
    assert hole[1]["ring"] == "hole_1"
    # Unknown / geometry-less drafts are honest None.
    assert integrated_boundary_action_helpers(document, "nope") is None
    empty = UserVectorLayer(id="draft-2", name="空", geometry_kind="polygon")
    document.user_vector_layers.append(empty)
    assert integrated_boundary_action_helpers(document, "draft-2") is None


def test_boundary_features_from_polygons_multipolygon():
    features = boundary_features_from_polygons([(
        {"type": "MultiPolygon",
         "coordinates": [[[[0, 0], [1, 0], [1, 1], [0, 0]]],
                          [[[2, 2], [3, 2], [3, 3], [2, 2]]]]},
        {},
    )], source_layer_id="src")
    assert len(features) == 2
    assert all(geometry["type"] == "LineString" for geometry, _ in features)


# ---------------------------------------------------------------------------
# Part 2 — stage-action wiring (fallback canvas path)
# ---------------------------------------------------------------------------


def _composite(qtbot, monkeypatch, project):
    pytest.importorskip("PySide6")
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    def _no_bridge():
        raise RuntimeError("bridge disabled for test")

    monkeypatch.setattr(
        "paleo_workbench.ui.qgis_stack.canvas_shim._load_mapstack", _no_bridge)
    doc = CompositeDocument(project)
    qtbot.addWidget(doc)
    return doc


def test_stage_overlay_factor_results_registers_six_children(qtbot, monkeypatch):
    from paleo_workbench.project.factor_grid_artifacts import (
        clear_live_factor_grid,
        store_live_factor_grid,
    )

    project = _document()
    task = _task()
    project.factor_map_tasks.append(task)
    doc = _composite(qtbot, monkeypatch, project)
    store_live_factor_grid(str(task.id), _grid(True))
    try:
        doc.stage_actions.overlay_factor_results()
    finally:
        clear_live_factor_grid(str(task.id))

    state = doc.stage_controller.state
    roles = {state.membership(lid).role for lid in state.memberships}
    for role in FACTOR_CHILD_ORDER:
        assert role in roles, f"missing factor child {role}"
    # Vector children exist as real edit layers.
    for role in (LayerRole.FACTOR_INPUT, LayerRole.FACTOR_CONTOUR,
                 LayerRole.FACTOR_CLASSIFICATION, LayerRole.FACTOR_QC):
        layer_ids = [
            lid for lid in state.layers_with_role(role)
            if doc.edit_controller.layer(lid) is not None
        ]
        assert layer_ids, f"no edit layer for {role}"
    # Scalar children are descriptor-only registrations (no edit layer).
    grid_ids = state.layers_with_role(LayerRole.FACTOR_GRID)
    assert grid_ids and all(
        doc.edit_controller.layer(lid) is None for lid in grid_ids)
    # Idempotent: a second run adds nothing.
    before = set(state.memberships)
    doc.stage_actions.overlay_factor_results()
    assert set(state.memberships) == before


def test_stage_toggle_prediction_confidence_round_trip(qtbot, monkeypatch):
    project = ProjectDocument.new("Confidence")
    project.prediction_tasks.append(PredictionTask(
        name="测井预测",
        input_refs={"well_logs": ["r1"]},
        result_summary={"spatial": {
            "type": "VECTOR_POLYGONS",
            "features": [_prediction_feature(0.9)],
        }},
    ))
    doc = _composite(qtbot, monkeypatch, project)
    doc.stage_actions.toggle_prediction_confidence()
    state = doc.stage_controller.state
    confidence_ids = state.layers_with_role(LayerRole.WELL_FACIES_CONFIDENCE)
    assert confidence_ids and doc.edit_controller.layer(confidence_ids[0])
    layer = doc.edit_controller.layer(confidence_ids[0])
    assert len(list(layer.features())) == 1
    # Toggle off removes the overlay.
    doc.stage_actions.toggle_prediction_confidence()
    assert not state.layers_with_role(LayerRole.WELL_FACIES_CONFIDENCE)


def test_stage_create_integrated_boundary_from_draft_rings(qtbot, monkeypatch):
    project = ProjectDocument.new("Phase3")
    doc = _composite(qtbot, monkeypatch, project)
    state = doc.stage_controller.state
    # Build an integrated draft with one facies polygon.
    draft_id = doc.stage_actions._create_role_layer(
        "综合沉积相（草稿）", "polygon", LayerRole.INTEGRATED_FACIES,
        features=[(
            {"type": "Polygon",
             "coordinates": [[[0, 0], [4, 0], [4, 4], [0, 0]]]},
            {"facies": "滨浅湖"},
        )])
    assert draft_id
    doc.stage_actions.create_integrated_boundary()
    boundary_ids = state.layers_with_role(LayerRole.INTEGRATED_BOUNDARY)
    assert boundary_ids
    boundary = doc.edit_controller.layer(boundary_ids[0])
    features = list(boundary.features())
    assert len(features) == 1
    assert features[0].geometry["type"] == "LineString"
    # Idempotent: second call reports existence without duplicating.
    doc.stage_actions.create_integrated_boundary()
    assert len(state.layers_with_role(LayerRole.INTEGRATED_BOUNDARY)) == 1
