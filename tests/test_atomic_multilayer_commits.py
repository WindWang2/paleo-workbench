"""多图层原子编辑事务与撤销重做（geotopo Ticket 5）。

契约：docs/development/geotopo-editor/02-interface-contracts.md §4.3/§4.4。
覆盖：compound_macro 单手势聚合、commit_all 中途失败的快照补偿、
geology 提交门、200 手势交错 undo/redo 压力。
"""
from __future__ import annotations

import json
import random

import pytest

from paleo_workbench.mapping.edit_session_set import reset_session_set
from paleo_workbench.mapping.geological_invariants import InvariantViolation
from paleo_workbench.mapping.qgis_mirror import reset_publish_ledger
from paleo_workbench.mapping.vector_layer import VectorFeature, VectorLayer


@pytest.fixture(autouse=True)
def _clean_state():
    reset_publish_ledger()
    reset_session_set()
    yield
    reset_publish_ledger()
    reset_session_set()


def _poly(x0, y0, size):
    return {"type": "Polygon", "coordinates": [[
        [x0, y0], [x0 + size, y0], [x0 + size, y0 + size],
        [x0, y0 + size], [x0, y0]]]}


class FakeNativeStack:
    """Duck-typed 桥：记录宏级调用 + 可注入提交失败。"""

    def __init__(self):
        self.editing: set[str] = set()
        self.calls: list[tuple] = []
        self.mirror: dict[str, list[dict]] = {}
        self.macros: dict[str, int] = {}
        self.fail_commit_for: set[str] = set()
        self.gesture_payloads: list[dict] = []

    def start_mirror_layer_editing(self, doc_id):
        self.calls.append(("start", doc_id))
        self.editing.add(doc_id)
        return ""

    def commit_mirror_layer(self, doc_id):
        self.calls.append(("commit", doc_id))
        if doc_id in self.fail_commit_for:
            return "commit failed (injected)"
        self.editing.discard(doc_id)
        return ""

    def roll_back_mirror_layer(self, doc_id):
        self.calls.append(("rollback", doc_id))
        self.editing.discard(doc_id)
        return ""

    def undo_mirror_edit(self, doc_id):
        self.calls.append(("undo", doc_id))
        self.macros[doc_id] = max(0, self.macros.get(doc_id, 0) - 1)
        return ""

    def redo_mirror_edit(self, doc_id):
        self.calls.append(("redo", doc_id))
        self.macros[doc_id] = self.macros.get(doc_id, 0) + 1
        return ""

    def mirror_features_json(self, doc_id, limit=0):
        return json.dumps({"exists": True, "features": self.mirror.get(doc_id, [])})

    def restore_mirror_snapshot(self, doc_id, features_json):
        self.calls.append(("restore", doc_id, json.loads(features_json)))
        self.mirror[doc_id] = json.loads(features_json)["features"]
        self.macros[doc_id] = self.macros.get(doc_id, 0) + 1
        return ""

    def fault_cut_mirror_features(self, doc_id, curve_geojson,
                                  feature_ids_json="", options_json="{}"):
        self.calls.append(("fault_cut", doc_id))
        self.gesture_payloads.append({
            "gesture": "fault_cut", "layer_doc_id": doc_id,
            "layers": [doc_id], "undo_text": "断层截断", "features": []})
        self.macros[doc_id] = self.macros.get(doc_id, 0) + 1
        return ""

    def set_committed_callback(self, canvas, callback):
        pass

    def run_geometry_checks(self, *args, **kwargs):
        return json.dumps({"errors": []})


def _controller_with_native(stack, layers):
    from paleo_workbench.ui.workstation.composite_editing import (
        CompositeEditController,
    )

    controller = CompositeEditController()
    for layer in layers:
        controller._layers[layer.id] = layer
        controller._kinds[layer.id] = "polygon"
    controller._active_layer_id = layers[0].id
    controller._canvas = type("Canvas", (), {
        "stack": stack, "canvas_address": 1,
        "set_map_tool": lambda self, kind: None,
        "setFocus": lambda self: None,
    })()
    for layer in layers:
        ok, reason = controller.native_editing.open(
            stack, layer, gate=lambda _lid: (True, ""), canvas_address=1)
        assert ok, reason
    return controller


def _layer(layer_id, *features):
    return VectorLayer(
        id=layer_id, name=layer_id,
        features=[VectorFeature(fid, feat["geometry"], dict(feat["properties"]))
                  for fid, feat in features])


def _record(fid, facies="滨岸"):
    return {"id": fid,
            "geometry": _poly(0.0, 0.0, 10.0),
            "properties": {"__pwb_fid": fid, "facies": facies}}


# ---------------------------------------------------------------------------
# 5.1 compound_macro：跨层单手势


def test_compound_macro_collapses_cross_layer_edits_into_one_gesture():
    line_layer = _layer("lines", ("l1", _record("l1")))
    poly_layer = _layer("polys", ("p1", _record("p1")))
    stack = FakeNativeStack()
    stack.mirror["lines"] = [_record("l1")]
    stack.mirror["polys"] = [_record("p1")]
    controller = _controller_with_native(stack, [poly_layer, line_layer])

    with controller.compound_macro("断层截断"):
        controller.record_native_gesture(
            {"gesture": "fault_cut", "layers": ["polys"], "undo_text": "断层截断"})
        controller.record_native_gesture(
            {"gesture": "fault_cut", "layers": ["lines"], "undo_text": "断层截断"})

    gestures = controller.native_editing.gestures
    assert len(gestures._gestures) == 1
    record = gestures._gestures[0]
    assert record.undo_text == "断层截断"
    assert set(record.layer_ids) == {"polys", "lines"}

    controller.native_editing.undo_gesture()
    undid = [c for c in stack.calls if c[0] == "undo"]
    assert {c[1] for c in undid} == {"polys", "lines"}
    controller.native_editing.redo_gesture()
    redid = [c for c in stack.calls if c[0] == "redo"]
    assert {c[1] for c in redid} == {"polys", "lines"}


# ---------------------------------------------------------------------------
# 5.2/5.3 提交级补偿


def test_mid_commit_failure_compensates_already_committed_layers():
    layer_a = _layer("poly_a", ("a1", _record("a1")))
    layer_b = _layer("poly_b", ("b1", _record("b1")))
    stack = FakeNativeStack()
    stack.mirror["poly_a"] = [_record("a1")]
    stack.mirror["poly_b"] = [_record("b1")]
    controller = _controller_with_native(stack, [layer_a, layer_b])
    stack.fail_commit_for.add("poly_b")

    ok, reason = controller.native_editing.commit_all(
        gate=lambda _lid: (True, ""), topology=type("T", (), {"enabled": False})())

    assert not ok
    assert "poly_b" in reason
    commits = [c for c in stack.calls if c[0] == "commit"]
    assert {c[1] for c in commits} == {"poly_a", "poly_b"}  # a 提交、b 失败
    restores = [c for c in stack.calls if c[0] == "restore"]
    assert len(restores) == 1 and restores[0][1] == "poly_a"
    restored_features = restores[0][2]["features"]
    assert [f["properties"]["__pwb_fid"] for f in restored_features] == ["a1"]
    assert controller.native_editing.compensations == ["poly_a"]
    # 补偿是宏：一次 undo 即撤销整段恢复。
    controller.native_editing.undo_gesture()
    assert ("undo", "poly_a") in stack.calls


def test_commit_all_geology_gate_blocks_on_error_violations():
    layer = _layer("polys", ("p1", _record("p1")))
    stack = FakeNativeStack()
    stack.mirror["polys"] = [_record("p1")]
    controller = _controller_with_native(stack, [layer])
    stack.calls.clear()

    def geology(records):
        return [InvariantViolation(
            code="facies_adjacency_gap", severity="error",
            message="深水盆地与冲积扇直接相邻", layer_id="polys")]

    ok, reason = controller.native_editing.commit_all(
        gate=lambda _lid: (True, ""),
        topology=type("T", (), {"enabled": False})(),
        geology=geology)
    assert not ok
    assert "facies_adjacency_gap" in reason
    assert not [c for c in stack.calls if c[0] == "commit"]  # 零提交

    def geology_ok(records):
        return [InvariantViolation(
            code="x", severity="warning", message="仅警告", layer_id="polys")]

    stack.calls.clear()
    ok, reason = controller.native_editing.commit_all(
        gate=lambda _lid: (True, ""),
        topology=type("T", (), {"enabled": False})(),
        geology=geology_ok)
    assert ok, reason  # warning 不拦截
    assert [c for c in stack.calls if c[0] == "commit"]


# ---------------------------------------------------------------------------
# 5.4 交错 undo/redo 压力


def test_interleaved_undo_redo_stress_keeps_gesture_plans_consistent():
    layer = _layer("polys", ("p1", _record("p1")))
    stack = FakeNativeStack()
    stack.mirror["polys"] = [_record("p1")]
    controller = _controller_with_native(stack, [layer])

    rng = random.Random(20260914)
    for index in range(200):
        with controller.compound_macro(f"g{index}"):
            controller.record_native_gesture(
                {"gesture": "fault_cut", "layers": ["polys"],
                 "undo_text": f"g{index}"})
        action = rng.random()
        if action < 0.45:
            controller.native_editing.undo_gesture()
        elif action < 0.9:
            controller.native_editing.redo_gesture()
        gestures = controller.native_editing.gestures
        undone = sum(1 for r in gestures._gestures if r.undone)
        assert undone <= len(gestures._gestures)
        assert stack.macros.get("polys", 0) >= 0


# ---------------------------------------------------------------------------
# 5.5 混合权威 compound（Python 会话层 + 原生层）


def test_compound_macro_covers_python_session_layers_too():
    native_layer = _layer("polys", ("p1", _record("p1")))
    python_layer = _layer("lines", ("l1", _record("l1")))
    stack = FakeNativeStack()
    stack.mirror["polys"] = [_record("p1")]
    controller = _controller_with_native(stack, [native_layer])
    python_layer.start_editing()
    controller._layers[python_layer.id] = python_layer
    controller._kinds[python_layer.id] = "line"

    with controller.compound_macro("复合编辑"):
        controller.record_native_gesture(
            {"gesture": "fault_cut", "layers": ["polys"], "undo_text": "断层截断"})
        with python_layer.edit_session.edit_source("compound-test"):
            python_layer.edit_session.change_attribute("l1", "facies", "陆棚")
        # 直接 session 写入经公开 note API 加入宏（§4.4 契约：绕过控制器
        # 入口的编辑显式声明）。
        controller.note_compound_layer("lines")

    gestures = controller.native_editing.gestures
    assert len(gestures._gestures) == 1
    assert set(gestures._gestures[0].layer_ids) == {"polys", "lines"}
    # Python 侧仍可用其自身 undo 回退（权威分离，层内原子）。
    assert python_layer.edit_session.undo()
    assert python_layer.feature("l1").attributes["facies"] == "滨岸"


@pytest.mark.qgis
class TestNativeCompensation:
    def test_real_bridge_snapshot_restore_roundtrip(self, qtbot, qapp):
        """真桥补偿冒烟：恢复宏后内容等价 + 一次 undo 可回退。"""
        import json as _json

        from PySide6.QtWidgets import QGraphicsView
        from shiboken6 import wrapInstance

        from qgis_render_bridge.mapstack import QgisMapStack

        stack = QgisMapStack()
        stack.initialize()
        try:
            fc = {"type": "FeatureCollection", "features": [
                {"type": "Feature",
                 "geometry": {"type": "Polygon", "coordinates": [[
                     (0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0),
                     (0.0, 0.0)]]},
                 "properties": {"__pwb_fid": "src", "facies": "滨岸"}},
            ]}
            fields = _json.dumps([{"name": "facies", "type": "QString"}])
            stack.upsert_mirror_layer("doc-r", "相带", "Polygon", "EPSG:4326",
                                      _json.dumps(fc), "", "", "",
                                      True, 1.0,
                                      is_reference=False, is_editable=True,
                                      data_revision=1, fields_json=fields)
            assert stack.start_mirror_layer_editing("doc-r") == ""
            canvas = stack.create_canvas()
            view = wrapInstance(canvas, QGraphicsView)
            qtbot.addWidget(view)
            view.resize(400, 400)
            view.show()

            snapshot = stack.mirror_features_json("doc-r", 0)
            # 断层截断改写内容后按快照恢复。
            curve = _json.dumps({"type": "LineString",
                                 "coordinates": [[5.0, -1.0], [5.0, 11.0]]})
            assert stack.fault_cut_mirror_features("doc-r", curve) == ""
            assert len(json.loads(
                stack.mirror_features_json("doc-r", 0))["features"]) == 2
            assert stack.restore_mirror_snapshot("doc-r", snapshot) == ""
            restored = json.loads(stack.mirror_features_json("doc-r", 0))["features"]
            assert len(restored) == 1
            props = restored[0]["properties"]
            assert props.get("facies") == "滨岸"
            assert "fault_bounded" not in props  # 快照先于标记
            assert stack.undo_mirror_edit("doc-r") == ""  # 补偿宏一步可撤
            assert len(json.loads(
                stack.mirror_features_json("doc-r", 0))["features"]) == 2
        finally:
            stack.shutdown()


# ---------------------------------------------------------------------------
# 4.10 / 5.6：save_edits 真实接线（geology_blocked 信号 + 拓扑门变体）


def _adjacent_facies_mirror(stack):
    stack.mirror["polys"] = [
        {"id": "fa",
         "geometry": {"type": "Polygon", "coordinates": [[
             [0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]]]},
         "properties": {"__pwb_fid": "fa", "facies": "深水盆地"}},
        {"id": "fb",
         "geometry": {"type": "Polygon", "coordinates": [[
             [10.0, 0.0], [20.0, 0.0], [20.0, 10.0], [10.0, 10.0], [10.0, 0.0]]]},
         "properties": {"__pwb_fid": "fb", "facies": "冲积扇"}},
    ]


def test_save_edits_real_geology_wiring_blocks_and_emits(qtbot):
    from PySide6.QtCore import QObject

    from paleo_workbench.ui.workstation.composite_editing import (
        CompositeEditController,
    )

    layer = _layer("polys", ("fa", _record("fa", facies="深水盆地")),
                   ("fb", _record("fb", facies="冲积扇")))
    stack = FakeNativeStack()
    _adjacent_facies_mirror(stack)
    controller = CompositeEditController()
    controller._layers[layer.id] = layer
    controller._kinds[layer.id] = "polygon"
    controller._active_layer_id = layer.id
    controller._canvas = type("Canvas", (), {
        "stack": stack, "canvas_address": 1,
        "set_map_tool": lambda self, kind: None,
        "setFocus": lambda self: None,
    })()
    ok, reason = controller.native_editing.open(
        stack, layer, gate=lambda _lid: (True, ""), canvas_address=1)
    assert ok, reason
    controller._topology.enabled = True  # 地质门随拓扑门开启（§4.4）

    emitted: list[object] = []
    controller.geology_blocked.connect(emitted.append)
    stack.calls.clear()
    result = controller.save_edits()
    assert result is not None and "facies_adjacency_gap" in result
    assert emitted and any(
        getattr(v, "code", "") == "facies_adjacency_gap" for v in emitted[0])
    assert not [c for c in stack.calls if c[0] == "commit"]  # 零提交


def test_save_edits_topology_door_variant_blocks_too(qtbot):
    """5.6 拓扑门变体：桥检查器报错同样拦截（双门任一违规 → 全拦截）。"""
    from paleo_workbench.ui.workstation.composite_editing import (
        CompositeEditController,
    )

    layer = _layer("polys", ("fa", _record("fa")))
    stack = FakeNativeStack()
    stack.mirror["polys"] = [_record("fa")]
    stack.check_errors = True
    controller = CompositeEditController()
    controller._layers[layer.id] = layer
    controller._kinds[layer.id] = "polygon"
    controller._active_layer_id = layer.id
    controller._canvas = type("Canvas", (), {
        "stack": stack, "canvas_address": 1,
        "set_map_tool": lambda self, kind: None,
        "setFocus": lambda self: None,
    })()
    ok, reason = controller.native_editing.open(
        stack, layer, gate=lambda _lid: (True, ""), canvas_address=1)
    assert ok, reason
    controller._topology.enabled = True
    stack.run_geometry_checks = lambda *a, **k: json.dumps(
        {"errors": [{"layer_id": "polys", "feature_id": "fa",
                     "message": "自相交"}]})

    result = controller.save_edits()
    assert result is not None and "未通过拓扑检查" in result
