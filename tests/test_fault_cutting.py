"""断-相协同截断（geotopo Ticket 2）——宿主编排面（fake stack）。

契约：docs/development/geotopo-editor/02-interface-contracts.md §2.1。
真桥面（真实 splitFeatures 引擎、属性克隆、fault_bounded 标记、undo）
在 ``TestNativeFaultCut``（@pytest.mark.qgis）。
"""
from __future__ import annotations

import json

import pytest

from paleo_workbench.mapping.edit_session_set import reset_session_set
from paleo_workbench.mapping.qgis_mirror import reset_publish_ledger
from paleo_workbench.mapping.vector_layer import VectorFeature, VectorLayer


@pytest.fixture(autouse=True)
def _clean_state():
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


FAULT_CURVE = {"type": "LineString", "coordinates": [[5.0, -1.0], [5.0, 11.0]]}


class FakeNativeStack:
    def __init__(self):
        self.editing: set[str] = set()
        self.calls: list[tuple] = []
        self.mirror: dict[str, list[dict]] = {}
        self.fault_cut_error = ""

    def start_mirror_layer_editing(self, doc_id):
        self.editing.add(doc_id)
        return ""

    def commit_mirror_layer(self, doc_id):
        return ""

    def roll_back_mirror_layer(self, doc_id):
        self.editing.discard(doc_id)
        return ""

    def mirror_features_json(self, doc_id, limit=0):
        return json.dumps({"exists": True, "features": self.mirror.get(doc_id, [])})

    def fault_cut_mirror_features(self, doc_id, curve_geojson, feature_ids_json="",
                                  options_json="{}"):
        self.calls.append(("fault_cut", doc_id, json.loads(curve_geojson),
                           json.loads(feature_ids_json or "[]"),
                           json.loads(options_json or "{}")))
        return self.fault_cut_error


class _Canvas:
    """Duck-typed native canvas: address + kind routing recorder."""

    def __init__(self) -> None:
        self.stack = None
        self.canvas_address = 1
        self.kinds: list[str] = []

    def set_map_tool(self, kind):
        self.kinds.append(kind)

    def setFocus(self):
        pass


def _controller_with_native(stack, layer):
    from paleo_workbench.ui.workstation.composite_editing import (
        CompositeEditController,
    )

    controller = CompositeEditController()
    controller._layers[layer.id] = layer
    controller._kinds[layer.id] = "polygon"
    controller._active_layer_id = layer.id
    canvas = _Canvas()
    canvas.stack = stack
    controller._canvas = canvas
    ok, reason = controller.native_editing.open(
        stack, layer, gate=lambda _lid: (True, ""), canvas_address=1)
    assert ok, reason
    return controller, canvas


def _facies_layer(*features):
    return VectorLayer(
        id="draft", name="相带",
        features=[VectorFeature(fid, feat["geometry"], dict(feat["properties"]))
                  for fid, feat in features])


def test_geometry_command_fault_cut_calls_bridge_with_contract_options():
    layer = _facies_layer(("src", _poly("src", 0, 0, 10, facies="三角洲")))
    stack = FakeNativeStack()
    stack.mirror["draft"] = [_poly("src", 0, 0, 10, facies="三角洲")]
    controller, _canvas = _controller_with_native(stack, layer)

    ok, message = controller.geometry_command("fault_cut", curve=FAULT_CURVE)
    assert ok, message
    assert stack.calls and stack.calls[0][0] == "fault_cut"
    assert stack.calls[0][1] == "draft"
    assert stack.calls[0][2] == FAULT_CURVE
    options = stack.calls[0][4]
    assert options["mark_field"] == "fault_bounded"


def test_fault_cut_selection_forwarded_when_present():
    layer = _facies_layer(
        ("a", _poly("a", 0, 0, 5, facies="滨岸")),
        ("b", _poly("b", 5, 0, 5, facies="陆棚")))
    layer.set_selection(("b", "a"))
    stack = FakeNativeStack()
    stack.mirror["draft"] = [
        _poly("a", 0, 0, 5, facies="滨岸"), _poly("b", 5, 0, 5, facies="陆棚")]
    controller, _canvas = _controller_with_native(stack, layer)

    ok, message = controller.geometry_command("fault_cut", curve=FAULT_CURVE)
    assert ok, message
    assert sorted(stack.calls[0][3]) == ["a", "b"]


def test_fault_cut_refused_for_python_session_layer():
    from paleo_workbench.ui.workstation.composite_editing import (
        CompositeEditController,
    )

    controller = CompositeEditController()
    layer = _facies_layer(("src", _poly("src", 0, 0, 10, facies="三角洲")))
    controller._layers[layer.id] = layer
    controller._kinds[layer.id] = "polygon"
    controller._active_layer_id = layer.id
    layer.start_editing()

    ok, message = controller.geometry_command("fault_cut", curve=FAULT_CURVE)
    assert not ok
    assert "原生" in message or "native" in message.lower()


def test_fault_cut_refused_on_legacy_bridge():
    class LegacyStack(FakeNativeStack):
        fault_cut_mirror_features = None  # type: ignore[assignment]

    layer = _facies_layer(("src", _poly("src", 0, 0, 10, facies="三角洲")))
    stack = LegacyStack()
    stack.mirror["draft"] = [_poly("src", 0, 0, 10, facies="三角洲")]
    controller, _canvas = _controller_with_native(stack, layer)

    ok, message = controller.geometry_command("fault_cut", curve=FAULT_CURVE)
    assert not ok
    assert "断层" in message or "fault" in message.lower()


def test_fault_cut_bridge_error_code_surfaced():
    layer = _facies_layer(("src", _poly("src", 0, 0, 10, facies="三角洲")))
    stack = FakeNativeStack()
    stack.fault_cut_error = "PWB-GT-102: no features intersect the fault curve"
    stack.mirror["draft"] = [_poly("src", 0, 0, 10, facies="三角洲")]
    controller, _canvas = _controller_with_native(stack, layer)

    ok, message = controller.geometry_command("fault_cut", curve=FAULT_CURVE)
    assert not ok
    assert "PWB-GT-102" in message


def test_activate_tool_fault_cut_sets_native_placeholder():
    layer = _facies_layer(("src", _poly("src", 0, 0, 10, facies="三角洲")))
    stack = FakeNativeStack()
    stack.mirror["draft"] = [_poly("src", 0, 0, 10, facies="三角洲")]
    controller, _canvas = _controller_with_native(stack, layer)

    controller.activate_tool("fault_cut")
    assert controller._active_tool_action == "fault_cut"
    active = controller.tools.active_tool
    assert getattr(active, "native_digitize_kind", None) == "faultCut"


def test_activate_tool_fault_cut_refused_without_native_canvas():
    layer = _facies_layer(("src", _poly("src", 0, 0, 10, facies="三角洲")))
    stack = FakeNativeStack()
    stack.mirror["draft"] = [_poly("src", 0, 0, 10, facies="三角洲")]
    controller, canvas = _controller_with_native(stack, layer)
    del canvas.canvas_address  # 非原生画布

    controller.activate_tool("fault_cut")
    assert controller._active_tool_action != "fault_cut"


def test_activate_tool_fault_cut_refused_for_non_polygon_layer():
    layer = _facies_layer(("src", _poly("src", 0, 0, 10, facies="三角洲")))
    stack = FakeNativeStack()
    stack.mirror["draft"] = [_poly("src", 0, 0, 10, facies="三角洲")]
    controller, _canvas = _controller_with_native(stack, layer)
    controller._kinds[layer.id] = "line"

    controller.activate_tool("fault_cut")
    assert controller._active_tool_action != "fault_cut"


# ---------------------------------------------------------------------------
# 真桥面：真实 splitFeatures 引擎 / 属性克隆 / fault_bounded 标记 / undo。


@pytest.mark.qgis
class TestNativeFaultCut:
    @staticmethod
    def _setup_stack(qtbot, qapp):
        import json as _json

        from PySide6.QtWidgets import QGraphicsView
        from shiboken6 import wrapInstance

        from qgis_render_bridge.mapstack import QgisMapStack

        stack = QgisMapStack()
        stack.initialize()
        fc = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature",
                 "geometry": {"type": "Polygon", "coordinates": [[
                     (0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)]]},
                 "properties": {"__pwb_fid": "src", "facies": "三角洲"}},
            ],
        }
        fields = _json.dumps([{"name": "facies", "type": "QString"}])
        stack.upsert_mirror_layer("doc-draft", "相带", "Polygon", "EPSG:4326",
                                  _json.dumps(fc), "", "", "",
                                  True, 1.0,
                                  is_reference=False, is_editable=True,
                                  data_revision=1, fields_json=fields)
        assert stack.start_mirror_layer_editing("doc-draft") == ""
        canvas = stack.create_canvas()
        view = wrapInstance(canvas, QGraphicsView)
        qtbot.addWidget(view)
        view.resize(400, 400)
        view.show()
        events: list[tuple[str, dict]] = []
        stack.set_edit_pick_callback(
            canvas, lambda action, payload: events.append((action, json.loads(payload))))
        return stack, events, canvas

    @staticmethod
    def _readback(stack):
        payload = json.loads(stack.mirror_features_json("doc-draft", 0))
        assert payload["exists"]
        return payload["features"]

    def test_full_crossing_cut_clones_attributes_and_marks(self, qtbot, qapp):
        stack, events, _canvas = self._setup_stack(qtbot, qapp)
        try:
            curve = json.dumps({"type": "LineString",
                                "coordinates": [[5.0, -1.0], [5.0, 11.0]]})
            error = stack.fault_cut_mirror_features("doc-draft", curve)
            assert error == "", error

            features = self._readback(stack)
            assert len(features) == 2
            for feature in features:
                props = feature.get("properties") or {}
                assert props.get("facies") == "三角洲"
                assert props.get("fault_bounded") in (True, "true", 1)
            areas = sorted(
                abs(sum(ring[i][0] * ring[(i + 1) % len(ring)][1]
                        - ring[(i + 1) % len(ring)][0] * ring[i][1]
                        for i in range(len(ring))) / 2)
                for ring in [f["geometry"]["coordinates"][0] for f in features])
            assert areas[0] == pytest.approx(50.0)
            assert areas[1] == pytest.approx(50.0)

            gestures = [p for a, p in events if a == "edit_gesture"]
            assert gestures and gestures[-1]["gesture"] == "fault_cut"
            assert gestures[-1]["undo_text"] == "断层截断"
            assert "doc-draft" in gestures[-1]["layers"]
            assert "src" in gestures[-1]["features"]
        finally:
            stack.shutdown()

    def test_side_field_stamps_opposite_walls(self, qtbot, qapp):
        stack, _events, _canvas = self._setup_stack(qtbot, qapp)
        try:
            curve = json.dumps({"type": "LineString",
                                "coordinates": [[5.0, -1.0], [5.0, 11.0]]})
            options = json.dumps({"mark_field": "fault_bounded",
                                  "side_field": "fault_side"})
            error = stack.fault_cut_mirror_features("doc-draft", curve, "", options)
            assert error == "", error
            sides = sorted(
                str(f.get("properties", {}).get("fault_side"))
                for f in self._readback(stack))
            assert sides == ["footwall", "hanging"]
        finally:
            stack.shutdown()

    def test_no_intersection_returns_contract_error(self, qtbot, qapp):
        stack, _events, _canvas = self._setup_stack(qtbot, qapp)
        try:
            curve = json.dumps({"type": "LineString",
                                "coordinates": [[50.0, 50.0], [60.0, 60.0]]})
            error = stack.fault_cut_mirror_features("doc-draft", curve)
            assert error.startswith("PWB-GT-102")
            assert len(self._readback(stack)) == 1  # 层内容零变更
        finally:
            stack.shutdown()

    def test_partial_penetration_is_refused_idempotent(self, qtbot, qapp):
        stack, _events, _canvas = self._setup_stack(qtbot, qapp)
        try:
            curve = json.dumps({"type": "LineString",
                                "coordinates": [[5.0, 0.0], [5.0, 5.0]]})
            error = stack.fault_cut_mirror_features("doc-draft", curve)
            assert error.startswith("PWB-GT-104")
            features = self._readback(stack)
            assert len(features) == 1  # 未贯穿：幂等无痕
        finally:
            stack.shutdown()

    def test_undo_restores_single_polygon(self, qtbot, qapp):
        stack, _events, _canvas = self._setup_stack(qtbot, qapp)
        try:
            curve = json.dumps({"type": "LineString",
                                "coordinates": [[5.0, -1.0], [5.0, 11.0]]})
            assert stack.fault_cut_mirror_features("doc-draft", curve) == ""
            assert len(self._readback(stack)) == 2
            assert stack.undo_mirror_edit("doc-draft") == ""
            assert len(self._readback(stack)) == 1
        finally:
            stack.shutdown()


    def test_z_fault_across_two_adjacent_faces(self, qtbot, qapp):
        """2.3：Z 形断层一次穿越两相邻面——两面均分割，单手势多层。"""
        stack, events, canvas = self._setup_stack(qtbot, qapp)
        try:
            from qgis_render_bridge.mapstack import QgisMapStack  # noqa: F401
            fc = {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature",
                     "geometry": {"type": "Polygon", "coordinates": [[
                         (0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0),
                         (0.0, 0.0)]]},
                     "properties": {"__pwb_fid": "fa", "facies": "滨岸"}},
                    {"type": "Feature",
                     "geometry": {"type": "Polygon", "coordinates": [[
                         (10.0, 0.0), (20.0, 0.0), (20.0, 10.0), (10.0, 10.0),
                         (10.0, 0.0)]]},
                     "properties": {"__pwb_fid": "fb", "facies": "陆棚"}},
                ],
            }
            fields = json.dumps([{"name": "facies", "type": "QString"}])
            stack.upsert_mirror_layer("doc-draft", "相带", "Polygon", "EPSG:4326",
                                      json.dumps(fc), "", "", "",
                                      True, 1.0,
                                      is_reference=False, is_editable=True,
                                      data_revision=2, fields_json=fields)
            curve = json.dumps({"type": "LineString", "coordinates": [
                [5.0, -1.0], [5.0, 5.0], [15.0, 5.0], [15.0, 11.0]]})
            error = stack.fault_cut_mirror_features("doc-draft", curve)
            assert error == "", error
            features = self._readback(stack)
            assert len(features) == 4  # 两面各一分为二
            for feature in features:
                assert feature.get("properties", {}).get("facies") in ("滨岸", "陆棚")
                assert feature.get("properties", {}).get("fault_bounded") in (True, "true", 1)
            gestures = [p for a, p in events if a == "edit_gesture"]
            assert gestures and gestures[-1]["gesture"] == "fault_cut"
        finally:
            stack.shutdown()

    def test_endpoints_exactly_on_boundary_split_pinned(self, qtbot, qapp):
        """2.4：断层两端点正好落在面边界上（不多出不少）——钉死为 2 面。"""
        stack, _events, _canvas = self._setup_stack(qtbot, qapp)
        try:
            curve = json.dumps({"type": "LineString",
                                "coordinates": [[5.0, 0.0], [5.0, 10.0]]})
            error = stack.fault_cut_mirror_features("doc-draft", curve)
            assert error == "", error
            assert len(self._readback(stack)) == 2  # 边界到边界恰好分割
        finally:
            stack.shutdown()

    def test_map_tool_fault_cut_kind_activates(self, qtbot, qapp):
        stack, _events, _canvas = self._setup_stack(qtbot, qapp)
        try:
            canvas = _canvas  # create_canvas 返回的画布地址
            stack.set_canvas_extent(canvas, 0.0, 0.0, 10.0, 10.0)
            stack.set_current_layer(canvas, "doc-draft")
            stack.set_map_tool(canvas, "faultCut")  # 不抛即工具注册成功
            stack.set_map_tool(canvas, "pan")
        finally:
            stack.shutdown()
