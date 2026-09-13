"""拓扑编辑二阶段：线约束/综合相/注记走原生会话；悬挂点规则进检查器默认集。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication

QApplication.instance() or QApplication([])

from paleo_workbench.mapping.topology_checker import TopologyChecker
from paleo_workbench.mapping.vector_layer import VectorFeature, VectorLayer
from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.ui.workstation.composite_editing import CompositeEditController
from paleo_workbench.ui.workstation.topology_checker_panel import _RULE_LABELS


class _Stack:
    def start_mirror_layer_editing(self, doc_id):
        return ""

    def commit_mirror_layer(self, doc_id):
        return ""

    def roll_back_mirror_layer(self, doc_id):
        return ""

    def mirror_layer_editing(self, doc_id):
        return False

    def set_committed_callback(self, canvas, callback):
        pass

    def mirror_features_json(self, doc_id, limit=0):
        return '{"exists": true, "features": []}'


def _controller(*, kind: str, role: str = "") -> tuple[CompositeEditController, VectorLayer]:
    controller = CompositeEditController()
    layer = VectorLayer(
        id="layer-1", name="layer-1", crs="",
        features=[VectorFeature("f0", {"type": "LineString",
                                       "coordinates": [[0, 0], [1, 0]]}, {})],
    )
    controller._layers[layer.id] = layer
    controller._kinds[layer.id] = kind
    if role:
        controller._layer_roles[layer.id] = role
    controller._canvas = SimpleNamespace(stack=_Stack(), canvas_address=1)
    return controller, layer


def test_native_session_eligible_for_line_constraint():
    controller, layer = _controller(
        kind="line", role=LayerRole.FAULT_CONSTRAINT.value)
    assert controller._native_session_eligible(layer) is True


def test_native_session_eligible_for_integrated_facies_polygon():
    controller, layer = _controller(
        kind="polygon", role=LayerRole.INTEGRATED_FACIES.value)
    layer.features = [VectorFeature(
        "f0", {"type": "Polygon",
               "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}, {})]
    assert controller._native_session_eligible(layer) is True


def test_native_session_eligible_for_map_annotation_point():
    controller, layer = _controller(
        kind="point", role=LayerRole.MAP_ANNOTATION.value)
    layer.features = [VectorFeature(
        "f0", {"type": "Point", "coordinates": [0, 0]}, {"text": "n"})]
    assert controller._native_session_eligible(layer) is True


def test_native_session_eligible_for_interpretation_annotation():
    controller, layer = _controller(
        kind="point", role=LayerRole.INTERPRETATION_ANNOTATION.value)
    assert controller._native_session_eligible(layer) is True


def test_native_session_not_eligible_for_unrelated_point():
    controller, layer = _controller(kind="point", role=LayerRole.FACTOR_INPUT.value)
    assert controller._native_session_eligible(layer) is False


def test_checker_default_rules_include_dangle(monkeypatch):
    seen = {}

    class _Stack:
        def run_geometry_checks(self, canvas, config_json):
            import json
            seen["config"] = json.loads(config_json)
            return {"errors": []}

    checker = TopologyChecker()
    checker.run(_Stack(), 1, ["line-1"])
    assert "dangle" in seen["config"]["rules"]


def test_panel_exposes_dangle_rule_filter():
    assert _RULE_LABELS["dangle"] == "线悬挂点"
