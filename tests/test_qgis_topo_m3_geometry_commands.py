# -*- coding: utf-8 -*-
"""拓扑编辑迁移 M3：几何命令——真桥面（规格 §8 → §4 无缝分割/合并）。

场景 9（分割：两块继承源属性、追踪切线沿边吸附、邻层插点不分割、
一 Ctrl+Z 全撤）、
场景 10（合并：预填最大面积属性、冲突高亮由宿主对话框覆盖；桥侧
union + 归并属性、一 Ctrl+Z 全撤）。

像素映射：extent 0-10 on 400px → 40px/unit；(x, y) → (40x, 400-40y)。
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.qgis


_FIELDS = json.dumps([
    {"name": "facies", "type": "QString", "alias": "相分类"},
    {"name": "name", "type": "QString", "alias": "名称"},
])


def _square(feature_id, x0, y0, size=4.0, **props):
    properties = {"__pwb_fid": feature_id, **props}
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [[
            [x0, y0], [x0 + size, y0], [x0 + size, y0 + size],
            [x0, y0 + size], [x0, y0]]]},
        "properties": properties,
    }


def _collection(*features):
    return json.dumps({"type": "FeatureCollection", "features": list(features)})


def _line_geojson(coords):
    return json.dumps({"type": "LineString", "coordinates": coords})


@pytest.fixture()
def stack(qapp):
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize()
    yield s
    s.shutdown()


def _canvas(qtbot, stack):
    from shiboken6 import wrapInstance
    from PySide6.QtWidgets import QGraphicsView

    addr = stack.create_canvas()
    view = wrapInstance(addr, QGraphicsView)
    qtbot.addWidget(view)
    view.resize(400, 400)
    view.show()
    return addr, view


def _upsert(stack, doc_id, features, geometry="Polygon", crs="EPSG:4326"):
    stack.upsert_mirror_layer(
        doc_id, doc_id, geometry, crs, _collection(*features),
        "", "", "", True, 1.0, is_reference=False, is_editable=True,
        data_revision=1, fields_json=_FIELDS)


def _readback(stack, doc_id):
    payload = json.loads(stack.mirror_features_json(doc_id, 0))
    assert payload["exists"], doc_id
    return payload["features"]


def _by_id(features):
    return {str(f.get("id")): f for f in features}


def _ring(feature):
    return feature["geometry"]["coordinates"][0]


def _has_vertex(ring, x, y, tol=0.05):
    return any(abs(float(px) - x) <= tol and abs(float(py) - y) <= tol
               for px, py in ring)


def _vertex_count(ring):
    return len(ring) - 1


def _area(feature):
    import shapely.geometry as sg

    return sg.shape(feature["geometry"]).area


def _cleanup(stack, addr, *docs):
    """teardown 卫生：切回 pan + 回滚编辑层（M2 契约，M3 沿用）。"""
    stack.set_map_tool(addr, "pan")
    for doc in docs:
        if stack.mirror_layer_editing(doc):
            stack.roll_back_mirror_layer(doc)


def test_scenario9_split_inherits_source_attributes_and_undo(qtbot, stack):
    """场景 9：选中面画切线 → 两块均继承源属性；一 undo 全撤。"""
    addr, _view = _canvas(qtbot, stack)
    _upsert(stack, "draft", [
        _square("src", 4.0, 4.0, size=4.0, facies="砂岩", name="源"),
    ])
    stack.set_canvas_extent(addr, 0.0, 0.0, 10.0, 10.0)
    assert stack.start_mirror_layer_editing("draft") == ""
    stack.set_current_layer(addr, "draft")
    stack.set_snapping_config(addr, json.dumps({
        "enabled": False, "topological_editing": True,
    }))

    events = []
    stack.set_edit_pick_callback(
        addr, lambda action, payload: events.append(
            (action, json.loads(payload))))

    # 竖切 x=5：左 1×4、右 3×4，右侧更大 → 源 fid 留给大块。
    error = stack.split_mirror_features(
        "draft", _line_geojson([[5.0, 3.0], [5.0, 9.0]]),
        json.dumps(["src"]))
    assert error == "", error

    gesture = [p for a, p in events if a == "edit_gesture"]
    assert gesture, events
    assert "draft" in gesture[-1]["layers"]
    assert gesture[-1]["undo_text"] == "Features split"

    pieces = _readback(stack, "draft")
    assert len(pieces) == 2, pieces
    for piece in pieces:
        assert piece["properties"].get("facies") == "砂岩", piece
        assert piece["properties"].get("name") == "源", piece
    by_id = _by_id(pieces)
    assert "src" in by_id, "最大块继承源 fid（桌面 split policy）"
    assert _area(by_id["src"]) > 1.5  # 大块约 12，小块约 4

    assert stack.undo_mirror_edit("draft") == ""
    restored = _readback(stack, "draft")
    assert len(restored) == 1
    assert restored[0]["id"] == "src"
    assert restored[0]["properties"].get("facies") == "砂岩"
    _cleanup(stack, addr, "draft")


def test_scenario9_neighbor_gets_topo_points_not_split(qtbot, stack):
    """场景 9：邻层同位置被插拓扑点但不分割。"""
    addr, _view = _canvas(qtbot, stack)
    # 草稿 (4,4)-(8,8)；邻层 (8,4)-(12,8) 共享 x=8 边。
    _upsert(stack, "draft", [
        _square("src", 4.0, 4.0, size=4.0, facies="砂岩"),
    ])
    _upsert(stack, "neighbor", [
        _square("n1", 8.0, 4.0, size=4.0, facies="泥岩"),
    ])
    stack.set_canvas_extent(addr, 0.0, 0.0, 14.0, 10.0)
    assert stack.start_mirror_layer_editing("draft") == ""
    assert stack.start_mirror_layer_editing("neighbor") == ""
    stack.set_current_layer(addr, "draft")
    stack.set_snapping_config(addr, json.dumps({
        "enabled": False, "topological_editing": True,
    }))

    events = []
    stack.set_edit_pick_callback(
        addr, lambda action, payload: events.append(
            (action, json.loads(payload))))

    # 横切 y=6：穿过草稿并跨过共享边落到邻层内部——邻层只插点。
    error = stack.split_mirror_features(
        "draft", _line_geojson([[3.0, 6.0], [10.0, 6.0]]),
        json.dumps(["src"]))
    assert error == "", error

    draft_pieces = _readback(stack, "draft")
    assert len(draft_pieces) == 2
    neighbor = _readback(stack, "neighbor")
    assert len(neighbor) == 1, "邻层不分割"
    assert neighbor[0]["id"] == "n1"
    assert neighbor[0]["properties"].get("facies") == "泥岩"
    ring = _ring(neighbor[0])
    assert _has_vertex(ring, 8.0, 6.0), f"邻层共享边应插入拓扑点: {ring}"
    assert _vertex_count(ring) > 4

    gesture = [p for a, p in events if a == "edit_gesture"][-1]
    assert sorted(gesture["layers"]) == ["draft", "neighbor"], gesture

    # 逆序逐层 undo（手势管理器计划的桥侧等价）。
    for doc in reversed(gesture["layers"]):
        assert stack.undo_mirror_edit(doc) == ""
    assert len(_readback(stack, "draft")) == 1
    neighbor_restored = _readback(stack, "neighbor")
    assert len(neighbor_restored) == 1
    assert _vertex_count(_ring(neighbor_restored[0])) == 4
    _cleanup(stack, addr, "draft", "neighbor")


def test_scenario9_traced_cut_line_follows_edge(qtbot, stack):
    """场景 9：追踪开时切线沿现有弯边吸附（捕获工具免费获得）。"""
    addr, view = _canvas(qtbot, stack)
    bent = {
        "type": "Feature",
        "geometry": {"type": "LineString",
                     "coordinates": [[2.0, 5.0], [5.0, 6.0], [8.0, 5.0]]},
        "properties": {"__pwb_fid": "guide", "name": "引导"},
    }
    stack.upsert_mirror_layer(
        "guide", "引导线", "LineString", "EPSG:4326",
        _collection(bent), "", "", "", True, 1.0,
        is_reference=False, is_editable=True, data_revision=1)
    _upsert(stack, "draft", [
        _square("src", 2.0, 2.0, size=6.0, facies="砂岩"),
    ])
    stack.set_canvas_extent(addr, 0.0, 0.0, 10.0, 10.0)
    assert stack.start_mirror_layer_editing("draft") == ""
    stack.set_current_layer(addr, "draft")

    captured = []
    stack.set_digitize_callback(
        addr, lambda status, geom: captured.append((status, geom)))
    stack.set_tracing_enabled(addr, True)
    stack.set_snapping_config(addr, json.dumps({
        "enabled": True, "mode": "all_layers", "tolerance_px": 20.0,
        "types": ["vertex", "segment"], "topological_editing": True,
    }))
    stack.set_map_tool(addr, "addLine")

    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    pixel = lambda x, y: QPoint(int(40 * x), int(400 - 40 * y))
    QTest.mouseMove(view.viewport(), pixel(2.0, 5.0))
    QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier,
                     pixel(2.0, 5.0))
    QTest.mouseMove(view.viewport(), pixel(8.0, 5.0))
    QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier,
                     pixel(8.0, 5.0))
    QTest.mouseClick(view.viewport(), Qt.RightButton, Qt.NoModifier,
                     pixel(8.0, 5.0))
    qtbot.waitUntil(lambda: any(s == "completed" for s, _ in captured),
                    timeout=3000)
    geometry = json.loads([g for s, g in captured if s == "completed"][-1])
    coords = geometry["coordinates"]
    assert _has_vertex(coords, 2.0, 5.0) and _has_vertex(coords, 8.0, 5.0)
    assert _has_vertex(coords, 5.0, 6.0), (
        f"追踪切线未沿弯边（coords={coords}）")

    error = stack.split_mirror_features(
        "draft", json.dumps(geometry), json.dumps(["src"]))
    assert error == "", error
    pieces = _readback(stack, "draft")
    assert len(pieces) == 2
    for piece in pieces:
        assert piece["properties"].get("facies") == "砂岩"
    _cleanup(stack, addr, "draft")
    stack.set_tracing_enabled(addr, False)


def test_scenario9_empty_split_leaves_no_edit_command(qtbot, stack):
    """规格 §4：splitFeatures 空结果 → destroyEditCommand 不留痕。"""
    addr, _view = _canvas(qtbot, stack)
    _upsert(stack, "draft", [
        _square("src", 4.0, 4.0, size=2.0, facies="砂岩"),
    ])
    stack.set_canvas_extent(addr, 0.0, 0.0, 10.0, 10.0)
    assert stack.start_mirror_layer_editing("draft") == ""
    # 切线完全在面外：不应分割、不应留下可撤销宏。
    error = stack.split_mirror_features(
        "draft", _line_geojson([[0.0, 0.0], [1.0, 0.0]]),
        json.dumps(["src"]))
    assert error, "空分割应返回原因"
    assert len(_readback(stack, "draft")) == 1
    stack.undo_mirror_edit("draft")
    restored = _readback(stack, "draft")
    assert len(restored) == 1
    assert restored[0]["id"] == "src"
    _cleanup(stack, addr, "draft")


def test_scenario10_merge_union_attributes_and_undo(qtbot, stack):
    """场景 10：确认后 union + 归并属性落层；一 undo 全撤。"""
    addr, _view = _canvas(qtbot, stack)
    _upsert(stack, "draft", [
        _square("big", 4.0, 4.0, size=4.0, facies="砂岩", name="大"),
        _square("small", 8.0, 4.0, size=2.0, facies="泥岩", name="小"),
    ])
    stack.set_canvas_extent(addr, 0.0, 0.0, 12.0, 10.0)
    assert stack.start_mirror_layer_editing("draft") == ""
    stack.set_current_layer(addr, "draft")

    events = []
    stack.set_edit_pick_callback(
        addr, lambda action, payload: events.append(
            (action, json.loads(payload))))

    error = stack.merge_mirror_features(
        "draft",
        json.dumps(["big", "small"]),
        json.dumps({
            "target_id": "big",
            "attributes": {"facies": "砂岩", "name": "大"},
        }))
    assert error == "", error

    gesture = [p for a, p in events if a == "edit_gesture"]
    assert gesture, events
    assert gesture[-1]["layers"] == ["draft"]
    assert gesture[-1]["undo_text"] == "Merged features"

    remaining = _readback(stack, "draft")
    assert len(remaining) == 1
    merged = remaining[0]
    assert merged["id"] == "big"
    assert merged["properties"].get("facies") == "砂岩"
    assert merged["properties"].get("name") == "大"
    import shapely.geometry as sg
    assert sg.shape(merged["geometry"]).area == pytest.approx(20.0, rel=1e-6)

    assert stack.undo_mirror_edit("draft") == ""
    restored = _by_id(_readback(stack, "draft"))
    assert set(restored) == {"big", "small"}
    assert restored["small"]["properties"].get("facies") == "泥岩"
    _cleanup(stack, addr, "draft")


def test_scenario10_merge_defaults_to_largest_when_target_omitted(qtbot, stack):
    """场景 10：对话框预填面积最大要素——桥在缺省 target 时选最大块。"""
    addr, _view = _canvas(qtbot, stack)
    _upsert(stack, "draft", [
        _square("big", 4.0, 4.0, size=4.0, facies="砂岩"),
        _square("small", 8.0, 4.0, size=2.0, facies="泥岩"),
    ])
    stack.set_canvas_extent(addr, 0.0, 0.0, 12.0, 10.0)
    assert stack.start_mirror_layer_editing("draft") == ""

    error = stack.merge_mirror_features(
        "draft", json.dumps(["big", "small"]), json.dumps({}))
    assert error == "", error
    remaining = _readback(stack, "draft")
    assert len(remaining) == 1
    assert remaining[0]["id"] == "big"
    assert remaining[0]["properties"].get("facies") == "砂岩"
    _cleanup(stack, addr, "draft")
