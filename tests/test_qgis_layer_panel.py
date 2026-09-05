"""M2 Task 4: QgisLayerTreePanel 作为 LayerManagerPanel 的 drop-in 替换。"""
import json

import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.qgis

_FC = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1.0, 1.0]}, "properties": {}}]}


def _layer(layer_id, name, visible=True):
    from paleo_workbench.mapping.map_render_backend import MapLayerSnapshot
    return MapLayerSnapshot(
        id=layer_id, name=name, layer_type="vector",
        extent=(0.0, 0.0, 10.0, 10.0), crs="EPSG:4326",
        data_revision=1, style_revision=1,
        features=(dict(_FC["features"][0]),), style={},
        visible=visible, opacity=1.0,
    )


def test_panel_bind_mirrors_layers_and_emits_active(qtbot, qapp):
    from paleo_workbench.ui.qgis_stack.canvas_shim import QgisCanvasShim
    from paleo_workbench.ui.qgis_stack.layer_tree_panel import QgisLayerTreePanel

    canvas = QgisCanvasShim()
    qtbot.addWidget(canvas)
    panel = QgisLayerTreePanel()
    qtbot.addWidget(panel)
    active = []
    panel.active_layer_changed.connect(active.append)
    panel.bind(canvas, [_layer("doc-a", "井位"), _layer("doc-b", "边界")])
    canvas.show()
    panel.show()
    qtbot.waitUntil(lambda: panel.tree_row_count() >= 2, timeout=3000)
    panel.select_layer("doc-b")
    qtbot.waitUntil(lambda: active and active[-1] == "doc-b", timeout=2000)


def test_tree_visibility_writes_back_to_panel_layers(qtbot, qapp):
    from paleo_workbench.ui.qgis_stack.canvas_shim import QgisCanvasShim
    from paleo_workbench.ui.qgis_stack.layer_tree_panel import QgisLayerTreePanel

    canvas = QgisCanvasShim()
    qtbot.addWidget(canvas)
    panel = QgisLayerTreePanel()
    qtbot.addWidget(panel)
    panel.bind(canvas, [_layer("doc-a", "井位")])
    canvas.show()
    panel.show()
    qtbot.waitUntil(lambda: panel.tree_row_count() >= 1, timeout=3000)
    canvas.stack.tree_view_set_row_checked(panel.tree_host.tree_view_address, 0, False)
    qtbot.waitUntil(lambda: panel.layer_by_id("doc-a").visible is False, timeout=2000)


def test_tree_rename_writes_back_to_panel_layers(qtbot, qapp):
    from paleo_workbench.ui.qgis_stack.canvas_shim import QgisCanvasShim
    from paleo_workbench.ui.qgis_stack.layer_tree_panel import QgisLayerTreePanel

    canvas = QgisCanvasShim()
    qtbot.addWidget(canvas)
    panel = QgisLayerTreePanel()
    qtbot.addWidget(panel)
    panel.bind(canvas, [_layer("doc-a", "井位")])
    canvas.show()
    panel.show()
    qtbot.waitUntil(lambda: panel.tree_row_count() >= 1, timeout=3000)
    canvas.stack.tree_view_rename_row(panel.tree_host.tree_view_address, 0, "井位2")
    qtbot.waitUntil(lambda: panel.layer_by_id("doc-a").name == "井位2", timeout=2000)


def test_tree_reorder_writes_back_to_panel_layers(qtbot, qapp):
    from paleo_workbench.ui.qgis_stack.canvas_shim import QgisCanvasShim
    from paleo_workbench.ui.qgis_stack.layer_tree_panel import QgisLayerTreePanel

    canvas = QgisCanvasShim()
    qtbot.addWidget(canvas)
    panel = QgisLayerTreePanel()
    qtbot.addWidget(panel)
    panel.bind(canvas, [_layer("doc-a", "井位"), _layer("doc-b", "边界")])
    canvas.show()
    panel.show()
    qtbot.waitUntil(lambda: panel.tree_row_count() >= 2, timeout=3000)
    canvas.stack.tree_view_move_row(panel.tree_host.tree_view_address, 0, 1)
    # flush 经 singleShot(0) 合并，先等一拍再断言，避免匹配到移动前状态
    # （M2 终局审查 I3：期望值是移动后的 ["doc-b","doc-a"]）。
    qtbot.wait(50)
    qtbot.waitUntil(
        lambda: [l.id for l in panel._layers][:2] == ["doc-b", "doc-a"], timeout=2000)


def test_panel_menu_callback_maps_to_request_signals(qtbot, qapp):
    from paleo_workbench.ui.qgis_stack.canvas_shim import QgisCanvasShim
    from paleo_workbench.ui.qgis_stack.layer_tree_panel import QgisLayerTreePanel

    canvas = QgisCanvasShim()
    qtbot.addWidget(canvas)
    panel = QgisLayerTreePanel()
    qtbot.addWidget(panel)
    panel.bind(canvas, [_layer("doc-a", "井位")])
    seen = []
    panel.properties_requested.connect(seen.append)
    panel._on_tree_menu("properties", "doc-a")
    assert seen == ["doc-a"]
    created = []
    panel.create_layer_requested.connect(lambda: created.append(True))
    panel._on_tree_menu("create_layer", "")
    assert created == [True]


def test_panel_set_layer_visible_reaches_mirror_without_echo(qtbot, qapp):
    from paleo_workbench.ui.qgis_stack.canvas_shim import QgisCanvasShim
    from paleo_workbench.ui.qgis_stack.layer_tree_panel import QgisLayerTreePanel

    canvas = QgisCanvasShim()
    qtbot.addWidget(canvas)
    panel = QgisLayerTreePanel()
    qtbot.addWidget(panel)
    panel.bind(canvas, [_layer("doc-a", "井位")])
    canvas.show()
    panel.show()
    qtbot.waitUntil(lambda: panel.tree_row_count() >= 1, timeout=3000)
    panel.set_layer_visible("doc-a", False)
    assert panel.layer_by_id("doc-a").visible is False
    assert canvas.stack.mirror_layer_visibility("doc-a") is False


def test_programmatic_publish_does_not_echo_active_layer(qtbot, qapp):
    """程序化发布（重排）不得外发 active_layer_changed（#1154 回归）。

    原生树重排的结构信号会让视图选中瞬跳（如回到第 0 行）；该噪声若外发，
    编辑控制器会被误切活动图层、数字化工具回落 pan（综合编修 resync 丢点）。
    """
    from paleo_workbench.ui.qgis_stack.canvas_shim import QgisCanvasShim
    from paleo_workbench.ui.qgis_stack.layer_tree_panel import QgisLayerTreePanel

    canvas = QgisCanvasShim()
    qtbot.addWidget(canvas)
    panel = QgisLayerTreePanel()
    qtbot.addWidget(panel)
    panel.bind(canvas, [_layer("doc-a", "井位"), _layer("doc-b", "边界")])
    canvas.show()
    panel.show()
    qtbot.waitUntil(lambda: panel.tree_row_count() >= 2, timeout=3000)
    panel.select_layer("doc-b")
    qtbot.waitUntil(lambda: panel._selected_doc_id == "doc-b", timeout=2000)
    active = []
    panel.active_layer_changed.connect(active.append)
    panel._publish()
    qtbot.wait(150)
    assert active == []


def test_empty_layer_appears_in_tree(qtbot, qapp):
    """零要素图层也上树——否则新建图层在首次数字化前不可见（M2 终局审查 I1）。"""
    from paleo_workbench.mapping.map_render_backend import MapLayerSnapshot
    from paleo_workbench.ui.qgis_stack.canvas_shim import QgisCanvasShim
    from paleo_workbench.ui.qgis_stack.layer_tree_panel import QgisLayerTreePanel

    empty = MapLayerSnapshot(
        id="doc-empty", name="新图层", layer_type="vector",
        extent=(0.0, 0.0, 10.0, 10.0), crs="EPSG:4326",
        data_revision=1, style_revision=1,
        features=(), style={},
        visible=True, opacity=1.0,
        metadata={"editable": "true", "geometry_kind": "point"},
    )
    canvas = QgisCanvasShim()
    qtbot.addWidget(canvas)
    panel = QgisLayerTreePanel()
    qtbot.addWidget(panel)
    panel.bind(canvas, [_layer("doc-a", "井位"), empty])
    canvas.show()
    panel.show()
    qtbot.waitUntil(lambda: panel.tree_row_count() >= 2, timeout=3000)
    panel.select_layer("doc-empty")
