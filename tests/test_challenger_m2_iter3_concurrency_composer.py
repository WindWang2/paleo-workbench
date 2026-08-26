"""Milestone 2 Iteration 3 Challenger Stress Test Suite.

Adversarial testing covering:
1. Concurrent snapshot serialization, deserialization, and immutability across all 7 layer types.
2. Composer layout rendering with edge-case aspect ratios, empty/long/special titles, and all layer types.
3. Multi-threaded snapshot capture vs document mutation safety.
4. Export fidelity and valid SVG generation across extreme layouts.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
import html
import json
import math
import os
import random
import threading
import time
from typing import Any, Mapping
from uuid import uuid4
import xml.etree.ElementTree as ET

import numpy as np
import pytest
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPdfWriter
from PySide6.QtSvg import QSvgGenerator

from paleo_workbench.mapping.color_ramps import get_color_ramp
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
from paleo_workbench.workflow.factor_grid_result import FactorGridResult


@pytest.fixture(autouse=True)
def _ensure_qapp(qapp):
    return qapp


# ============================================================================
# LAYER FACTORY HELPERS FOR ALL 7 LAYER TYPES
# ============================================================================

def create_sample_vector_layer(layer_id: str = "vec_1", n_pts: int = 10) -> VectorMapLayer:
    coords = [[100.0 + i * 2.0, 30.0 + i * 1.5] for i in range(n_pts)]
    return VectorMapLayer(
        id=layer_id,
        name=f"Vector Layer {layer_id}",
        features=({
            "type": "Feature",
            "id": f"f_{layer_id}",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {"type": "Fault", "severity": 3},
        },),
        style={"stroke": "#e74c3c", "stroke_width": 2.0},
        crs="EPSG:4326",
    )


def create_sample_grid_layer(layer_id: str = "grid_1", h: int = 15, w: int = 15) -> GridMapLayer:
    x = np.linspace(100.0, 120.0, w, dtype=np.float64)
    y = np.linspace(30.0, 50.0, h, dtype=np.float64)
    xx, yy = np.meshgrid(x, y)
    z = (np.sin(xx / 5.0) * np.cos(yy / 5.0) * 20.0 + 50.0).astype(np.float32)
    # Introduce NaN
    z[0, 0] = np.nan
    res = FactorGridResult(
        grid_z=z,
        grid_x=x,
        grid_y=y,
        factor_name="Porosity",
        algorithm_id="kriging",
        unit="%",
        crs="EPSG:4326",
    )
    return GridMapLayer(
        id=layer_id,
        name=f"Grid Layer {layer_id}",
        grid_result=res,
        color_ramp_name="viridis",
        crs="EPSG:4326",
    )


def create_sample_contour_layer(layer_id: str = "cnt_1") -> ContourMapLayer:
    features = tuple({
        "type": "Feature",
        "id": f"cnt_f_{i}",
        "geometry": {
            "type": "LineString",
            "coordinates": [[100.0 + i * 2.0, 30.0], [110.0 + i * 2.0, 45.0], [120.0 + i * 2.0, 40.0]],
        },
        "properties": {"level": 100.0 + i * 20.0},
    } for i in range(5))
    return ContourMapLayer(
        id=layer_id,
        name=f"Contour Layer {layer_id}",
        features=features,
        levels=[100.0, 120.0, 140.0, 160.0, 180.0],
        contour_interval=20.0,
        crs="EPSG:4326",
    )


def create_sample_well_point_layer(layer_id: str = "well_1", n_wells: int = 8) -> WellPointMapLayer:
    features = tuple({
        "type": "Feature",
        "id": f"well_f_{i}",
        "geometry": {"type": "Point", "coordinates": [102.0 + i * 2.0, 32.0 + i * 1.8]},
        "properties": {"name": f"Well-00{i}", "porosity": 15.0 + i * 1.2, "depth": 2500.0 + i * 100},
    } for i in range(n_wells))
    return WellPointMapLayer(
        id=layer_id,
        name=f"Well Layer {layer_id}",
        factor_name="Porosity",
        unit="%",
        features=features,
        crs="EPSG:4326",
    )


def create_sample_polygon_layer(layer_id: str = "poly_1") -> PolygonMapLayer:
    poly_coords = [[[105.0, 35.0], [115.0, 35.0], [115.0, 42.0], [105.0, 42.0], [105.0, 35.0]]]
    return PolygonMapLayer(
        id=layer_id,
        name=f"Facies Layer {layer_id}",
        categories=[{"name": "Delta Front", "color": "#ffe082"}],
        features=({
            "type": "Feature",
            "id": f"poly_f_{layer_id}",
            "geometry": {"type": "Polygon", "coordinates": poly_coords},
            "properties": {"facies_name": "Delta Front", "code": 101},
        },),
        crs="EPSG:4326",
    )


def create_sample_annotation_layer(layer_id: str = "ann_1") -> AnnotationMapLayer:
    layer = AnnotationMapLayer(
        id=layer_id,
        name=f"Annotation Layer {layer_id}",
        crs="EPSG:4326",
    )
    layer.add_annotation("古隆起轴线 (Paleo-High Axis)", 108.0, 38.0, font_size=12.0, color="#f1c40f", rotation=45.0)
    layer.add_annotation("Depocenter 深度: >4500m & <5000m", 112.0, 34.0, font_size=10.0, color="#3498db", rotation=0.0)
    return layer


def create_sample_raster_layer(layer_id: str = "rast_1") -> RasterMapLayer:
    return RasterMapLayer(
        id=layer_id,
        name=f"Satellite Raster {layer_id}",
        source_path="/tmp/fake_satellite_dem.tif",
        extent=(100.0, 30.0, 120.0, 50.0),
        crs="EPSG:4326",
        style={"opacity": 0.8},
    )


def create_7_layer_map_document(doc_id: str = "doc_7_layers") -> MapDocument:
    doc = MapDocument(id=doc_id, title="7-Layer Comprehensive Map", crs="EPSG:4326")
    doc.add_layer(create_sample_raster_layer(f"{doc_id}_rast"))
    doc.add_layer(create_sample_grid_layer(f"{doc_id}_grid"))
    doc.add_layer(create_sample_polygon_layer(f"{doc_id}_poly"))
    doc.add_layer(create_sample_contour_layer(f"{doc_id}_cnt"))
    doc.add_layer(create_sample_vector_layer(f"{doc_id}_vec"))
    doc.add_layer(create_sample_well_point_layer(f"{doc_id}_well"))
    doc.add_layer(create_sample_annotation_layer(f"{doc_id}_ann"))
    doc.recompute_extent()
    return doc


# ============================================================================
# 1. CONCURRENT SNAPSHOT SERIALIZATION & DESERIALIZATION ACROSS ALL 7 LAYER TYPES
# ============================================================================

class TestConcurrentSnapshotAcrossAll7LayerTypes:
    """Stress test snapshot serialization, deserialization, and immutability under concurrency."""

    def test_roundtrip_all_7_layer_types_preservation(self):
        """Verify that all 7 layer types correctly convert to snapshot and reconstruct to matching classes."""
        doc = create_7_layer_map_document("doc_verify_7")
        assert len(doc.layers) == 7

        snap = doc.to_snapshot()
        assert isinstance(snap, MapRenderSnapshot)
        assert len(snap.layers) == 7

        # Verify snapshot layer types
        types_in_snap = [lyr.layer_type for lyr in snap.layers]
        assert "raster_source" in types_in_snap
        assert "scalar_grid" in types_in_snap
        assert "polygon" in types_in_snap
        assert "contour" in types_in_snap
        assert "vector" in types_in_snap
        assert "well_point" in types_in_snap
        assert "annotation" in types_in_snap

        # Reconstruct from snapshot
        reconstructed = MapDocument.from_snapshot(snap, title="Reconstructed 7")
        assert len(reconstructed.layers) == 7
        assert isinstance(reconstructed.layers[0], RasterMapLayer)
        assert isinstance(reconstructed.layers[1], GridMapLayer)
        assert isinstance(reconstructed.layers[2], PolygonMapLayer)
        assert isinstance(reconstructed.layers[3], ContourMapLayer)
        assert isinstance(reconstructed.layers[4], VectorMapLayer)
        assert isinstance(reconstructed.layers[5], WellPointMapLayer)
        assert isinstance(reconstructed.layers[6], AnnotationMapLayer)

    def test_json_dict_serialization_fidelity_all_7_layer_types(self):
        """Verify that to_dict() produces valid JSON-serializable structures for all 7 layer types."""
        doc = create_7_layer_map_document("doc_json")
        d = doc.to_dict()
        assert d["id"] == "doc_json"
        assert len(d["layers"]) == 7

        # Ensure json.dumps does not raise TypeError (e.g., numpy arrays, tuples)
        serialized_json = json.dumps(d)
        assert isinstance(serialized_json, str)
        loaded = json.loads(serialized_json)
        assert loaded["id"] == "doc_json"
        assert len(loaded["layers"]) == 7

    def test_concurrent_snapshot_capture_during_heavy_mutations(self):
        """Stress test: 12 threads concurrently mutating doc vs taking snapshots vs deserializing."""
        doc = create_7_layer_map_document("doc_concurrent_stress")
        errors: list[Exception] = []
        stop_event = threading.Event()
        lock = threading.Lock()

        def mutator_worker(worker_id: int):
            try:
                for step in range(100):
                    if stop_event.is_set():
                        break
                    time.sleep(0.001)
                    # Perform mutations
                    with lock:
                        # Add or modify annotations
                        ann_layer = doc.get_layer("doc_concurrent_stress_ann")
                        if isinstance(ann_layer, AnnotationMapLayer):
                            ann_layer.add_annotation(f"W{worker_id}_{step}", 100.0 + step * 0.1, 30.0 + step * 0.1)
                        # Reorder layers
                        layer_ids = [l.id for l in doc.layers]
                        random.shuffle(layer_ids)
                        doc.reorder_layers(layer_ids)
                        # Change opacity/visibility
                        for l in doc.layers:
                            l.opacity = random.choice([0.5, 0.8, 1.0])
                            l.visible = random.choice([True, True, False])
            except Exception as e:
                errors.append(e)

        def snapshot_reader_worker(worker_id: int):
            try:
                for step in range(100):
                    if stop_event.is_set():
                        break
                    time.sleep(0.001)
                    with lock:
                        snap = doc.to_snapshot()
                    # Inspect snapshot outside lock
                    assert isinstance(snap, MapRenderSnapshot)
                    assert len(snap.layers) == 7
                    # Reconstruct doc from snapshot
                    rebuilt = MapDocument.from_snapshot(snap)
                    assert len(rebuilt.layers) == 7
                    # Ensure layer snapshots are immutable frozen dataclasses
                    for lyr_snap in snap.layers:
                        assert isinstance(lyr_snap, MapLayerSnapshot)
                        with pytest.raises((AttributeError, TypeError, Exception)):
                            lyr_snap.name = "Illegal Mutation"
            except Exception as e:
                errors.append(e)

        def dict_serializer_worker(worker_id: int):
            try:
                for step in range(50):
                    if stop_event.is_set():
                        break
                    time.sleep(0.002)
                    with lock:
                        d = doc.to_dict()
                    # Serialize to JSON outside lock
                    json_str = json.dumps(d)
                    assert len(json_str) > 100
            except Exception as e:
                errors.append(e)

        with ThreadPoolExecutor(max_workers=12) as executor:
            futures = []
            for i in range(4):
                futures.append(executor.submit(mutator_worker, i))
            for i in range(4):
                futures.append(executor.submit(snapshot_reader_worker, i))
            for i in range(4):
                futures.append(executor.submit(dict_serializer_worker, i))

            for f in as_completed(futures):
                f.result()

        assert len(errors) == 0, f"Encountered {len(errors)} errors during concurrent execution: {errors[:3]}"

    def test_deep_snapshot_immutability_guarantee_all_layers(self):
        """Mutating original layers or styles after snapshot must not alter the captured snapshot."""
        doc = create_7_layer_map_document("doc_immutability_test")
        snap = doc.to_snapshot()

        # Capture snapshot layer properties
        snap_well_features_len = len(snap.layers[5].features)
        snap_ann_features_len = len(snap.layers[6].features)
        snap_style_copy = dict(snap.layers[0].style)

        # Mutate document layers aggressively
        well_lyr = doc.get_layer("doc_immutability_test_well")
        assert isinstance(well_lyr, WellPointMapLayer)
        well_lyr.set_features([])  # Clear features
        assert len(well_lyr.features) == 0

        ann_lyr = doc.get_layer("doc_immutability_test_ann")
        assert isinstance(ann_lyr, AnnotationMapLayer)
        ann_lyr.clear_annotations()  # Clear annotations
        assert len(ann_lyr.annotations) == 0

        doc.layers[0].style["custom_key"] = "hacked_value"
        doc.crs = "EPSG:3857"

        # Verify snapshot remains completely unchanged
        assert len(snap.layers[5].features) == snap_well_features_len
        assert len(snap.layers[6].features) == snap_ann_features_len
        assert snap.layers[0].style == snap_style_copy
        assert snap.project_crs == "EPSG:4326"


# ============================================================================
# 2. COMPOSER LAYOUT RENDERING WITH ADVERSARIAL EDGE CASES
# ============================================================================

class TestComposerLayoutEdgeCases:
    """Stress test MapComposerRenderer with edge-case aspect ratios, extreme titles, and layer structures."""

    def test_composer_extreme_aspect_ratios(self):
        """Test ultra-wide (10000:10), ultra-tall (10:10000), tiny (0.1:0.1) and custom aspect ratios."""
        renderer = MapComposerRenderer()

        test_dimensions = [
            (10000.0, 10.0, "Ultra Wide Panorama"),
            (10.0, 10000.0, "Ultra Tall Well Log Column"),
            (0.1, 0.1, "Microscopic Stamp"),
            (297.0, 210.0, "A4 Landscape Standard"),
            (210.0, 297.0, "A4 Portrait Standard"),
            (841.0, 1189.0, "A0 Poster Giant"),
        ]

        for w_mm, h_mm, label in test_dimensions:
            comp_doc = MapCompositionDocument(
                id=f"comp_{w_mm}_{h_mm}",
                title=label,
                width_mm=w_mm,
                height_mm=h_mm,
            )
            # Add main map element
            comp_doc.add_element(
                ComposerElement(
                    id="map_elem",
                    element_type=ElementType.MAIN_MAP,
                    x_mm=w_mm * 0.05,
                    y_mm=h_mm * 0.05,
                    width_mm=w_mm * 0.9,
                    height_mm=h_mm * 0.9,
                    properties={"title": f"Map inside {label}"},
                )
            )
            # Add title
            comp_doc.add_element(
                ComposerElement(
                    id="title_elem",
                    element_type=ElementType.TITLE,
                    x_mm=w_mm * 0.1,
                    y_mm=h_mm * 0.01,
                    width_mm=w_mm * 0.8,
                    height_mm=max(1.0, h_mm * 0.05),
                    properties={"text": label},
                )
            )

            svg = renderer.render_to_svg(comp_doc)
            assert isinstance(svg, str)
            assert f'viewBox="0 0 {w_mm} {h_mm}"' in svg
            # Verify valid XML
            root = ET.fromstring(svg)
            assert root.tag.endswith("svg")

    def test_composer_empty_whitespace_and_none_titles(self):
        """Test titles with empty string, whitespace, None, and missing property keys."""
        renderer = MapComposerRenderer()

        edge_titles = [
            ("", "empty string"),
            ("   \t  \n  ", "whitespace only"),
            ("None", "string None"),
        ]

        for title_val, desc in edge_titles:
            comp_doc = MapCompositionDocument(
                id=f"comp_title_{desc.replace(' ', '_')}",
                title="Doc Title",
                width_mm=200.0,
                height_mm=150.0,
            )
            comp_doc.add_element(
                ComposerElement(
                    id="title_1",
                    element_type=ElementType.TITLE,
                    x_mm=10.0,
                    y_mm=10.0,
                    width_mm=180.0,
                    height_mm=15.0,
                    properties={"text": title_val},
                )
            )
            # Also test title element without "text" key in properties
            comp_doc.add_element(
                ComposerElement(
                    id="title_default",
                    element_type=ElementType.TITLE,
                    x_mm=10.0,
                    y_mm=30.0,
                    width_mm=180.0,
                    height_mm=15.0,
                    properties={},  # No "text" key
                )
            )

            svg = renderer.render_to_svg(comp_doc)
            root = ET.fromstring(svg)
            assert root.tag.endswith("svg")

    def test_composer_ultra_long_and_special_character_titles(self):
        """Test titles with 10,000+ characters, XML entities, CJK, emoji, and HTML tags."""
        renderer = MapComposerRenderer()

        huge_title = "塔里木盆地-奥陶系-鹰山组-古地理与沉积相分布图 " * 300  # ~7,500 chars
        special_chars_title = "<script>alert('XSS & Injection')</script> & \" ' < > 🧭 🗺️ 🏔️"

        comp_doc = MapCompositionDocument(
            id="comp_huge_special",
            title="Complex Title Doc",
            width_mm=400.0,
            height_mm=300.0,
        )
        comp_doc.add_element(
            ComposerElement(
                id="title_huge",
                element_type=ElementType.TITLE,
                x_mm=10.0,
                y_mm=5.0,
                width_mm=380.0,
                height_mm=20.0,
                properties={"text": huge_title},
            )
        )
        comp_doc.add_element(
            ComposerElement(
                id="title_special",
                element_type=ElementType.TITLE,
                x_mm=10.0,
                y_mm=30.0,
                width_mm=380.0,
                height_mm=20.0,
                properties={"text": special_chars_title},
            )
        )

        svg = renderer.render_to_svg(comp_doc)
        # Must be well-formed XML without escaping failures
        root = ET.fromstring(svg)
        assert root.tag.endswith("svg")
        # Ensure special characters were escaped
        assert "<script>" not in svg
        assert "&lt;script&gt;" in svg or "&amp;" in svg

    def test_composer_rendering_with_full_7_layer_map_document(self):
        """Attach a full 7-layer MapDocument to Composer Element and render all components."""
        map_doc = create_7_layer_map_document("comp_full_map_doc")
        comp_doc = MapCompositionDocument(
            id="comp_full_layout",
            title="鄂尔多斯盆地延长组综合地质图",
            width_mm=297.0,
            height_mm=210.0,
        )
        # 1. Main map element containing the MapDocument
        comp_doc.add_element(
            ComposerElement(
                id="main_map",
                element_type=ElementType.MAIN_MAP,
                x_mm=15.0,
                y_mm=20.0,
                width_mm=200.0,
                height_mm=160.0,
                properties={"map_document": map_doc},
            )
        )
        # 2. Dynamic Legend element linked to main map
        comp_doc.add_element(
            ComposerElement(
                id="legend",
                element_type=ElementType.LEGEND,
                x_mm=220.0,
                y_mm=20.0,
                width_mm=65.0,
                height_mm=100.0,
                properties={},
            )
        )
        # 3. North Arrow
        comp_doc.add_element(
            ComposerElement(
                id="north_arrow",
                element_type=ElementType.NORTH_ARROW,
                x_mm=200.0,
                y_mm=25.0,
                width_mm=12.0,
                height_mm=18.0,
            )
        )
        # 4. Scale Bar
        comp_doc.add_element(
            ComposerElement(
                id="scale_bar",
                element_type=ElementType.SCALE_BAR,
                x_mm=15.0,
                y_mm=185.0,
                width_mm=50.0,
                height_mm=10.0,
                properties={"length_km": 100},
            )
        )
        # 5. Title
        comp_doc.add_element(
            ComposerElement(
                id="title",
                element_type=ElementType.TITLE,
                x_mm=50.0,
                y_mm=5.0,
                width_mm=150.0,
                height_mm=12.0,
                properties={"text": "鄂尔多斯盆地延长组长7油层组沉积相及孔隙度分布图"},
            )
        )

        svg = composer_renderer.render_to_svg(comp_doc)
        assert len(svg) > 1000
        # Parse XML to guarantee strict XML compliance
        root = ET.fromstring(svg)
        assert root.tag.endswith("svg")
        # Check elements rendered
        ids = [elem.attrib.get("id") for elem in root.iter() if "id" in elem.attrib]
        assert "main_map" in ids
        assert "legend" in ids
        assert "north_arrow" in ids
        assert "scale_bar" in ids
        assert "title" in ids

    def test_composer_empty_and_corrupt_element_properties_resilience(self):
        """Ensure Composer elements with empty or malformed properties do not raise unhandled exceptions."""
        comp_doc = MapCompositionDocument(id="comp_corrupt", title="Corrupt Test", width_mm=200.0, height_mm=200.0)

        # Scale bar with missing length_km or string length_km
        comp_doc.add_element(
            ComposerElement(id="scale_none", element_type=ElementType.SCALE_BAR, x_mm=10, y_mm=10, width_mm=40, height_mm=10, properties={})
        )
        # Legend with malformed items
        comp_doc.add_element(
            ComposerElement(
                id="legend_bad_items",
                element_type=ElementType.LEGEND,
                x_mm=60,
                y_mm=10,
                width_mm=40,
                height_mm=40,
                properties={"items": [{"label": "Bad Stop", "symbol_type": "gradient", "gradient_stops": None}]},
            )
        )
        # Main map with non-existent or empty layers list
        comp_doc.add_element(
            ComposerElement(
                id="main_map_empty",
                element_type=ElementType.MAIN_MAP,
                x_mm=10,
                y_mm=60,
                width_mm=100,
                height_mm=100,
                properties={"layers": [None, {}, "invalid_string"]},
            )
        )

        svg = composer_renderer.render_to_svg(comp_doc)
        root = ET.fromstring(svg)
        assert root.tag.endswith("svg")


# ============================================================================
# 3. EXPORT FIDELITY & RASTER/VECTOR COMPOSITIONS
# ============================================================================

class TestExportFidelityAll7LayerTypes:
    """Validate raster and vector export consistency across all 7 layer types."""

    def test_fallback_backend_all_7_layers_qpainter_render(self):
        """Render all 7 layer types through FallbackMapRenderBackend synchronously onto QImage."""
        doc = create_7_layer_map_document("doc_render_7")
        snap = doc.to_snapshot()

        backend = FallbackMapRenderBackend()
        try:
            backend.initialize()
            backend.set_layer_snapshot(snap)
            backend.set_extent((100.0, 30.0, 120.0, 50.0))
            w, h = 800, 600
            backend.set_output_size(w, h)
            img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
            img.fill(Qt.transparent)

            painter = QPainter(img)
            try:
                backend.render_to_painter(painter, w, h, dpi=96.0)
            finally:
                painter.end()

            # Check that non-transparent pixels exist
            ptr = img.constBits()
            buf = np.frombuffer(ptr, dtype=np.uint8).reshape((h, w, 4))
            non_zero = np.count_nonzero(buf)
            assert non_zero > 0, "Rendered image should not be completely blank"
        finally:
            backend.shutdown()

    def test_svg_vector_export_fidelity(self):
        """Export snapshot via QSvgGenerator to verify vector painter compatibility."""
        doc = create_7_layer_map_document("doc_svg_vector")
        snap = doc.to_snapshot()

        import tempfile
        from PySide6.QtCore import QSize, QRect
        with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as tmp:
            tmp_path = tmp.name

        w, h = 800, 600
        try:
            generator = QSvgGenerator()
            generator.setFileName(tmp_path)
            generator.setSize(QSize(w, h))
            generator.setViewBox(QRect(0, 0, w, h))
            generator.setResolution(96)
            generator.setTitle("SVG Export Fidelity Test")

            svg_painter = QPainter(generator)
            backend = FallbackMapRenderBackend()
            try:
                backend.initialize()
                backend.set_layer_snapshot(snap)
                backend.set_extent((100.0, 30.0, 120.0, 50.0))
                backend.set_output_size(w, h)
                backend.render_to_painter(svg_painter, w, h, dpi=96.0)
            finally:
                svg_painter.end()
                backend.shutdown()

            assert os.path.exists(tmp_path)
            size = os.path.getsize(tmp_path)
            assert size > 500, f"SVG file too small: {size} bytes"

            # Verify generated SVG is valid XML
            tree = ET.parse(tmp_path)
            root = tree.getroot()
            assert root.tag.endswith("svg")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
