"""M2 Task 1: QgsLayerTreeView 嵌入宿主，镜像图层出现在树中。"""
import pytest

pytest.importorskip("PySide6")
from shiboken6 import wrapInstance
from PySide6.QtWidgets import QWidget

_GEOJSON = """{
  "type": "FeatureCollection",
  "features": [
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [5.0, 5.0]},
     "properties": {"name": "A1"}}
  ]
}"""

_EMPTY_FC = '{"type": "FeatureCollection", "features": []}'

_POLYGON_FC = """{
  "type": "FeatureCollection",
  "features": [
    {"type": "Feature", "geometry": {"type": "Polygon", "coordinates":
      [[[0.0, 0.0], [100.0, 0.0], [100.0, 100.0], [0.0, 100.0], [0.0, 0.0]]]},
     "properties": {}}
  ]
}"""


@pytest.fixture()
def stack(qapp):
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize()
    yield s
    s.shutdown()


def test_layer_tree_view_embeds_and_lists_mirror_layers(qtbot, stack):
    canvas = stack.create_canvas()
    stack.set_canvas_extent(canvas, 0.0, 0.0, 10.0, 10.0)
    tree_addr = stack.create_layer_tree_view(canvas)
    assert tree_addr != 0
    tree = wrapInstance(tree_addr, QWidget)
    qtbot.addWidget(tree)
    tree.show()
    stack.add_vector_layer_geojson("井位", "Point", "EPSG:4326", _GEOJSON)
    qtbot.waitUntil(lambda: stack.tree_view_row_count(tree_addr) >= 1, timeout=2000)
    names = [stack.tree_view_layer_name(tree_addr, row) for row in range(stack.tree_view_row_count(tree_addr))]
    assert "井位" in names


def test_selection_callback_fires_with_doc_id(qtbot, stack):
    canvas = stack.create_canvas()
    tree_addr = stack.create_layer_tree_view(canvas)
    seen = []
    stack.set_tree_selection_callback(tree_addr, seen.append)
    stack.add_vector_layer_geojson("工区边界", "Polygon", "EPSG:4326", _GEOJSON)
    tree = wrapInstance(tree_addr, QWidget)
    qtbot.addWidget(tree)
    tree.show()
    qtbot.waitUntil(lambda: stack.tree_view_row_count(tree_addr) >= 1, timeout=2000)
    stack.tree_view_set_current_row(tree_addr, 0)
    qtbot.waitUntil(lambda: len(seen) >= 1, timeout=2000)
    assert seen[-1]  # 非空：doc id 或 QGIS layer id


def test_zoom_to_layer_empty_falls_back_to_full_extent(qtbot, stack):
    """M3 Task 6（M2 移交项）：空图层「缩放至图层」回退全图，不再无操作。"""
    canvas = stack.create_canvas()
    tree_addr = stack.create_layer_tree_view(canvas)
    tree = wrapInstance(tree_addr, QWidget)
    qtbot.addWidget(tree)
    tree.show()
    stack.upsert_mirror_layer("doc-full", "全图参照", "Polygon", "EPSG:4326", _POLYGON_FC)
    stack.upsert_mirror_layer("doc-empty", "空图层", "Point", "EPSG:4326", _EMPTY_FC)
    qtbot.waitUntil(lambda: stack.tree_view_row_count(tree_addr) >= 2, timeout=2000)
    # 先把画布收到小范围，再对空图层执行缩放至图层
    stack.set_canvas_extent(canvas, 0.0, 0.0, 1.0, 1.0)
    stack.zoom_to_layer(tree_addr, "doc-empty")
    xmin, ymin, xmax, ymax = stack.canvas_extent(canvas)
    assert xmax - xmin > 50.0  # 回退到全图（≈100 宽），而不是停留在 1.0


def test_edit_indicator_roundtrip(qtbot, stack):
    """M3 Task 6（M2 移交项）：✏ 编辑态图层指示器幂等挂/摘。"""
    canvas = stack.create_canvas()
    tree_addr = stack.create_layer_tree_view(canvas)
    tree = wrapInstance(tree_addr, QWidget)
    qtbot.addWidget(tree)
    tree.show()
    stack.upsert_mirror_layer("doc-edit", "编辑层", "Point", "EPSG:4326", _EMPTY_FC)
    qtbot.waitUntil(lambda: stack.tree_view_row_count(tree_addr) >= 1, timeout=2000)
    assert stack.edit_indicator_count(tree_addr, "doc-edit") == 0
    stack.set_edit_indicator(tree_addr, "doc-edit", True)
    qtbot.waitUntil(lambda: stack.edit_indicator_count(tree_addr, "doc-edit") == 1, timeout=2000)
    stack.set_edit_indicator(tree_addr, "doc-edit", True)  # 幂等：不重复挂
    assert stack.edit_indicator_count(tree_addr, "doc-edit") == 1
    stack.set_edit_indicator(tree_addr, "doc-edit", False)
    qtbot.waitUntil(lambda: stack.edit_indicator_count(tree_addr, "doc-edit") == 0, timeout=2000)
