"""初始相图缺省：未指定初始相图时默认用工区范围的一整块空白相。"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.project.domain import WellEntity, WorkArea
from paleo_workbench.project.models import PaleoMapDocument, ProjectDocument

QApplication.instance() or QApplication([])


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
    project = ProjectDocument.new("初始相图缺省")
    project.coordinate.project_crs = "EPSG:32650"
    project.workarea = WorkArea(
        name="工区",
        boundary=[[-2, -2], [12, -2], [12, 2], [-2, 2], [-2, -2]],
        project_crs="EPSG:32650",
        boundary_crs="EPSG:32650",
    )
    project.wells.extend([
        WellEntity(id="well_a", name="A", project_x=0.0, project_y=0.0, td=1200.0),
        WellEntity(id="well_b", name="B", project_x=10.0, project_y=0.0),
    ])
    project.stratigraphy.target_horizon = "Sq1"
    return project


def _live_layers(doc, role: LayerRole) -> list:
    return [
        layer_id
        for layer_id in doc.stage_controller.state.layers_with_role(role)
        if doc.edit_controller.layer(str(layer_id)) is not None
    ]


def test_load_initial_facies_defaults_to_workarea_blank(qtbot, monkeypatch):
    project = _project()
    doc = _composite(qtbot, monkeypatch, project)
    messages = []
    doc.status_message.connect(messages.append)
    doc.stage_actions.dispatch("facies_calibration", "load_initial_facies")
    layers = _live_layers(doc, LayerRole.INITIAL_FACIES_SOURCE)
    assert len(layers) == 1
    layer = doc.edit_controller.layer(str(layers[0]))
    features = list(layer.features())
    assert len(features) == 1
    assert features[0].attributes.get("facies") == "空白相"
    geometry = features[0].geometry
    assert geometry.get("type") == "Polygon"
    ring = geometry["coordinates"][0]
    assert ring[0] == ring[-1]  # ring 闭合
    xs = [point[0] for point in ring]
    ys = [point[1] for point in ring]
    assert min(xs) <= -2 and max(xs) >= 12
    assert min(ys) <= -2 and max(ys) >= 2
    assert any("空白相" in text for text in messages)


def test_load_initial_facies_without_workarea_keeps_dead_road(qtbot, monkeypatch):
    project = _project()
    project.workarea = None
    doc = _composite(qtbot, monkeypatch, project)
    messages = []
    doc.status_message.connect(messages.append)
    doc.stage_actions.dispatch("facies_calibration", "load_initial_facies")
    assert _live_layers(doc, LayerRole.INITIAL_FACIES_SOURCE) == []
    assert any("编图页生成或导入" in text for text in messages)


def test_load_initial_facies_prefers_document(qtbot, monkeypatch):
    project = _project()
    project.paleomap_documents.append(PaleoMapDocument(
        name="已有相图",
        linked_target_horizon="Sq1",
        facies_polygons=[{
            "facies": "砂岩",
            "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
            "properties": {"facies": "砂岩"},
        }],
    ))
    doc = _composite(qtbot, monkeypatch, project)
    doc.stage_actions.dispatch("facies_calibration", "load_initial_facies")
    layers = _live_layers(doc, LayerRole.INITIAL_FACIES_SOURCE)
    assert len(layers) == 1
    layer = doc.edit_controller.layer(str(layers[0]))
    assert "已有相图" in layer.name
    features = list(layer.features())
    assert features and features[0].attributes.get("facies") == "砂岩"


def test_load_initial_facies_idempotent(qtbot, monkeypatch):
    project = _project()
    doc = _composite(qtbot, monkeypatch, project)
    doc.stage_actions.dispatch("facies_calibration", "load_initial_facies")
    doc.stage_actions.dispatch("facies_calibration", "load_initial_facies")
    assert len(_live_layers(doc, LayerRole.INITIAL_FACIES_SOURCE)) == 1


def test_create_facies_draft_falls_back_to_blank(qtbot, monkeypatch):
    project = _project()
    doc = _composite(qtbot, monkeypatch, project)
    doc.stage_actions.dispatch("facies_calibration", "create_facies_draft")
    layers = _live_layers(doc, LayerRole.INITIAL_FACIES_DRAFT)
    assert len(layers) == 1
    layer = doc.edit_controller.layer(str(layers[0]))
    features = list(layer.features())
    assert features
    assert all(
        feature.attributes.get("facies") == "空白相" for feature in features)
