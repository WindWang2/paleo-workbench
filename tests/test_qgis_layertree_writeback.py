"""M2 Task 3: 树的用户操作（勾选/拖拽/重命名）经回调到达 Python；程序化 reconcile 不触发。"""
import json

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt

_FC = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1.0, 1.0]}, "properties": {}}]}


@pytest.fixture()
def stack(qapp):
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize()
    yield s
    s.shutdown()


def _mirror(stack, doc, name):
    return stack.upsert_mirror_layer(doc, name, "Point", "EPSG:4326",
                                     json.dumps(_FC), "", "", "", True, 1.0)


def test_tree_visibility_toggle_reports_doc_id(qtbot, stack):
    canvas = stack.create_canvas()
    tree_addr = stack.create_layer_tree_view(canvas)
    events = []
    stack.set_tree_change_callback(tree_addr, events.append)
    _mirror(stack, "doc-a", "井位")
    qtbot.waitUntil(lambda: stack.tree_view_row_count(tree_addr) >= 1, timeout=2000)
    stack.tree_view_set_row_checked(tree_addr, 0, False)
    qtbot.waitUntil(lambda: any(json.loads(e).get("visibility") for e in events), timeout=2000)
    payload = json.loads([e for e in events if json.loads(e).get("visibility")][-1])
    assert payload["visibility"] == {"doc-a": False}


def test_programmatic_reconcile_does_not_echo(qtbot, stack):
    canvas = stack.create_canvas()
    tree_addr = stack.create_layer_tree_view(canvas)
    events = []
    stack.set_tree_change_callback(tree_addr, events.append)
    _mirror(stack, "doc-a", "井位")
    _mirror(stack, "doc-b", "边界")
    qtbot.waitUntil(lambda: stack.tree_view_row_count(tree_addr) >= 2, timeout=2000)
    qtbot.wait(200)
    events.clear()
    # 程序化：改可见性 + 重排序——不得触发回调
    stack.set_mirror_layer_visibility("doc-a", False)
    stack.set_mirror_layer_order(["doc-b", "doc-a"])
    qtbot.wait(200)
    assert events == []


def test_tree_reorder_reports_order(qtbot, stack):
    canvas = stack.create_canvas()
    tree_addr = stack.create_layer_tree_view(canvas)
    events = []
    stack.set_tree_change_callback(tree_addr, events.append)
    _mirror(stack, "doc-a", "井位")
    _mirror(stack, "doc-b", "边界")
    qtbot.waitUntil(lambda: stack.tree_view_row_count(tree_addr) >= 2, timeout=2000)
    qtbot.wait(200)
    events.clear()
    stack.tree_view_move_row(tree_addr, 0, 1)
    qtbot.waitUntil(lambda: any(json.loads(e).get("order") for e in events), timeout=2000)
    payload = json.loads([e for e in events if json.loads(e).get("order")][-1])
    # 初始顶层顺序 [doc-b, doc-a]（新图层置顶）；行 0 (doc-b) 移到行 1
    assert tuple(payload["order"]) == ("doc-a", "doc-b")


def test_rename_reports(qtbot, stack):
    canvas = stack.create_canvas()
    tree_addr = stack.create_layer_tree_view(canvas)
    events = []
    stack.set_tree_change_callback(tree_addr, events.append)
    _mirror(stack, "doc-a", "井位")
    qtbot.waitUntil(lambda: stack.tree_view_row_count(tree_addr) >= 1, timeout=2000)
    stack.tree_view_rename_row(tree_addr, 0, "井位2")
    qtbot.waitUntil(lambda: any(json.loads(e).get("renames") for e in events), timeout=2000)
    payload = json.loads([e for e in events if json.loads(e).get("renames")][-1])
    assert payload["renames"] == {"doc-a": "井位2"}


def test_parse_tree_change_merges_payload():
    from paleo_workbench.ui.qgis_stack.tree_sync import parse_tree_change

    cs = parse_tree_change(json.dumps({
        "visibility": {"doc-a": False},
        "order": ["doc-b", "doc-a"],
        "renames": {"doc-a": "井位2"},
    }))
    assert cs.visibility == {"doc-a": False}
    assert cs.order == ("doc-b", "doc-a")
    assert cs.renames == {"doc-a": "井位2"}
    assert not cs.empty
    assert parse_tree_change("").empty
    assert parse_tree_change("{}").empty
