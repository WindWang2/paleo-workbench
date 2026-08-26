"""Milestone 2 Adversarial Stress Testing & Boundary Challenge Suite.

Empirically tests edge cases and boundary conditions for:
1. GraduatedRenderer with malformed/degenerate inputs.
2. AnnotationMapLayer with degenerate annotations.
3. MapDocument.from_snapshot roundtrips with corrupted/missing data.
"""

from __future__ import annotations

import html
import math
from typing import Any, Mapping
import numpy as np
import pytest

from paleo_workbench.mapping.composer.models import (
    ComposerElement,
    ElementType,
    MapCompositionDocument,
)
from paleo_workbench.mapping.composer.renderer import MapComposerRenderer, composer_renderer
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
from paleo_workbench.mapping.map_render_backend import (
    FallbackMapRenderBackend,
    MapLayerSnapshot,
    MapRenderSnapshot,
)
from paleo_workbench.mapping.map_styles import (
    LinePattern,
    MarkerSymbol,
    TextStyle,
    VectorStyle,
    default_style_for,
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


# ============================================================================
# 1. GraduatedRenderer Edge Case Challenges
# ============================================================================

class TestGraduatedRendererEdgeCases:
    """Stress-test GraduatedRenderer with malformed, inverted, and boundary inputs."""

    @pytest.fixture
    def sample_features(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "Feature",
                "id": "f_normal",
                "geometry": {"type": "Point", "coordinates": [10.0, 20.0]},
                "properties": {"value": 50.0, "name": "NormalPoint"},
            },
            {
                "type": "Feature",
                "id": "f_str_val",
                "geometry": {"type": "Point", "coordinates": [12.0, 22.0]},
                "properties": {"value": "75.5", "name": "StringFloatPoint"},
            },
            {
                "type": "Feature",
                "id": "f_non_numeric",
                "geometry": {"type": "Point", "coordinates": [14.0, 24.0]},
                "properties": {"value": "not_a_number", "name": "InvalidStrPoint"},
            },
            {
                "type": "Feature",
                "id": "f_none_val",
                "geometry": {"type": "Point", "coordinates": [16.0, 26.0]},
                "properties": {"value": None, "name": "NonePoint"},
            },
            {
                "type": "Feature",
                "id": "f_missing_prop",
                "geometry": {"type": "Point", "coordinates": [18.0, 28.0]},
                "properties": {"other_field": 100.0},
            },
            {
                "type": "Feature",
                "id": "f_empty_prop",
                "geometry": {"type": "Point", "coordinates": [20.0, 30.0]},
                "properties": {},
            },
            {
                "type": "Feature",
                "id": "f_polygon",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]]],
                },
                "properties": {"porosity": 15.2, "value": "corrupt"},
            },
            {
                "type": "Feature",
                "id": "f_linestring",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[0.0, 0.0], [5.0, 5.0], [10.0, 10.0]],
                },
                "properties": {"value": 25.0},
            },
        ]

    def test_graduated_empty_ranges(self, sample_features):
        """GraduatedRenderer must safely fall back to base fill when ranges list is empty."""
        layer = VectorMapLayer(
            id="grad_empty",
            name="Empty Ranges Layer",
            features=sample_features,
            style={
                "renderer": "graduated",
                "field": "value",
                "fill": "#cccccc",
                "stroke": "#111111",
                "ranges": [],
            },
        )
        renderer = DEFAULT_RENDERER_REGISTRY.resolve(layer)
        assert isinstance(renderer, GraduatedRenderer)

        # Legend fallback
        legends = renderer.legend_items(layer)
        assert len(legends) == 1
        assert legends[0].label == "Empty Ranges Layer"
        assert legends[0].color == "#cccccc"

        # SVG export should not throw and use fallback fill
        ctx = RenderContext(extent=(0.0, 0.0, 50.0, 50.0), width=400, height=300)
        svg = renderer.render_svg(layer, ctx)
        assert "<g " in svg
        assert 'fill="#cccccc"' in svg

    def test_graduated_inverted_ranges(self, sample_features):
        """GraduatedRenderer must handle inverted ranges [100.0, 0.0] without crashing."""
        layer = VectorMapLayer(
            id="grad_inv",
            name="Inverted Ranges",
            features=sample_features,
            style={
                "renderer": "graduated",
                "field": "value",
                "fill": "#ffffff",
                "ranges": [
                    (100.0, 0.0, "#ff0000", "Inverted Range 1"),
                    (50.0, 10.0, "#00ff00", "Inverted Range 2"),
                ],
            },
        )
        renderer = DEFAULT_RENDERER_REGISTRY.resolve(layer)
        assert isinstance(renderer, GraduatedRenderer)

        # Legend items generated without error
        legends = renderer.legend_items(layer)
        assert len(legends) == 2
        assert legends[0].label == "Inverted Range 1"

        # Rendering should fall back safely to default style.fill since no value satisfies 100 <= v <= 0
        ctx = RenderContext(extent=(0.0, 0.0, 50.0, 50.0), width=400, height=300)
        svg = renderer.render_svg(layer, ctx)
        assert "<g " in svg
        # Points should fall back to fill="#ffffff"
        assert 'fill="#ffffff"' in svg

    def test_graduated_non_numeric_and_missing_values(self, sample_features):
        """Features with string, None, missing, or corrupt properties gracefully fall back."""
        layer = VectorMapLayer(
            id="grad_non_numeric",
            name="Non Numeric Test",
            features=sample_features,
            style={
                "renderer": "graduated",
                "field": "value",
                "fill": "#333333",
                "ranges": [
                    (0.0, 30.0, "#0000ff", "Low"),
                    (30.0, 60.0, "#00ff00", "Medium"),
                    (60.0, 100.0, "#ff0000", "High"),
                ],
            },
        )
        renderer = DEFAULT_RENDERER_REGISTRY.resolve(layer)
        ctx = RenderContext(extent=(0.0, 0.0, 50.0, 50.0), width=400, height=300)
        svg = renderer.render_svg(layer, ctx)

        # 50.0 -> Medium (#00ff00)
        assert 'fill="#00ff00"' in svg
        # "75.5" (coerced string float) -> High (#ff0000)
        assert 'fill="#ff0000"' in svg
        # "not_a_number", None, missing -> Fallback (#333333)
        assert 'fill="#333333"' in svg
        # 25.0 LineString -> Low (#0000ff)
        assert 'stroke="#0000ff"' in svg

    def test_graduated_values_outside_all_ranges(self):
        """Values strictly below min range, strictly above max range, or in gaps fall back."""
        features = [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 1]}, "properties": {"val": -999.0}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [2, 2]}, "properties": {"val": 25.0}},  # gap
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [3, 3]}, "properties": {"val": 999.0}},
        ]
        layer = VectorMapLayer(
            id="grad_gaps",
            name="Gaps Layer",
            features=features,
            style={
                "renderer": "graduated",
                "field": "val",
                "fill": "#999999",
                "ranges": [
                    (0.0, 10.0, "#ff1111", "0-10"),
                    (50.0, 100.0, "#11ff11", "50-100"),
                ],
            },
        )
        renderer = DEFAULT_RENDERER_REGISTRY.resolve(layer)
        ctx = RenderContext(extent=(0, 0, 10, 10), width=200, height=200)
        svg = renderer.render_svg(layer, ctx)
        # All 3 features fall outside ranges and must receive fallback color #999999
        assert 'fill="#999999"' in svg
        assert 'fill="#ff1111"' not in svg
        assert 'fill="#11ff11"' not in svg

    def test_graduated_boundary_matches(self):
        """Check exact boundary values: lo bound, hi bound, and overlapping ranges."""
        features = [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 1]}, "properties": {"val": 0.0}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [2, 2]}, "properties": {"val": 50.0}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [3, 3]}, "properties": {"val": 100.0}},
        ]
        layer = VectorMapLayer(
            id="grad_bounds",
            name="Bounds Layer",
            features=features,
            style={
                "renderer": "graduated",
                "field": "val",
                "fill": "#000000",
                "ranges": [
                    (0.0, 50.0, "#111111", "Lower Half"),
                    (50.0, 100.0, "#222222", "Upper Half"),
                ],
            },
        )
        renderer = DEFAULT_RENDERER_REGISTRY.resolve(layer)
        ctx = RenderContext(extent=(0, 0, 10, 10), width=200, height=200)
        svg = renderer.render_svg(layer, ctx)
        # 0.0 -> #111111
        assert 'fill="#111111"' in svg
        # 50.0 -> matches first range #111111
        # 100.0 -> matches second range #222222
        assert 'fill="#222222"' in svg

    def test_graduated_malformed_range_structures(self):
        """Malformed range tuples or dict mappings (e.g. bad types, missing keys) sanitized."""
        style_dict = {
            "renderer": "graduated",
            "field": "val",
            "ranges": [
                [10],                      # too short
                ["invalid", "invalid", "#123"],  # unparseable numbers
                {"min": 10, "max": 20, "fill": "#abcdef"},  # valid dict
                {"color": "#123456"},      # dict with missing min/max (defaults to 0.0, 1.0)
                (30.0, 40.0, "#fedcba"),   # 3-element tuple
            ],
        }
        v_style = VectorStyle.from_dict(style_dict)
        # The invalid ones are skipped, valid dicts & tuples parsed
        assert len(v_style.ranges) == 3
        assert v_style.ranges[0] == (10.0, 20.0, "#abcdef", "")
        assert v_style.ranges[1] == (0.0, 1.0, "#123456", "")
        assert v_style.ranges[2] == (30.0, 40.0, "#fedcba", "")

    def test_vector_style_from_dict_with_vector_style_instance(self):
        """VectorStyle.from_dict should accept an existing VectorStyle instance or convert gracefully."""
        orig = VectorStyle(fill="#123456", stroke="#654321", stroke_width=3.5)
        # Contract in PROJECT.md:58 states style can be dict | VectorStyle
        # Test VectorStyle.from_dict behavior
        res = VectorStyle.from_dict(orig.to_dict())
        assert res.fill == "#123456"
        assert res.stroke_width == 3.5

    def test_graduated_fallback_backend_rendering(self, sample_features):
        """Verify FallbackMapRenderBackend processes graduated styles without exception."""
        layer = VectorMapLayer(
            id="grad_backend_layer",
            name="Grad Backend",
            features=sample_features,
            style={
                "renderer": "graduated",
                "field": "value",
                "fill": "#444444",
                "ranges": [
                    (0.0, 50.0, "#ff0000", "Low"),
                    (50.0, 100.0, "#00ff00", "High"),
                ],
            },
        )
        snapshot = MapRenderSnapshot(
            project_crs="EPSG:4326",
            layers=(layer.to_snapshot(),),
        )
        backend = FallbackMapRenderBackend()
        backend.initialize()
        backend.set_layer_snapshot(snapshot)
        backend.set_extent((0.0, 0.0, 50.0, 50.0))
        backend.set_output_size(400, 300)
        backend.set_dpi(96.0)

        frame = backend.render_sync()
        assert frame is not None
        assert frame.width == 400
        assert frame.height == 300


# ============================================================================
# 2. AnnotationMapLayer Edge Case Challenges
# ============================================================================

class TestAnnotationMapLayerEdgeCases:
    """Stress-test AnnotationMapLayer with degenerate annotations, unicode, NaN, extreme angles."""

    def test_annotation_empty_text(self):
        """Annotation with empty or whitespace-only text should not crash or create broken SVG."""
        layer = AnnotationMapLayer(id="ann_empty", name="Empty Annotation")
        layer.add_annotation(text="", x=10.0, y=20.0)
        layer.add_annotation(text="   ", x=15.0, y=25.0)

        renderer = DEFAULT_RENDERER_REGISTRY.resolve(layer)
        assert isinstance(renderer, AnnotationRenderer)

        ctx = RenderContext(extent=(0.0, 0.0, 50.0, 50.0), width=400, height=300)
        svg = renderer.render_svg(layer, ctx)
        assert "<g " in svg
        # Whitespace/empty text tags should not be emitted
        assert "<text" not in svg

    def test_annotation_extreme_rotation_angles(self):
        """Test extreme rotation angles (720.0, -1080.0, 360.0, 0.0)."""
        layer = AnnotationMapLayer(id="ann_rot", name="Rotated Annotation")
        layer.add_annotation(text="Rot720", x=10.0, y=20.0, rotation=720.0)
        layer.add_annotation(text="RotNeg1080", x=20.0, y=30.0, rotation=-1080.0)
        layer.add_annotation(text="Rot0", x=30.0, y=40.0, rotation=0.0)

        renderer = DEFAULT_RENDERER_REGISTRY.resolve(layer)
        ctx = RenderContext(extent=(0.0, 0.0, 50.0, 50.0), width=400, height=300)
        svg = renderer.render_svg(layer, ctx)

        assert 'transform="rotate(720.0' in svg
        assert 'transform="rotate(-1080.0' in svg
        # 0.0 rotation should not clutter output with rotate transform
        assert 'transform="rotate(0.0' not in svg
        assert "Rot0" in svg

    def test_annotation_unicode_and_special_characters(self):
        """Unicode Chinese, emojis, special punctuation, and multi-line strings."""
        layer = AnnotationMapLayer(id="ann_unicode", name="Unicode Annotation")
        chinese_text = "构造高部位 — 储层厚度增大区"
        emoji_text = "井位 🎯 深度: 3200m 🌋 沉积相带"
        xml_special_text = "Zone A < B & C > D"

        layer.add_annotation(text=chinese_text, x=10.0, y=20.0, font_size=12.0, color="#ff5500")
        layer.add_annotation(text=emoji_text, x=20.0, y=30.0, font_size=10.0)
        layer.add_annotation(text=xml_special_text, x=30.0, y=40.0, font_size=9.0)

        renderer = DEFAULT_RENDERER_REGISTRY.resolve(layer)
        ctx = RenderContext(extent=(0.0, 0.0, 50.0, 50.0), width=400, height=300)
        svg = renderer.render_svg(layer, ctx)

        assert chinese_text in svg
        assert emoji_text in svg
        assert html.escape(xml_special_text) in svg
        import xml.etree.ElementTree as ET
        full_svg = f'<svg xmlns="http://www.w3.org/2000/svg">{svg}</svg>'
        root = ET.fromstring(full_svg)
        assert root is not None

    def test_annotation_nan_and_inf_coordinates(self):
        """Annotations with NaN or Inf coordinates are handled safely without unhandled crashes."""
        layer = AnnotationMapLayer(id="ann_nan", name="NaN Annotation")
        layer.add_annotation(text="Valid Point", x=10.0, y=20.0)
        layer.add_annotation(text="NaN Point", x=float("nan"), y=float("nan"))
        layer.add_annotation(text="Inf Point", x=float("inf"), y=float("-inf"))

        renderer = DEFAULT_RENDERER_REGISTRY.resolve(layer)
        ctx = RenderContext(extent=(0.0, 0.0, 50.0, 50.0), width=400, height=300)
        svg = renderer.render_svg(layer, ctx)

        assert "<g " in svg
        assert "Valid Point" in svg

    def test_annotation_add_set_clear_lifecycle(self):
        """Test dynamic add, set, and clear annotation lifecycle operations."""
        layer = AnnotationMapLayer(id="ann_life", name="Lifecycle Test")
        assert len(layer.annotations) == 0
        assert len(layer.features) == 0

        # Add
        a1 = layer.add_annotation("Note 1", 10.0, 10.0)
        a2 = layer.add_annotation("Note 2", 20.0, 20.0)
        assert len(layer.annotations) == 2
        assert len(layer.features) == 2
        assert layer.extent[0] <= 10.0
        assert layer.extent[2] >= 20.0

        # Set
        layer.set_annotations([
            {"text": "Replaced Note", "x": 50.0, "y": 60.0, "font_size": 14.0},
        ])
        assert len(layer.annotations) == 1
        assert len(layer.features) == 1
        assert layer.features[0]["properties"]["text"] == "Replaced Note"

        # Clear
        layer.clear_annotations()
        assert len(layer.annotations) == 0
        assert len(layer.features) == 0

    def test_annotation_composer_svg_integration(self):
        """Verify MapComposerRenderer renders AnnotationMapLayer in MapCompositionDocument."""
        layer = AnnotationMapLayer(id="ann_comp", name="Composer Annotations")
        layer.add_annotation("构造断裂带", 100.0, 200.0, font_size=12.0, color="#ffff00", rotation=45.0)
        layer.add_annotation("古隆起高点", 150.0, 250.0, font_size=10.0, color="#00ffff")

        doc = MapDocument(id="doc_ann", title="Annotation Map", layers=[layer])
        comp_doc = MapCompositionDocument(id="comp_1", title="Composed Plan", width_mm=297, height_mm=210)
        main_map = ComposerElement(
            id="main_map_1",
            element_type=ElementType.MAIN_MAP,
            x_mm=20.0,
            y_mm=20.0,
            width_mm=200.0,
            height_mm=150.0,
            properties={"map_document": doc},
        )
        comp_doc.add_element(main_map)

        svg = composer_renderer.render_to_svg(comp_doc)
        assert "<svg" in svg
        assert "构造断裂带" in svg
        assert "古隆起高点" in svg
        assert 'transform="rotate(45.0' in svg


# ============================================================================
# 3. MapDocument Snapshot Roundtrip Edge Cases & Bug Reproduction
# ============================================================================

class TestMapDocumentSnapshotRoundtripEdgeCases:
    """Stress-test MapDocument.from_snapshot roundtrips with corrupt, missing, or polymorphic data."""

    def test_reproduce_bug_polymorphic_layer_type_loss_on_snapshot(self):
        """EMPIRICAL BUG REPRODUCTION:
        
        VectorMapLayer.to_snapshot() hardcodes `layer_type="vector"` instead of `self.layer_type`.
        When ContourMapLayer, WellPointMapLayer, or PolygonMapLayer (subclasses of VectorMapLayer)
        are exported to snapshots, their snapshot layer_type is erroneously stamped as "vector".
        Upon MapDocument.from_snapshot(), they are reconstructed as plain VectorMapLayer instances,
        causing loss of:
        1. Subclass identity (isinstance check fails)
        2. RendererRegistry resolution (defaults to SingleSymbolRenderer instead of ContourRenderer / WellSymbolRenderer)
        """
        contour_layer = ContourMapLayer(
            id="lyr_contour",
            name="Contour Layer",
            levels=[10.0, 20.0, 30.0],
            features=({"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}, "properties": {"level": 20.0}},),
            style={"stroke": "#ff8800"},
        )
        well_layer = WellPointMapLayer(
            id="lyr_well",
            name="Well Layer",
            factor_name="porosity",
            features=({"type": "Feature", "geometry": {"type": "Point", "coordinates": [5, 5]}, "properties": {"name": "Well-1", "value": 18.5}},),
        )
        polygon_layer = PolygonMapLayer(
            id="lyr_poly",
            name="Facies Layer",
            categories=[{"name": "Delta Front", "color": "#ffe082"}],
            features=({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 0]]]}, "properties": {"facies": "Delta Front"}},),
        )

        doc = MapDocument(id="doc_test", title="Test Map", layers=[contour_layer, well_layer, polygon_layer])
        snapshot = doc.to_snapshot()

        snap_types = {s.id: s.layer_type for s in snapshot.layers}

        reconstructed = MapDocument.from_snapshot(snapshot)

        # Before snapshot:
        assert isinstance(DEFAULT_RENDERER_REGISTRY.resolve(contour_layer), ContourRenderer)
        assert isinstance(DEFAULT_RENDERER_REGISTRY.resolve(well_layer), WellSymbolRenderer)

        # After snapshot reconstruction:
        # snap_types must preserve exact polymorphic layer types
        assert snap_types["lyr_contour"] == "contour"
        assert snap_types["lyr_well"] == "well_point"
        assert snap_types["lyr_poly"] == "polygon"

        # Reconstructed layers maintain their specific classes
        assert isinstance(reconstructed.layers[0], ContourMapLayer)
        assert isinstance(reconstructed.layers[1], WellPointMapLayer)
        assert isinstance(reconstructed.layers[2], PolygonMapLayer)

        # Renderer resolution preserves specialized renderers
        resolved_contour = DEFAULT_RENDERER_REGISTRY.resolve(reconstructed.layers[0])
        resolved_well = DEFAULT_RENDERER_REGISTRY.resolve(reconstructed.layers[1])
        assert isinstance(resolved_contour, ContourRenderer)
        assert isinstance(resolved_well, WellSymbolRenderer)

    def test_snapshot_roundtrip_grid_annotation_raster_fidelity(self):
        """Ensure GridMapLayer, AnnotationMapLayer, and RasterMapLayer roundtrip cleanly."""
        grid_arr = np.linspace(10, 50, 100).reshape((10, 10))
        gx, gy = np.meshgrid(np.linspace(0, 10, 10), np.linspace(0, 10, 10))

        layers: list[MapLayer] = [
            GridMapLayer(
                id="lyr_grid",
                name="Grid Layer",
                grid_z=grid_arr,
                grid_x=gx,
                grid_y=gy,
                color_ramp_name="plasma",
                value_range=(10.0, 50.0),
                unit="%",
                metadata={"source": "kriging"},
            ),
            AnnotationMapLayer(
                id="lyr_ann",
                name="Annotation Layer",
                annotations=({"text": "Fault Zone", "x": 3.0, "y": 4.0, "font_size": 11.0, "color": "#ff0000", "rotation": 30.0},),
            ),
            RasterMapLayer(
                id="lyr_raster",
                name="Raster Layer",
                source_path="/data/satellite.tif",
                extent=(0.0, 0.0, 100.0, 100.0),
            ),
        ]

        doc = MapDocument(id="doc_full", title="Comprehensive Map", crs="EPSG:3857", layers=layers)
        snapshot = doc.to_snapshot()
        reconstructed = MapDocument.from_snapshot(snapshot, title="Reconstructed Map")

        assert len(reconstructed.layers) == 3
        assert isinstance(reconstructed.layers[0], GridMapLayer)
        assert isinstance(reconstructed.layers[1], AnnotationMapLayer)
        assert isinstance(reconstructed.layers[2], RasterMapLayer)

        assert reconstructed.layers[0].style["color_ramp"] == "plasma"
        assert reconstructed.layers[1].features[0]["properties"]["text"] == "Fault Zone"
        assert reconstructed.layers[2].source_path == "/data/satellite.tif"

    def test_snapshot_corrupted_and_missing_metadata(self):
        """MapDocument.from_snapshot handles snapshots with empty or corrupt metadata gracefully."""
        snap_layer = MapLayerSnapshot(
            id="lyr_missing_meta",
            name="Missing Meta Layer",
            layer_type="vector",
            extent=(0.0, 0.0, 10.0, 10.0),
            crs="EPSG:4326",
            data_revision=1,
            style_revision=1,
            features=(),
            style={},
            visible=True,
            opacity=1.0,
            metadata={},  # empty
            scale_range=None,
        )
        snap = MapRenderSnapshot(project_crs="EPSG:4326", layers=(snap_layer,))
        doc = MapDocument.from_snapshot(snap)

        assert len(doc.layers) == 1
        assert doc.layers[0].metadata == {}
        assert doc.layers[0].scale_range is None

    def test_snapshot_unknown_layer_type_fallback(self):
        """MapDocument.from_snapshot falls back to VectorMapLayer on unrecognized layer_type."""
        snap_layer = MapLayerSnapshot(
            id="lyr_future",
            name="Future SciFi Sensor Layer",
            layer_type="hyperspectral_3d_pointcloud",
            extent=(0.0, 0.0, 10.0, 10.0),
            crs="EPSG:4326",
            data_revision=1,
            style_revision=1,
            features=({"type": "Feature", "geometry": {"type": "Point", "coordinates": [5, 5]}},),
            style={},
            visible=True,
            opacity=1.0,
            metadata={},
        )
        snap = MapRenderSnapshot(project_crs="EPSG:4326", layers=(snap_layer,))
        doc = MapDocument.from_snapshot(snap)

        assert len(doc.layers) == 1
        assert isinstance(doc.layers[0], VectorMapLayer)
        assert doc.layers[0].name == "Future SciFi Sensor Layer"

    def test_document_reorder_and_remove_nonexistent(self):
        """Document operations on nonexistent IDs do not corrupt state."""
        l1 = VectorMapLayer(id="l1", name="L1")
        l2 = VectorMapLayer(id="l2", name="L2")
        doc = MapDocument(layers=[l1, l2])

        # Remove nonexistent ID
        removed = doc.remove_layer("non_existent_id")
        assert removed is None
        assert len(doc.layers) == 2

        # Reorder with unknown IDs mixed in
        doc.reorder_layers(["ghost_id", "l2", "l1", "another_ghost"])
        assert [lyr.id for lyr in doc.layers] == ["l2", "l1"]

        # Get nonexistent
        assert doc.get_layer("ghost_id") is None
        assert doc.get_layer("l1") is l1

    def test_document_extent_recomputation_with_degenerate_extents(self):
        """recompute_extent ignores default unit extents (0,0,1,1) and computes true bounding box."""
        l1 = VectorMapLayer(id="l1", extent=(0.0, 0.0, 1.0, 1.0), visible=True)
        l2 = VectorMapLayer(id="l2", extent=(100.0, 200.0, 300.0, 400.0), visible=True)
        l3 = VectorMapLayer(id="l3", extent=(50.0, 100.0, 500.0, 600.0), visible=False)  # invisible

        doc = MapDocument(layers=[l1, l2, l3])
        extent = doc.recompute_extent()
        # l1 is default (0,0,1,1), l3 is hidden -> only l2 considered
        assert extent == (100.0, 200.0, 300.0, 400.0)

        # Make l3 visible
        l3.set_visible(True)
        extent = doc.recompute_extent()
        assert extent == (50.0, 100.0, 500.0, 600.0)
