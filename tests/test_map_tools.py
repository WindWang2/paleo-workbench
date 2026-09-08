"""Renderer-independent GIS map-tool state machine contracts."""

from __future__ import annotations

from paleo_workbench.mapping.map_tools import (
    AddLineTool,
    AddPointTool,
    AddPolygonTool,
    MapToolController,
    MeasureDistanceTool,
    SelectTool,
)
from paleo_workbench.mapping.vector_layer import VectorFeature, VectorLayer


def _session():
    layer = VectorLayer(
        id="facies",
        name="Facies",
        features=[VectorFeature("f1", {"type": "Point", "coordinates": [1, 1]})],
    )
    return layer, layer.start_editing()


def test_map_tool_controller_keeps_exactly_one_tool_active() -> None:
    layer, session = _session()
    selected = SelectTool(layer, identify=lambda _point: "f1")
    add_point = AddPointTool(session, feature_id_factory=lambda: "f2")
    controller = MapToolController()

    controller.set_active_tool(selected)
    assert controller.active_tool is selected
    controller.set_active_tool(add_point)

    assert controller.active_tool is add_point
    assert selected.active is False
    assert add_point.active is True


def test_select_tool_updates_host_feature_selection_by_id() -> None:
    layer, session = _session()
    tool = SelectTool(layer, identify=lambda _point: "f1")
    tool.mouse_press((1.0, 1.0))
    assert layer.selection == {"f1"}
    tool.mouse_press((1.0, 1.0), modifiers={"ctrl"})
    assert layer.selection == set()


def test_capture_tools_create_features_and_escape_only_cancels_capture() -> None:
    layer, session = _session()
    polygon = AddPolygonTool(session, feature_id_factory=lambda: "poly-1")
    controller = MapToolController()
    controller.set_active_tool(polygon)
    polygon.mouse_press((0.0, 0.0))
    polygon.mouse_press((2.0, 0.0))
    polygon.mouse_press((2.0, 2.0))
    polygon.mouse_press((0.0, 0.0), button="right")

    assert session.feature("poly-1").geometry["type"] == "Polygon"
    assert session.feature("poly-1").geometry["coordinates"][0][-1] == (0.0, 0.0)
    # Finished capture has no in-progress vertices; Escape is a no-op (#624).
    assert controller.key_press("escape") is False
    assert session.feature("poly-1").feature_id == "poly-1"


def test_escape_cancels_an_unfinished_capture_without_rolling_back_the_session() -> None:
    layer, session = _session()
    point = AddPointTool(session, feature_id_factory=lambda: "p2")
    controller = MapToolController()
    controller.set_active_tool(point)
    # Empty capture is not an edit: Escape must not claim it handled a cancel
    # (#624 — `had_points or True` used to force a full composition resync).
    assert controller.key_press("escape") is False
    point.mouse_press((3.0, 4.0))
    assert session.feature("p2").geometry["coordinates"] == (3.0, 4.0)


def test_empty_polygon_cancel_is_false_in_progress_cancel_is_true() -> None:
    """#624: cancel() reports whether any captured vertices were discarded."""
    _layer, session = _session()
    polygon = AddPolygonTool(session, feature_id_factory=lambda: "poly-esc")
    assert polygon.cancel() is False
    polygon.mouse_press((0.0, 0.0))
    polygon.mouse_press((1.0, 0.0))
    assert polygon.points
    assert polygon.cancel() is True
    assert polygon.points == []
    assert polygon.cancel() is False


def test_measure_distance_tool_reports_map_space_distance_without_editing() -> None:
    received: list[float] = []
    tool = MeasureDistanceTool(measurement_ready=received.append)

    tool.mouse_press((0.0, 0.0))
    tool.mouse_move((3.0, 4.0))
    tool.mouse_press((3.0, 4.0))

    assert received == [5.0]
    assert tool.points == [(3.0, 4.0), (3.0, 4.0)]


def test_capture_tool_commit_geometry_from_native_digitize() -> None:
    """M3 Task 2：原生采点完成几何经 commit_geometry 落权威会话。"""
    layer, session = _session()
    tool = AddPointTool(session, feature_id_factory=lambda: "f-new")

    assert tool.commit_geometry({"type": "Point", "coordinates": [7.0, 8.0]}) is True
    features = session.features()
    assert len(features) == 2
    added = [f for f in features if f.feature_id == "f-new"][0]
    assert added.geometry["type"] == "Point"
    assert list(added.geometry["coordinates"]) == [7.0, 8.0]
    # undo 链完好（命令模式权威不变）
    assert session.undo() is True
    assert len(session.features()) == 1

    # 几何类型不匹配 / 空几何拒绝
    assert tool.commit_geometry({"type": "LineString", "coordinates": [[0, 0], [1, 1]]}) is False
    assert tool.commit_geometry({}) is False
    assert len(session.features()) == 1


def test_move_tool_commit_move_from_native_drag() -> None:
    """M3 Task 3：原生移动工具位移经 commit_move 落权威会话。"""
    from paleo_workbench.mapping.map_tools import MoveFeatureTool

    layer, session = _session()
    tool = MoveFeatureTool(session, identify=lambda _p: "f1")

    assert tool.commit_move("f1", 2.0, 3.0) is True
    moved = session.feature("f1")
    assert list(moved.geometry["coordinates"]) == [3.0, 4.0]
    assert session.undo() is True
    assert list(session.feature("f1").geometry["coordinates"]) == [1, 1]
    # 未知要素拒绝且不产生命令
    assert tool.commit_move("nope", 1.0, 1.0) is False


def test_vertex_tool_commit_vertex_move_from_native_drag() -> None:
    """M3 Task 3：原生顶点工具拖动经 commit_vertex_move 落权威会话。"""
    from paleo_workbench.mapping.map_tools import VertexTool

    layer = VectorLayer(
        id="poly",
        name="Poly",
        features=[VectorFeature(
            "p1",
            {"type": "Polygon",
             "coordinates": [[[5.0, 5.0], [8.0, 5.0], [8.0, 8.0], [5.0, 8.0], [5.0, 5.0]]]},
        )],
    )
    session = layer.start_editing()
    committed = []
    tool = VertexTool(
        session,
        identify_vertex=lambda _p: None,
        on_vertex_committed=lambda fid, path, origin, point: committed.append(
            (fid, path, origin, point)),
    )

    assert tool.commit_vertex_move("p1", (0, 1), (9.0, 5.0)) is True
    ring = session.feature("p1").geometry["coordinates"][0]
    assert list(ring[1]) == [9.0, 5.0]
    assert committed == [("p1", (0, 1), (8.0, 5.0), (9.0, 5.0))]
    assert session.undo() is True
    assert list(session.feature("p1").geometry["coordinates"][0][1]) == [8.0, 5.0]
    # 未知要素 / 无效路径拒绝
    assert tool.commit_vertex_move("nope", (0, 0), (0.0, 0.0)) is False
    assert tool.commit_vertex_move("p1", (9, 9), (0.0, 0.0)) is False


def test_select_tool_commit_selection_modifier_semantics() -> None:
    """M3 Task 4：原生选择结果落选集；无=替换/Ctrl=并/Shift=差/Ctrl+Shift=交。"""
    layer = VectorLayer(
        id="facies",
        name="Facies",
        features=[
            VectorFeature("f1", {"type": "Point", "coordinates": [1, 1]}),
            VectorFeature("f2", {"type": "Point", "coordinates": [2, 2]}),
        ],
    )
    tool = SelectTool(layer, identify=lambda _p: None)

    assert tool.commit_selection(["f1"]) is True
    assert layer.selection == {"f1"}
    tool.commit_selection(["f2"], ["ctrl"])
    assert layer.selection == {"f1", "f2"}
    tool.commit_selection(["f1"], ["shift"])
    assert layer.selection == {"f2"}
    tool.commit_selection(["f1", "f2"], ["ctrl", "shift"])
    assert layer.selection == {"f2"}
    tool.commit_selection([], [])
    assert layer.selection == set()


def test_capture_vertex_clicks_request_overlay_repaint() -> None:
    """线/面采点期间每个顶点点击都要回报「已处理」→ 画布重绘 overlay。

    回归：此前线/面 mouse_press 加点后返回 False，画布不重绘，绘制
    过程完全不可见，只有右键结束才能看到要素。
    """
    layer, session = _session()
    line = AddLineTool(session, feature_id_factory=lambda: "line-1")

    assert line.mouse_press((0.0, 0.0)) is True
    assert line.mouse_press((1.0, 1.0)) is True


def test_capture_mouse_move_requests_repaint_only_mid_capture() -> None:
    layer, session = _session()
    line = AddLineTool(session, feature_id_factory=lambda: "line-1")

    # 未开始采点：悬停不重绘（裸悬停不得触发逐帧重绘）。
    assert line.mouse_move((0.5, 0.5)) is False
    line.mouse_press((0.0, 0.0))
    # 采集中：橡皮筋终点变化需要逐帧重绘。
    assert line.mouse_move((0.5, 0.5)) is True


def test_capture_edits_data_flag_is_dynamic() -> None:
    """采集中 = False（只刷 overlay）；要素落地后 = True（全量重组合）。"""
    layer, session = _session()
    polygon = AddPolygonTool(session, feature_id_factory=lambda: "poly-1")
    polygon.mouse_press((0.0, 0.0))
    assert polygon.edits_data is False

    polygon.mouse_press((2.0, 0.0))
    polygon.mouse_press((2.0, 2.0))
    assert polygon.mouse_press((0.0, 0.0), button="right") is True
    assert polygon.edits_data is True
    assert session.feature("poly-1") is not None


class TestRectangleSelectModifierParity:
    """V7 P2-4：矩形选择修饰键语义对齐 QGIS 桌面（无=替换 / Ctrl=并 /
    Shift=差 / Ctrl+Shift=交），与原生 commit_selection 一致。"""

    def _tool(self, selection=None):
        from paleo_workbench.mapping.map_tools import RectangleSelectTool
        from paleo_workbench.mapping.vector_layer import VectorFeature, VectorLayer

        layer = VectorLayer(id="composite:L", name="x")
        layer.start_editing()
        for i in range(4):
            layer.edit_session.add_feature(
                VectorFeature(
                    f"f{i}",
                    {"type": "Point", "coordinates": [float(i), 0.0]},
                    {},
                )
            )
        layer.set_selection(selection or ("f0", "f1"))
        hits = {"f1", "f2"}

        def _rect(_start, _end):
            return set(hits)

        return RectangleSelectTool(layer, select_rectangle=_rect), layer

    def test_plain_replace(self):
        tool, layer = self._tool()
        tool.mouse_press((0, 0))
        tool.mouse_release((5, 5))
        assert layer.selection == {"f1", "f2"}

    def test_ctrl_union(self):
        tool, layer = self._tool()
        tool.mouse_press((0, 0))
        tool.mouse_release((5, 5), modifiers=("ctrl",))
        assert layer.selection == {"f0", "f1", "f2"}

    def test_shift_difference(self):
        tool, layer = self._tool()
        tool.mouse_press((0, 0))
        tool.mouse_release((5, 5), modifiers=("shift",))
        assert layer.selection == {"f0"}

    def test_ctrl_shift_intersection(self):
        tool, layer = self._tool()
        tool.mouse_press((0, 0))
        tool.mouse_release((5, 5), modifiers=("ctrl", "shift"))
        assert layer.selection == {"f1"}
