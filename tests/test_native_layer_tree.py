"""Offscreen Qt integration tests for the native-backed layer manager."""

from __future__ import annotations

import layer_model_core
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeView

from paleo_workbench.ui.native_layer_tree import NativeLayerModel, NativeLayerTree


def _registry():
    registry = layer_model_core.LayerRegistry()
    registry.add_layer("factor", "孔隙度单因素图", layer_model_core.LayerType.Group)
    registry.add_layer(
        "surface", "孔隙度", layer_model_core.LayerType.ScalarGrid, parent_id="factor"
    ).extent = (100.0, 200.0, 300.0, 400.0)
    registry.add_layer(
        "contour", "等值线", layer_model_core.LayerType.Contour, parent_id="factor"
    )
    return registry


def test_native_layer_model_reads_and_mutates_only_the_cpp_registry(qtbot):
    registry = _registry()
    model = NativeLayerModel(registry)
    assert model.rowCount() == 1
    group = model.index(0, 0)
    surface = model.index(0, 0, group)
    opacity = model.index(0, 1, group)

    assert model.data(group) == "孔隙度单因素图"
    assert model.data(surface, NativeLayerModel.LayerIdRole) == "surface"
    assert model.parent(surface) == group
    assert model.rowCount(group) == 2

    assert model.setData(surface, Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
    assert registry.get("surface").visible is False
    assert model.setData(surface, "孔隙度（重命名）")
    assert registry.get("surface").name == "孔隙度（重命名）"
    assert model.setData(opacity, 0.35)
    assert registry.get("surface").opacity == pytest.approx(0.35)
    assert not model.setData(opacity, "nan")


def test_native_layer_model_handles_order_removal_active_layer_and_zoom(qtbot):
    registry = _registry()
    model = NativeLayerModel(registry)
    assert model.move_layer("contour", 1)
    group = model.index(0, 0)
    assert [model.data(model.index(row, 0, group), NativeLayerModel.LayerIdRole) for row in range(2)] == [
        "contour",
        "surface",
    ]

    active = []
    zoom = []
    model.active_layer_changed.connect(active.append)
    model.zoom_to_layer_requested.connect(lambda layer_id, extent: zoom.append((layer_id, extent)))
    assert model.set_active_layer("surface")
    assert active == ["surface"]
    assert model.request_zoom_to_layer("surface")
    assert zoom == [("surface", (100.0, 200.0, 300.0, 400.0))]

    assert model.remove_layer("factor")
    assert model.active_layer_id == "surface"
    assert model.rowCount() == 2  # former children are safely orphaned roots
    assert not model.set_active_layer("missing")
    assert not model.request_zoom_to_layer("missing")


def test_native_layer_tree_wires_qtreeview_selection_and_zoom(qtbot):
    tree = NativeLayerTree(_registry())
    qtbot.addWidget(tree)
    tree.show()
    tree.expand_all()

    assert tree.objectName() == "NativeLayerTree"
    assert tree.tree.objectName() == "NativeLayerTreeView"
    assert isinstance(tree.tree, QTreeView)

    group = tree.model.index(0, 0)
    surface = tree.model.index(0, 0, group)
    tree.tree.setCurrentIndex(surface)
    assert tree.model.active_layer_id == "surface"

    with qtbot.waitSignal(tree.zoom_to_layer_requested, timeout=1000) as signal:
        tree.model.request_zoom_to_layer("surface")
    assert signal.args == ["surface", (100.0, 200.0, 300.0, 400.0)]


def test_native_layer_model_drag_drop_reparents_through_cpp_registry(qtbot):
    registry = _registry()
    registry.add_layer("second", "Second Group", layer_model_core.LayerType.Group)
    model = NativeLayerModel(registry)
    source_group = model.index(0, 0)
    surface = model.index(0, 0, source_group)
    target_group = model.index(1, 0)

    mime = model.mimeData([surface])
    assert model.dropMimeData(mime, Qt.DropAction.MoveAction, -1, 0, target_group)

    assert registry.parent_id("surface") == "second"
    assert model.parent(model._index_for_id("surface")) == target_group


def test_native_layer_panel_exposes_real_actions_for_layer_management(qtbot):
    tree = NativeLayerTree(_registry())
    qtbot.addWidget(tree)
    tree.show()
    before = tree.model.registry.size
    tree.add_group_action.trigger()

    assert tree.model.registry.size == before + 1
    group = tree.model.index(0, 0)
    tree.tree.setCurrentIndex(group)
    assert tree.zoom_action.isEnabled()
    assert tree.properties_action.isEnabled()
