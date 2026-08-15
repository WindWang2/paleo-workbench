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


def _flat_ids(registry):
    return [layer.id for layer in registry.layers()]


def _drop(model, source_row, drop_row, parent=QModelIndex(), target_parent=None):
    if target_parent is None:
        target_parent = parent
    mime = model.mimeData([model.index(source_row, 0, parent)])
    assert model.dropMimeData(
        mime, Qt.DropAction.MoveAction, drop_row, 0, target_parent
    )


@pytest.mark.parametrize("drop_row", range(5))
@pytest.mark.parametrize("source_row", range(4))
def test_drop_mime_data_inserts_at_drop_row_for_all_row_pairs(source_row, drop_row):
    """Every (source, target) sibling pair must land on the drop row (C23).

    move_layer removes the dragged layer before inserting; downward drops
    previously overshot by one row and the rendered z-order disagreed with
    the tree shown during the drag.
    """
    registry = layer_model_core.LayerRegistry()
    for layer_id in ("a", "b", "c", "d"):
        registry.add_layer(layer_id, layer_id.upper(), layer_model_core.LayerType.Vector)
    model = NativeLayerModel(registry)

    _drop(model, source_row, drop_row)

    expected = ["a", "b", "c", "d"]
    layer_id = expected.pop(source_row)
    target = drop_row - 1 if drop_row > source_row else drop_row
    expected.insert(target, layer_id)
    assert _flat_ids(registry) == expected


def test_drop_mime_data_downward_and_upward_within_a_group(qtbot):
    registry = layer_model_core.LayerRegistry()
    registry.add_layer("g", "G", layer_model_core.LayerType.Group)
    for layer_id in ("a", "b", "c", "d"):
        registry.add_layer(layer_id, layer_id.upper(), layer_model_core.LayerType.Vector, parent_id="g")
    model = NativeLayerModel(registry)
    parent = model.index(0, 0)

    _drop(model, 0, 2, parent)  # a below b, above c
    assert _flat_ids(registry) == ["g", "b", "a", "c", "d"]

    _drop(model, 3, 0, parent)  # d to the top of the group
    assert _flat_ids(registry) == ["g", "d", "b", "a", "c"]


def test_drop_mime_data_same_position_is_a_noop(qtbot):
    registry = layer_model_core.LayerRegistry()
    for layer_id in ("a", "b", "c", "d"):
        registry.add_layer(layer_id, layer_id.upper(), layer_model_core.LayerType.Vector)
    model = NativeLayerModel(registry)

    _drop(model, 1, 1)  # own row
    assert _flat_ids(registry) == ["a", "b", "c", "d"]

    _drop(model, 3, 4)  # below own last row
    assert _flat_ids(registry) == ["a", "b", "c", "d"]


def test_drop_mime_data_cross_group_compensates_flat_removal(qtbot):
    """Anchor and dragged layer are not siblings; the off-by-one still applies
    when the dragged layer precedes the anchor in flat z-order."""
    registry = layer_model_core.LayerRegistry()
    registry.add_layer("g", "G", layer_model_core.LayerType.Group)
    registry.add_layer("c", "C", layer_model_core.LayerType.Vector, parent_id="g")
    for layer_id in ("a", "b", "d"):
        registry.add_layer(layer_id, layer_id.upper(), layer_model_core.LayerType.Vector)
    model = NativeLayerModel(registry)
    # Flat z-order: [g, c, a, b, d]; root rows: g(0), a(1), b(2), d(3).
    group = model.index(0, 0)

    # Drag root "b" (flat 3) into the group above "c" (flat 1): "b" sits
    # AFTER the anchor, so no removal compensation applies.
    _drop(model, 2, 0, target_parent=group)
    assert _flat_ids(registry) == ["g", "b", "c", "a", "d"]
    assert registry.parent_id("b") == "g"

    # Root rows are now g(0), a(1), d(2). Drag group child "c" (flat 2) to
    # root row 2 (between "a", flat 3, and "d", flat 4): "c" PRECEDES the
    # anchor, so removal shifts the anchor left by one and the pre-removal
    # index would overshoot.
    _drop(model, 1, 2, parent=group, target_parent=QModelIndex())
    assert _flat_ids(registry) == ["g", "b", "a", "c", "d"]
    assert registry.parent_id("c") == ""
    assert [model.data(model.index(row, 0), NativeLayerModel.LayerIdRole) for row in range(3)] == [
        "g", "a", "c",
    ]
