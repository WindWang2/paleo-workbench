"""Unit and integration tests for Mapping Engine 2.0 architecture."""

from __future__ import annotations

import numpy as np
import pytest

from paleo_workbench.mapping.color_ramps import (
    ColorRamp,
    ColorStop,
    get_color_ramp,
    list_color_ramps,
)
from paleo_workbench.mapping.composer.models import (
    ComposerElement,
    ElementType,
    MapCompositionDocument,
)
from paleo_workbench.mapping.composer.renderer import MapComposerRenderer
from paleo_workbench.mapping.layers import (
    AnnotationMapLayer,
    ContourMapLayer,
    GridMapLayer,
    LayerType,
    MapDocument,
    MapLayer,
    PolygonMapLayer,
    RasterMapLayer,
    VectorMapLayer,
    WellPointMapLayer,
)
from paleo_workbench.mapping.map_styles import (
    MarkerSymbol,
    TextStyle,
    VectorStyle,
)
from paleo_workbench.mapping.renderers import (
    DEFAULT_RENDERER_REGISTRY,
    AnnotationRenderer,
    CategorizedRenderer,
    ContourRenderer,
    GraduatedRenderer,
    GridRenderer,
    LegendItem,
    RenderContext,
    SingleSymbolRenderer,
    WellSymbolRenderer,
)
from paleo_workbench.workflow.factor_grid_result import FactorGridResult


def test_color_ramps_evaluation():
    ramp = get_color_ramp("porosity")
    assert ramp.name == "porosity"
    c0 = ramp.evaluate(0.0)
    c1 = ramp.evaluate(1.0)
    cmid = ramp.evaluate(0.5)
    assert c0.startswith("#")
    assert c1.startswith("#")
    assert cmid.startswith("#")
    assert c0 != c1

    # Nodata
    assert ramp.evaluate(float("nan")) == ramp.nodata_color

    # Table sampling
    table = ramp.sample_table(64)
    assert len(table) == 64
    assert len(table[0]) == 4


def test_vector_map_layer_extent_and_snapshot():
    features = (
        {
            "id": "f1",
            "geometry": {"type": "Point", "coordinates": [10.0, 20.0]},
            "properties": {"name": "Well A"},
        },
        {
            "id": "f2",
            "geometry": {"type": "Point", "coordinates": [30.0, 40.0]},
            "properties": {"name": "Well B"},
        },
    )
    layer = VectorMapLayer(
        id="v1",
        name="Test Wells",
        features=features,
        crs="EPSG:4326",
    )
    assert layer.extent[0] <= 10.0
    assert layer.extent[2] >= 30.0
    assert layer.extent[1] <= 20.0
    assert layer.extent[3] >= 40.0

    snapshot = layer.to_snapshot()
    assert snapshot.id == "v1"
    assert snapshot.layer_type == "vector"
    assert len(snapshot.features) == 2


def test_grid_map_layer_rasterize_and_snapshot():
    gx = np.linspace(100.0, 110.0, 10)
    gy = np.linspace(30.0, 40.0, 10)
    gz = np.ones((10, 10), dtype=np.float32) * 15.5
    gz[0, 0] = np.nan

    grid_res = FactorGridResult(
        grid_z=gz,
        grid_x=gx,
        grid_y=gy,
        factor_name="孔隙度",
        algorithm_id="kriging",
        crs="EPSG:4326",
        unit="%",
    )

    layer = GridMapLayer(
        id="g1",
        name="孔隙度栅格",
        grid_result=grid_res,
        color_ramp_name="porosity",
    )
    assert layer.extent == grid_res.extent
    assert layer.crs == "EPSG:4326"

    rgba = layer.rasterize_rgba()
    assert rgba.shape == (10, 10, 4)
    assert rgba.dtype == np.uint8
    # Top-left cell was NaN => alpha = 0
    assert rgba[0, 0, 3] == 0
    # Other cells => alpha = 255
    assert rgba[5, 5, 3] == 255

    snapshot = layer.to_snapshot()
    assert snapshot.layer_type == "scalar_grid"
    assert snapshot.renderer_payload is not None
    assert hasattr(snapshot.renderer_payload, "rasterize")


def test_map_document_layer_management():
    doc = MapDocument(id="doc1", title="盆地综合图", crs="EPSG:4326")
    l1 = VectorMapLayer(id="l1", name="界线", extent=(10.0, 10.0, 20.0, 20.0))
    l2 = VectorMapLayer(id="l2", name="断层", extent=(5.0, 5.0, 25.0, 25.0))

    doc.add_layer(l1)
    doc.add_layer(l2)
    assert len(doc.layers) == 2
    assert doc.extent == (5.0, 5.0, 25.0, 25.0)

    # Reorder
    doc.reorder_layers(["l2", "l1"])
    assert doc.layers[0].id == "l2"
    assert doc.layers[1].id == "l1"

    # Remove
    removed = doc.remove_layer("l1")
    assert removed is not None
    assert len(doc.layers) == 1
    assert doc.get_layer("l1") is None
    assert doc.get_layer("l2") is not None


def test_renderer_registry_resolution():
    registry = DEFAULT_RENDERER_REGISTRY
    v_layer = VectorMapLayer(id="v", name="Vector")
    g_layer = GridMapLayer(id="g", name="Grid")
    c_layer = ContourMapLayer(id="c", name="Contour")
    w_layer = WellPointMapLayer(id="w", name="Wells")
    p_layer = PolygonMapLayer(id="p", name="Facies", style={"renderer": "categorized"})
    grad_layer = VectorMapLayer(id="grad", name="Graduated", style={"renderer": "graduated", "ranges": [(0.0, 10.0, "#ff0000")]})
    ann_layer = AnnotationMapLayer(id="ann", name="Annotations")

    r_v = registry.resolve(v_layer)
    r_g = registry.resolve(g_layer)
    r_c = registry.resolve(c_layer)
    r_w = registry.resolve(w_layer)
    r_p = registry.resolve(p_layer)
    r_grad = registry.resolve(grad_layer)
    r_ann = registry.resolve(ann_layer)

    assert isinstance(r_v, SingleSymbolRenderer)
    assert isinstance(r_g, GridRenderer)
    assert isinstance(r_c, ContourRenderer)
    assert isinstance(r_w, WellSymbolRenderer)
    assert isinstance(r_p, CategorizedRenderer)
    assert isinstance(r_grad, GraduatedRenderer)
    assert isinstance(r_ann, AnnotationRenderer)


def test_graduated_renderer_and_svg_export():
    ranges = (
        (0.0, 10.0, "#e0f2fe", "0 - 10 m"),
        (10.0, 20.0, "#38bdf8", "10 - 20 m"),
        (20.0, 30.0, "#0369a1", "20 - 30 m"),
    )
    style = VectorStyle(
        renderer="graduated",
        field="thickness",
        ranges=ranges,
        stroke="#0f172a",
        stroke_width=1.5,
    )
    features = (
        {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]]],
            },
            "properties": {"thickness": 5.0, "name": "Zone Low"},
        },
        {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[10.0, 0.0], [20.0, 0.0], [20.0, 10.0], [10.0, 10.0], [10.0, 0.0]]],
            },
            "properties": {"thickness": 15.0, "name": "Zone Med"},
        },
        {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[20.0, 0.0], [30.0, 0.0], [30.0, 10.0], [20.0, 10.0], [20.0, 0.0]]],
            },
            "properties": {"thickness": 25.0, "name": "Zone High"},
        },
    )
    layer = VectorMapLayer(
        id="poly_grad",
        name="砂层厚度分级",
        features=features,
        style=style.to_dict(),
        extent=(0.0, 0.0, 30.0, 10.0),
    )

    renderer = GraduatedRenderer()
    items = renderer.legend_items(layer)
    assert len(items) == 3
    assert items[0].label == "0 - 10 m"
    assert items[0].color == "#e0f2fe"
    assert items[1].label == "10 - 20 m"
    assert items[1].color == "#38bdf8"
    assert items[2].label == "20 - 30 m"
    assert items[2].color == "#0369a1"

    ctx = RenderContext(extent=(0.0, 0.0, 30.0, 10.0), width=300.0, height=100.0)
    svg = renderer.render_svg(layer, ctx)
    assert f'fill="#e0f2fe"' in svg
    assert f'fill="#38bdf8"' in svg
    assert f'fill="#0369a1"' in svg
    assert f'stroke="#0f172a"' in svg


def test_annotation_map_layer_and_renderer():
    layer = AnnotationMapLayer(
        id="ann_test",
        name="构造注记",
        crs="EPSG:4326",
    )
    assert layer.layer_type == "annotation"

    # Add text annotations
    ann1 = layer.add_annotation(
        text="中央背斜带",
        x=105.5,
        y=31.2,
        font_size=12.0,
        color="#f59e0b",
        rotation=15.0,
    )
    ann2 = layer.add_annotation(
        text="洼陷生烃中心",
        x=106.8,
        y=32.0,
        font_size=10.0,
        color="#10b981",
        rotation=0.0,
    )

    assert len(layer.annotations) == 2
    assert len(layer.features) == 2
    assert layer.extent[0] <= 105.5
    assert layer.extent[2] >= 106.8
    assert layer.extent[1] <= 31.2
    assert layer.extent[3] >= 32.0

    # Snapshot serialization & reconstruction
    snapshot = layer.to_snapshot()
    assert snapshot.id == "ann_test"
    assert snapshot.layer_type == "annotation"
    assert len(snapshot.features) == 2

    doc = MapDocument(id="doc_ann", title="注记图", crs="EPSG:4326")
    doc.add_layer(layer)
    doc_snap = doc.to_snapshot()

    restored_doc = MapDocument.from_snapshot(doc_snap)
    restored_layer = restored_doc.get_layer("ann_test")
    assert restored_layer is not None
    assert isinstance(restored_layer, AnnotationMapLayer)
    assert restored_layer.layer_type == "annotation"

    # Render to SVG
    renderer = AnnotationRenderer()
    ctx = RenderContext(extent=layer.extent, width=400.0, height=300.0)
    svg = renderer.render_svg(layer, ctx)

    assert "<text" in svg
    assert "中央背斜带" in svg
    assert "洼陷生烃中心" in svg
    assert 'fill="#f59e0b"' in svg
    assert 'rotate(15.0' in svg


def test_pure_data_layer_decoupling():
    import sys
    # Verify that mapping data models do not import or depend on PySide6 widgets
    from paleo_workbench.mapping.layers import (
        AnnotationMapLayer,
        ContourMapLayer,
        GridMapLayer,
        MapDocument,
        MapLayer,
        PolygonMapLayer,
        RasterMapLayer,
        VectorMapLayer,
        WellPointMapLayer,
    )
    from paleo_workbench.mapping.composer.models import MapCompositionDocument, ComposerElement

    # Check classes are pure dataclasses
    l = AnnotationMapLayer(id="a", name="A")
    assert hasattr(l, "to_snapshot")
    assert hasattr(l, "to_dict")
    assert isinstance(l.to_dict(), dict)

    doc = MapDocument(id="d", title="D")
    doc.add_layer(l)
    d_dict = doc.to_dict()
    assert d_dict["id"] == "d"
    assert len(d_dict["layers"]) == 1

    comp = MapCompositionDocument(id="c", title="C")
    c_dict = comp.to_dict()
    assert c_dict["id"] == "c"


def test_composer_renderer_with_map_document():
    doc = MapDocument(id="doc_test", title="测试编图", crs="EPSG:4326", extent=(0.0, 0.0, 100.0, 100.0))

    # Add WellPointLayer
    wells = WellPointMapLayer(
        id="wells",
        name="探井",
        features=(
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [25.0, 50.0]}, "properties": {"name": "井-1", "value": 18.2}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [75.0, 50.0]}, "properties": {"name": "井-2", "value": 22.5}},
        ),
    )
    # Add ContourLayer
    contours = ContourMapLayer(
        id="contours",
        name="孔隙度等值线",
        levels=[15.0, 20.0, 25.0],
        features=(
            {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[10.0, 20.0], [50.0, 50.0], [90.0, 80.0]]}, "properties": {"level": 20.0}},
        ),
    )
    # Add AnnotationLayer
    annotations = AnnotationMapLayer(
        id="ann_comp",
        name="地质注记",
    )
    annotations.add_annotation(text="断陷盆地", x=50.0, y=85.0, font_size=14.0, color="#ffffff")

    doc.add_layer(contours)
    doc.add_layer(wells)
    doc.add_layer(annotations)

    comp = MapCompositionDocument(
        id="comp_1",
        title="地质图",
        width_mm=297.0,
        height_mm=210.0,
    )
    comp.add_element(
        ComposerElement(
            id="main_map",
            element_type=ElementType.MAIN_MAP,
            x_mm=10.0,
            y_mm=20.0,
            width_mm=200.0,
            height_mm=150.0,
            properties={"map_document": doc},
        )
    )
    comp.add_element(
        ComposerElement(
            id="legend",
            element_type=ElementType.LEGEND,
            x_mm=220.0,
            y_mm=20.0,
            width_mm=60.0,
            height_mm=100.0,
        )
    )

    renderer = MapComposerRenderer()
    svg = renderer.render_to_svg(comp)

    assert "<svg" in svg
    assert "</svg>" in svg
    assert 'id="main_map"' in svg
    assert 'id="legend"' in svg
    assert "井-1" in svg
    assert "井-2" in svg
    assert "20.0" in svg
    assert "断陷盆地" in svg

