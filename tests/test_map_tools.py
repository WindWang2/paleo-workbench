"""Renderer-independent GIS map-tool state machine contracts."""

from __future__ import annotations

from paleo_workbench.mapping.map_tools import (
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
