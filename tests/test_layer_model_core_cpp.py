"""Binding contract for the native authoritative layer registry."""

from __future__ import annotations

import gc

import pytest

layer_model_core = pytest.importorskip("layer_model_core")
LayerRegistry = layer_model_core.LayerRegistry
LayerType = layer_model_core.LayerType


def test_registry_binding_exposes_authoritative_order_and_groups():
    registry = LayerRegistry()
    group = registry.add_layer("factor", "孔隙度单因素图", LayerType.Group)
    surface = registry.add_layer(
        "surface", "孔隙度", LayerType.ScalarGrid, parent_id=group.id
    )
    contour = registry.add_layer(
        "contour", "等值线", LayerType.Contour, parent_id=group.id
    )

    assert registry.size == 3
    assert [layer.id for layer in registry.layers()] == ["factor", "surface", "contour"]
    assert [layer.id for layer in registry.children_of("factor")] == ["surface", "contour"]
    assert registry.parent_id(surface.id) == group.id
    assert registry.is_effectively_visible(surface.id, 1000.0)

    assert registry.move_above(surface.id, contour.id)
    assert [layer.id for layer in registry.layers()] == ["factor", "contour", "surface"]


def test_binding_mutations_keep_data_and_style_revisions_independent():
    registry = LayerRegistry()
    layer = registry.add_layer("grid", "初始", LayerType.ScalarGrid)

    data0, style0 = layer.data_revision, layer.style_revision
    layer.name = "重命名"
    layer.visible = False
    layer.opacity = 0.4
    assert layer.data_revision == data0
    assert layer.style_revision == style0 + 3

    data1, style1 = layer.data_revision, layer.style_revision
    layer.extent = (10.0, 20.0, 30.0, 40.0)
    layer.crs = "EPSG:3857"
    layer.source_ref = "artifact:porosity"
    assert layer.data_revision == data1 + 3
    assert layer.style_revision == style1
    assert layer.extent == (10.0, 20.0, 30.0, 40.0)

    layer.opacity = 0.4
    layer.extent = (10.0, 20.0, 30.0, 40.0)
    assert (layer.data_revision, layer.style_revision) == (data1 + 3, style1)


def test_binding_rejects_invalid_registry_operations_and_keeps_handles_safe():
    registry = LayerRegistry()
    layer = registry.add_layer("grid", "网格", LayerType.ScalarGrid)
    registry.add_layer("point", "点", LayerType.Point)

    with pytest.raises(ValueError, match="duplicate layer id"):
        registry.add_layer("grid", "重复", LayerType.ScalarGrid)
    with pytest.raises(ValueError, match="parent group does not exist"):
        registry.add_layer("child", "子项", LayerType.Point, parent_id="missing")
    with pytest.raises(ValueError, match="parent is not a group"):
        registry.add_layer("child", "子项", LayerType.Point, parent_id="point")

    assert registry.remove_layer(layer.id)
    assert registry.get(layer.id) is None
    del registry
    gc.collect()
    # The Python handle owns a shared reference, so inspection after removal is safe.
    assert layer.name == "网格"
