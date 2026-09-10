"""智能预测阶段：地震/测井叠加与测井点到面（fallback 画布）。"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from paleo_workbench.mapping.well_prediction_surface import (
    POINTS_LAYER_TASK_ID,
    SURFACE_LAYER_TASK_ID,
)
from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.project.domain import EntityAssetLink, WellEntity, WorkArea
from paleo_workbench.project.models import (
    PredictionTask,
    ProjectDocument,
    ResourceItem,
)
from paleo_workbench.ui.workstation.stage_actions import stage_context_actions

QApplication.instance() or QApplication([])


def test_dispatch_prediction_requires_horizon(qtbot, monkeypatch):
    project = ProjectDocument.new("无层位编图")
    doc = _composite(qtbot, monkeypatch, project)
    messages = []
    doc.status_message.connect(messages.append)
    doc.stage_actions.dispatch("facies_calibration", "add_well_prediction_overlay")
    assert any("编图层位" in text for text in messages)
    assert not doc.stage_controller.state.layers_with_role(
        LayerRole.WELL_FACIES_PREDICTION)


def test_phase1_actions_lead_with_prediction_results():
    actions = stage_context_actions("facies_calibration")
    ids = [action_id for action_id, _title in actions]
    assert ids[:3] == [
        "add_seismic_prediction_overlay",
        "add_well_prediction_overlay",
        "well_prediction_point_to_surface",
    ]
    labels = dict(actions)
    assert labels["add_seismic_prediction_overlay"] == "叠加地震相预测"
    assert labels["add_well_prediction_overlay"] == "叠加测井相预测"
    assert labels["well_prediction_point_to_surface"] == "测井点到面"


def _composite(qtbot, monkeypatch, project):
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    def _no_bridge():
        raise RuntimeError("bridge disabled for test")

    monkeypatch.setattr(
        "paleo_workbench.ui.qgis_stack.canvas_shim._load_mapstack", _no_bridge)
    doc = CompositeDocument(project)
    qtbot.addWidget(doc)
    return doc


def _project() -> ProjectDocument:
    project = ProjectDocument.new("智能预测叠加")
    project.coordinate.project_crs = "EPSG:32650"
    project.workarea = WorkArea(
        name="工区",
        boundary=[[-2, -2], [12, -2], [12, 2], [-2, 2], [-2, -2]],
        project_crs="EPSG:32650",
        boundary_crs="EPSG:32650",
    )
    project.wells.extend([
        WellEntity(id="well_a", name="A", project_x=0.0, project_y=0.0),
        WellEntity(id="well_b", name="B", project_x=10.0, project_y=0.0),
    ])
    project.resources.extend([
        ResourceItem(id="res_a", name="A", path="a.las", type="well_log", format="las"),
        ResourceItem(id="res_b", name="B", path="b.las", type="well_log", format="las"),
    ])
    project.entity_asset_links.extend([
        EntityAssetLink(entity_type="well", entity_id="well_a", asset_id="res_a",
                        role="well_log"),
        EntityAssetLink(entity_type="well", entity_id="well_b", asset_id="res_b",
                        role="well_log"),
    ])
    project.prediction_tasks.extend([
        PredictionTask(
            id="pred_a", name="测井相预测 A",
            input_refs={"well_log_resource_ids": ["res_a"]},
            result_summary={"predicted_regions": [
                {"facies": "三角洲", "top": 0, "bottom": 20, "probability": 0.8},
            ]},
        ),
        PredictionTask(
            id="pred_b", name="测井相预测 B",
            input_refs={"well_log_resource_ids": ["res_b"]},
            result_summary={"predicted_regions": [
                {"facies": "滨浅湖", "top": 0, "bottom": 20, "probability": 0.7},
            ]},
        ),
        PredictionTask(
            id="pred_s", name="地震相预测",
            input_refs={"seismic_resource_ids": ["seis1"]},
            result_summary={"spatial": {
                "type": "VECTOR_POLYGONS",
                "features": [{
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[0, 0], [4, 0], [4, 2], [0, 0]]],
                    },
                    "properties": {"facies": "前三角洲"},
                }],
            }},
        ),
    ])
    return project


def test_overlay_well_prediction_creates_point_layer(qtbot, monkeypatch):
    doc = _composite(qtbot, monkeypatch, _project())
    doc.stage_actions.add_well_prediction_overlay()
    ids = doc.stage_controller.state.layers_with_role(LayerRole.WELL_FACIES_PREDICTION)
    assert ids
    record = doc.stage_controller.state.membership(ids[0])
    assert record.factor_task_id == POINTS_LAYER_TASK_ID
    layer = doc.edit_controller.layer(ids[0])
    assert len(list(layer.features())) == 2


def test_overlay_seismic_prediction_creates_polygon_layer(qtbot, monkeypatch):
    doc = _composite(qtbot, monkeypatch, _project())
    doc.stage_actions.add_seismic_prediction_overlay()
    ids = doc.stage_controller.state.layers_with_role(
        LayerRole.SEISMIC_FACIES_PREDICTION)
    assert len(ids) == 1
    layer = doc.edit_controller.layer(ids[0])
    assert len(list(layer.features())) == 1


def test_well_point_to_surface_creates_polygon_layer(qtbot, monkeypatch):
    doc = _composite(qtbot, monkeypatch, _project())
    doc.stage_actions.well_prediction_point_to_surface()
    ids = [
        lid for lid in doc.stage_controller.state.layers_with_role(
            LayerRole.WELL_FACIES_PREDICTION)
        if doc.stage_controller.state.membership(lid).factor_task_id
        == SURFACE_LAYER_TASK_ID
    ]
    assert len(ids) == 1
    layer = doc.edit_controller.layer(ids[0])
    facies = {
        str((feature.attributes or {}).get("facies") or "")
        for feature in layer.features()
    }
    assert "三角洲" in facies
    assert "滨浅湖" in facies
