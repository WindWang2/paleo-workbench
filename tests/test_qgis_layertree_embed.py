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
