"""拓扑编辑迁移 M3 几何命令——宿主侧（规格 §8 → §4）。

纯 Python：合并属性计划（最大面积预填 + 相分类冲突）、原生会话下
geometry_command 的 split/merge 分支（fake stack）。真桥面场景 9/10 在
tests/test_qgis_topo_m3_geometry_commands.py。
"""
from __future__ import annotations

import json

import pytest

from paleo_workbench.mapping.edit_session_set import reset_session_set
from paleo_workbench.mapping.merge_attributes import plan_merge_attributes
from paleo_workbench.mapping.qgis_mirror import reset_publish_ledger
from paleo_workbench.mapping.vector_layer import VectorFeature, VectorLayer


@pytest.fixture(autouse=True)
def _clean_m3_state():
    reset_publish_ledger()
    reset_session_set()
    yield
    reset_publish_ledger()
    reset_session_set()


def _poly(feature_id, x0, y0, size, **attrs):
    return {
        "id": feature_id,
        "geometry": {"type": "Polygon", "coordinates": [[
            [x0, y0], [x0 + size, y0], [x0 + size, y0 + size],
            [x0, y0 + size], [x0, y0]]]},
        "properties": dict(attrs),
    }


def test_merge_plan_prefills_largest_and_flags_facies_conflict():
    """场景 10：预填面积最大要素属性；相分类字段冲突高亮。"""
    records = [
        _poly("small", 0.0, 0.0, 1.0, facies="泥岩", name="小"),
        _poly("big", 1.0, 0.0, 3.0, facies="砂岩", name="大"),
    ]
    plan = plan_merge_attributes(records, facies_fields=("facies",))
    assert plan["target_id"] == "big"
    assert plan["attributes"]["facies"] == "砂岩"
    assert plan["attributes"]["name"] == "大"
    assert "facies" in plan["conflicts"]
    assert set(plan["conflicts"]["facies"]) == {"泥岩", "砂岩"}
    assert "name" in plan["conflicts"]


def test_merge_plan_no_conflict_when_attributes_match():
    records = [
        _poly("a", 0.0, 0.0, 2.0, facies="砂岩", name="同"),
        _poly("b", 2.0, 0.0, 2.0, facies="砂岩", name="同"),
    ]
    plan = plan_merge_attributes(records, facies_fields=("facies",))
    assert plan["conflicts"] == {}
    assert plan["attributes"]["facies"] == "砂岩"


def test_merge_dialog_highlights_conflict_and_accepts(qtbot):
    from paleo_workbench.ui.workstation.merge_features_dialog import (
        MergeFeaturesDialog,
    )

    records = [
        _poly("small", 0.0, 0.0, 1.0, facies="泥岩", name="小"),
        _poly("big", 1.0, 0.0, 3.0, facies="砂岩", name="大"),
    ]
    dialog = MergeFeaturesDialog(records)
    qtbot.addWidget(dialog)
    assert dialog.plan["target_id"] == "big"
    payload = dialog.result_payload()
    assert payload["target_id"] == "big"
    assert payload["attributes"]["facies"] == "砂岩"
    # 冲突行可改：把相分类改成泥岩后再确认。
    dialog.set_field_value("facies", "泥岩")
    payload = dialog.result_payload()
    assert payload["attributes"]["facies"] == "泥岩"
    dialog.accept()
    from PySide6.QtWidgets import QDialog
    assert dialog.result() == QDialog.DialogCode.Accepted


class FakeNativeStack:
    def __init__(self):
        self.editing: set[str] = set()
        self.calls: list[tuple] = []
        self.mirror: dict[str, list[dict]] = {}

    def start_mirror_layer_editing(self, doc_id):
        self.editing.add(doc_id)
        return ""

    def commit_mirror_layer(self, doc_id):
        return ""

    def roll_back_mirror_layer(self, doc_id):
        self.editing.discard(doc_id)
        return ""

    def mirror_features_json(self, doc_id, limit=0):
        return json.dumps({
            "exists": True,
            "features": self.mirror.get(doc_id, []),
        })

    def split_mirror_features(self, doc_id, curve_geojson, feature_ids_json=""):
        self.calls.append(("split", doc_id, json.loads(curve_geojson),
                           json.loads(feature_ids_json or "[]")))
        return ""

    def merge_mirror_features(self, doc_id, feature_ids_json, attrs_json):
        self.calls.append(("merge", doc_id, json.loads(feature_ids_json),
                           json.loads(attrs_json or "{}")))
        return ""


def _controller_with_native(stack, layer):
    from paleo_workbench.ui.workstation.composite_editing import (
        CompositeEditController,
    )

    controller = CompositeEditController()
    controller._layers[layer.id] = layer
    controller._kinds[layer.id] = "polygon"
    controller._active_layer_id = layer.id
    controller._canvas = type("Canvas", (), {
        "stack": stack, "canvas_address": 1,
        "set_map_tool": lambda self, kind: None,
    })()
    ok, reason = controller.native_editing.open(
        stack, layer, gate=lambda _lid: (True, ""), canvas_address=1)
    assert ok, reason
    return controller


def test_geometry_command_native_merge_calls_bridge(monkeypatch):
    """原生会话 merge：对话框确认后走 merge_mirror_features，不经 Python 会话。"""
    layer = VectorLayer(
        id="draft", name="相带",
        features=[
            VectorFeature("big", _poly("big", 0, 0, 3)["geometry"], {"facies": "砂岩"}),
            VectorFeature("small", _poly("small", 3, 0, 1)["geometry"], {"facies": "泥岩"}),
        ])
    layer.set_selection(("big", "small"))
    stack = FakeNativeStack()
    stack.mirror["draft"] = [
        _poly("big", 0, 0, 3, facies="砂岩"),
        _poly("small", 3, 0, 1, facies="泥岩"),
    ]
    controller = _controller_with_native(stack, layer)
    monkeypatch.setattr(
        controller, "_confirm_merge_attributes",
        lambda records: {
            "target_id": "big",
            "attributes": {"facies": "砂岩"},
        })

    ok, message = controller.geometry_command("merge")
    assert ok, message
    assert stack.calls and stack.calls[0][0] == "merge"
    assert stack.calls[0][1] == "draft"
    assert set(stack.calls[0][2]) == {"big", "small"}
    assert stack.calls[0][3]["target_id"] == "big"


def test_geometry_command_native_split_uses_digitized_curve():
    """原生会话 split：切线来自画布数字化（commit_native_capture），不是选中线。"""
    layer = VectorLayer(
        id="draft", name="相带",
        features=[VectorFeature(
            "src", _poly("src", 0, 0, 4)["geometry"], {"facies": "砂岩"})])
    layer.set_selection(("src",))
    stack = FakeNativeStack()
    controller = _controller_with_native(stack, layer)

    ok, message = controller.geometry_command("split")
    assert ok, message
    assert "切线" in message
    curve = {"type": "LineString", "coordinates": [[2.0, -1.0], [2.0, 5.0]]}
    assert controller.commit_native_capture(curve) is True
    assert stack.calls and stack.calls[0][0] == "split"
    assert stack.calls[0][1] == "draft"
    assert stack.calls[0][2]["type"] == "LineString"
    assert stack.calls[0][3] == ["src"]


def test_native_split_cancel_clears_pending():
    layer = VectorLayer(
        id="draft", name="相带",
        features=[VectorFeature(
            "src", _poly("src", 0, 0, 4)["geometry"], {"facies": "砂岩"})])
    layer.set_selection(("src",))
    stack = FakeNativeStack()
    controller = _controller_with_native(stack, layer)
    ok, _message = controller.geometry_command("split")
    assert ok
    assert controller._pending_native_split == "draft"
    controller.cancel_native_capture()
    assert controller._pending_native_split is None
    curve = {"type": "LineString", "coordinates": [[2.0, -1.0], [2.0, 5.0]]}
    assert controller.commit_native_capture(curve) is False
    assert stack.calls == []


def test_python_session_split_still_uses_selected_line(qtbot, tmp_path, monkeypatch):
    """Python 会话路径保持选中线切割（M1 钉子，M3 不得吞掉）。"""
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.ui.workstation.composite_document import (
        CompositeDocument,
    )

    project = ProjectDocument.new("Pearl River Mouth", region="HZ26")
    project.meta.project_root = str(tmp_path)
    doc = CompositeDocument(project)
    qtbot.addWidget(doc)
    controller = doc.edit_controller
    monkeypatch.setattr(
        controller, "_native_session_eligible", lambda _layer: False)
    polygons = controller.create_layer("相带", "polygon", template="facies")
    lines = controller.create_layer("打断线", "line", template="break")
    controller.set_active_layer(polygons.id)
    controller.start_editing()
    polygons.edit_session.add_feature(VectorFeature(
        "poly", _poly("poly", 0, 0, 2)["geometry"], {"facies": "三角洲"}))
    polygons.set_selection({"poly"})
    lines.start_editing()
    lines.edit_session.add_feature(VectorFeature(
        "cut", {"type": "LineString", "coordinates": [[1.0, -1.0], [1.0, 3.0]]}))
    lines.set_selection({"cut"})
    ok, message = controller.geometry_command("split")
    assert ok, message
    pieces = list(polygons.edit_session.features())
    assert len(pieces) == 2
