"""M2 Task 4: QgisLayerTreePanel 作为 LayerManagerPanel 的 drop-in 替换。"""
import json

import pytest

pytest.importorskip("PySide6")

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
    qtbot.waitUntil(
        lambda: [l.id for l in panel._layers][:2] == ["doc-a", "doc-b"], timeout=2000)


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
