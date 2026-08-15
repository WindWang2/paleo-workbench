"""Offscreen Qt integration tests for the native-backed layer manager."""

from __future__ import annotations

import layer_model_core
import pytest
from PySide6.QtCore import QModelIndex, Qt
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
    # Children are displayed in REVERSE z-order (top row = topmost).
    surface = model.index(1, 0, group)
    opacity = model.index(1, 1, group)

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
    # Flat z-order after move: [factor, contour, surface]; display reverses it.
    assert [model.data(model.index(row, 0, group), NativeLayerModel.LayerIdRole) for row in range(2)] == [
        "surface",
        "contour",
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
    surface = tree.model.index(1, 0, group)
    tree.tree.setCurrentIndex(surface)
    assert tree.model.active_layer_id == "surface"

    with qtbot.waitSignal(tree.zoom_to_layer_requested, timeout=1000) as signal:
        tree.model.request_zoom_to_layer("surface")
    assert signal.args == ["surface", (100.0, 200.0, 300.0, 400.0)]


def test_native_layer_model_drag_drop_reparents_through_cpp_registry(qtbot):
    registry = _registry()
    registry.add_layer("second", "Second Group", layer_model_core.LayerType.Group)
    model = NativeLayerModel(registry)
    # _index_for_id resolves the display row regardless of order; flat order
    # is [factor, surface, contour, second], display is its reverse.
    source_group = model._index_for_id("factor")
    surface = model._index_for_id("surface")
    target_group = model._index_for_id("second")
    assert model.rowCount() == 2  # display roots: [second, factor]

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


# --- display convention: panel top = topmost layer (#422) --------------------

def _display_order(model, parent=None) -> list[str]:
    parent_index = parent if parent is not None else QModelIndex()
    count = model.rowCount(parent_index)
    return [
        model.data(model.index(r, 0, parent_index), NativeLayerModel.LayerIdRole)
        for r in range(count)
    ]


def test_native_layer_model_display_order_is_reversed_z_order(qtbot):
    """The panel's top row must show the layer drawn LAST (topmost), while
    the registry keeps z-order with index 0 = bottom, drawn first."""
    registry = layer_model_core.LayerRegistry()
    registry.add_layer("bottom", "bottom", layer_model_core.LayerType.ScalarGrid)
    registry.add_layer("top", "top", layer_model_core.LayerType.ScalarGrid)
    model = NativeLayerModel(registry)

    assert _display_order(model) == ["top", "bottom"]
    # Registry z-order untouched: index 0 = bottom.
    assert registry.index_of("bottom") == 0
    assert registry.index_of("top") == 1
    # Top display row maps to the highest registry index (drawn last).
    assert registry.index_of(model._children(None)[0].id) == registry.size - 1


def test_native_layer_tree_move_up_raises_z_order(qtbot):
    """'Move Up' must raise the selected layer's z-order (drawn later, higher
    on the panel); 'Move Down' lowers it. Display: [c, b, a] for flat
    z-order [a, b, c] (index 0 = bottom)."""
    registry = layer_model_core.LayerRegistry()
    for layer_id in ("a", "b", "c"):
        registry.add_layer(layer_id, layer_id, layer_model_core.LayerType.ScalarGrid)
    tree = NativeLayerTree(registry)
    qtbot.addWidget(tree)
    tree.show()
    assert _display_order(tree.model) == ["c", "b", "a"]

    # b (middle display row): Move Up enabled, raises z-order 1 -> 2.
    tree.tree.setCurrentIndex(tree.model._index_for_id("b"))
    assert tree.move_up_action.isEnabled()
    assert tree.move_down_action.isEnabled()
    tree.move_up_action.trigger()
    assert registry.index_of("b") == 2
    assert _display_order(tree.model) == ["b", "c", "a"]

    # b is now topmost: Move Up disabled, Move Down enabled.
    tree.tree.setCurrentIndex(tree.model._index_for_id("b"))
    assert not tree.move_up_action.isEnabled()
    assert tree.move_down_action.isEnabled()

    # c (middle display row): Move Down lowers z-order 1 -> 0.
    tree.tree.setCurrentIndex(tree.model._index_for_id("c"))
    tree.move_down_action.trigger()
    assert registry.index_of("c") == 0
    assert _display_order(tree.model) == ["b", "a", "c"]

    # c is now bottommost: Move Down disabled, Move Up enabled.
    tree.tree.setCurrentIndex(tree.model._index_for_id("c"))
    assert not tree.move_down_action.isEnabled()
    assert tree.move_up_action.isEnabled()


def test_native_layer_model_drop_target_matches_display_position(qtbot):
    """Dropping at a display row must land the layer at that display
    position (top display row = highest z), consistent with the convention."""
    registry = layer_model_core.LayerRegistry()
    for layer_id in ("a", "b", "c"):
        registry.add_layer(layer_id, layer_id, layer_model_core.LayerType.ScalarGrid)
    model = NativeLayerModel(registry)
    assert _display_order(model) == ["c", "b", "a"]
    assert [registry.index_of(l) for l in ("a", "b", "c")] == [0, 1, 2]

    # Drop "a" above the top display row (row 0): it becomes the top layer.
    mime = model.mimeData([model._index_for_id("a")])
    assert model.dropMimeData(mime, Qt.DropAction.MoveAction, 0, 0, QModelIndex())
    assert _display_order(model) == ["a", "c", "b"]
    assert registry.index_of("a") == 2

    # Drop "c" below the last display row: it becomes the bottom layer.
    mime = model.mimeData([model._index_for_id("c")])
    assert model.dropMimeData(mime, Qt.DropAction.MoveAction, 3, 0, QModelIndex())
    assert _display_order(model) == ["a", "b", "c"]
    assert registry.index_of("c") == 0
