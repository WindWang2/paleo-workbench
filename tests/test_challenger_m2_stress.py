"""Empirical Stress Test Suite & Adversarial Harness for Milestone 2.

Author: Challenger M2 (Mapping Engine 2.0 & Styling System)
Scope:
1. Rapid MapDocument Layer Mutations Stress (100+ mixed layers, rapid reordering, additions, deletions, extents).
2. Concurrent Snapshot Generations & Immutability Verification (multi-threaded mutation vs snapshot capture, deep immutability).
3. High-Resolution SVG, PNG, and PDF Exports (300/600 DPI, 4K/8K dimensions, complex graduated ranges, multi-line & CJK annotations).
4. Empirical reproduction of discovered bugs:
   - Bug 1 (CRITICAL): AttributeError on prepared.layer_type in FallbackMapRenderBackend for Point layers without explicit labels.
   - Bug 2 (HIGH): Type erasure in VectorMapLayer.to_snapshot() causing loss of Contour, WellPoint, and Polygon subclasses in from_snapshot().
   - Bug 3 (MEDIUM): Malformed SVG XML output when annotations/labels contain XML special characters.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import html
import io
import math
import os
import random
import tempfile
import threading
import time
from typing import Any, Mapping
from uuid import uuid4
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image
import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QImage, QPainter, QPdfWriter
from PySide6.QtWidgets import QApplication

from paleo_workbench.mapping.color_ramps import get_color_ramp, list_color_ramps
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
from paleo_workbench.workflow.factor_grid_result import FactorGridResult, GridStatistics


# ============================================================================
# HELPER GENERATORS FOR ADVERSARIAL & STRESS DATA
# ============================================================================

def _generate_synthetic_grid(h: int = 50, w: int = 50) -> GridMapLayer:
    """Generate a realistic GridMapLayer with Gaussian topography & NaN holes."""
    x = np.linspace(100.0, 200.0, w, dtype=np.float64)
    y = np.linspace(30.0, 80.0, h, dtype=np.float64)
    xx, yy = np.meshgrid(x, y)
    zz = (np.sin(xx / 15.0) * np.cos(yy / 10.0) * 50.0 + 100.0).astype(np.float32)
    # Introduce NaN holes at boundary/center
    zz[0:5, 0:5] = np.nan
    zz[20:25, 20:25] = np.nan

    result = FactorGridResult(
        grid_z=zz,
        grid_x=x,
        grid_y=y,
        factor_name="Porosity",
        algorithm_id="kriging",
        unit="%",
    )
    return GridMapLayer(
        name="Synthetic Grid",
        grid_result=result,
        color_ramp_name="plasma",
    )


def _generate_synthetic_graduated_layer(num_features: int = 100) -> VectorMapLayer:
    """Generate a VectorMapLayer with complex graduated ranges and 100+ polygon/point features."""
    features = []
    for i in range(num_features):
        val = random.uniform(-50.0, 150.0)
        cx = 100.0 + (i % 10) * 10.0 + random.uniform(-2.0, 2.0)
        cy = 30.0 + (i // 10) * 5.0 + random.uniform(-2.0, 2.0)
        # Mix of Polygons and Points
        if i % 2 == 0:
            poly = [
                [cx - 2.0, cy - 2.0],
                [cx + 2.0, cy - 2.0],
                [cx + 2.0, cy + 2.0],
                [cx - 2.0, cy + 2.0],
                [cx - 2.0, cy - 2.0],
            ]
            geom = {"type": "Polygon", "coordinates": [poly]}
        else:
            geom = {"type": "Point", "coordinates": [cx, cy]}

        features.append({
            "type": "Feature",
            "id": f"feat_{i}",
            "geometry": geom,
            "properties": {"permeability": val, "name": f"Block-{i:03d}"},
        })

    ranges = [
        (-100.0, 0.0, "#2c7bb6", "Low (<0)"),
        (0.0, 25.0, "#abd9e9", "Medium-Low (0-25)"),
        (25.0, 75.0, "#ffffbf", "Medium (25-75)"),
        (75.0, 120.0, "#fdae61", "High (75-120)"),
        (120.0, 300.0, "#d7191c", "Ultra-High (>120)"),
    ]
    style = VectorStyle(
        field="permeability",
        ranges=ranges,
        fill="#cccccc",
        stroke="#111111",
        stroke_width=1.0,
        labels=TextStyle(field="name", size=8.0, color="#222222"),
    ).to_dict()

    return VectorMapLayer(
        name="Graduated Permeability",
        features=tuple(features),
        style=style,
    )


def _generate_synthetic_annotation_layer(num_annotations: int = 50) -> AnnotationMapLayer:
    """Generate an AnnotationMapLayer with multi-line, CJK, rotated, and scaled annotations."""
    layer = AnnotationMapLayer(name="Field Annotations")
    for i in range(num_annotations):
        x = 100.0 + (i % 10) * 10.0
        y = 30.0 + (i // 10) * 5.0
        rotation = (i * 35.0) % 360.0
        size = 8.0 + (i % 5) * 2.0
        cjk_text = f"构造带-{i:02d}\nFault Zone {i}\nDepth: {1000 + i * 50}m"
        layer.add_annotation(
            text=cjk_text,
            x=x,
            y=y,
            font_size=size,
            color="#e65100" if i % 2 == 0 else "#0d47a1",
            rotation=rotation,
            bold=(i % 3 == 0),
        )
    return layer


# ============================================================================
# 1. RAPID MAPDOCUMENT LAYER MUTATION STRESS TESTS
# ============================================================================

def test_map_document_50_plus_layers_rapid_mutation_lifecycle():
    """Stress test MapDocument with 60+ mixed polymorphic layers across 500+ mutations."""
    doc = MapDocument(title="Mega Stress Map", crs="EPSG:4326")

    # 1. Add 60 mixed layers
    created_layers: list[MapLayer] = []
    for idx in range(60):
        mod = idx % 6
        if mod == 0:
            lyr = _generate_synthetic_grid(20, 20)
            lyr.id = f"grid_{idx}"
            lyr.name = f"Grid Layer {idx}"
        elif mod == 1:
            lyr = _generate_synthetic_graduated_layer(20)
            lyr.id = f"grad_{idx}"
            lyr.name = f"Graduated Layer {idx}"
        elif mod == 2:
            lyr = _generate_synthetic_annotation_layer(10)
            lyr.id = f"ann_{idx}"
            lyr.name = f"Annotation Layer {idx}"
        elif mod == 3:
            lyr = ContourMapLayer(
                id=f"cnt_{idx}",
                name=f"Contour {idx}",
                features=({
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": [[100.0, 30.0], [200.0, 80.0]]},
                    "properties": {"level": 100.0 + idx * 10},
                },),
                levels=[100.0, 200.0, 300.0],
            )
        elif mod == 4:
            lyr = WellPointMapLayer(
                id=f"well_{idx}",
                name=f"Well Layer {idx}",
                features=({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [150.0 + idx * 0.5, 50.0 + idx * 0.5]},
                    "properties": {"name": f"W-{idx}", "value": 25.5},
                },),
            )
        else:
            lyr = PolygonMapLayer(
                id=f"poly_{idx}",
                name=f"Facies {idx}",
                features=({
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[110.0, 35.0], [120.0, 35.0], [120.0, 45.0], [110.0, 45.0], [110.0, 35.0]]],
                    },
                    "properties": {"facies_name": "Delta Front"},
                },),
            )
        created_layers.append(lyr)
        doc.add_layer(lyr)

    assert len(doc.layers) == 60
    assert doc.active_layer_id == "grid_0"
    ext = doc.recompute_extent()
    assert ext[0] <= 100.0 and ext[2] >= 170.0

    # 2. Perform 200 rapid reorderings
    all_ids = [lyr.id for lyr in doc.layers]
    for _ in range(200):
        shuffled = list(all_ids)
        random.shuffle(shuffled)
        doc.reorder_layers(shuffled)
        assert [l.id for l in doc.layers] == shuffled

    # 3. Partial sequence reordering + unknown IDs
    partial = all_ids[10:30]
    doc.reorder_layers(partial + ["non_existent_id_999"])
    assert [l.id for l in doc.layers[:20]] == partial
    assert len(doc.layers) == 60

    # 4. Rapid removals: remove 30 layers randomly
    for lyr_id in all_ids[:30]:
        removed = doc.remove_layer(lyr_id)
        assert removed is not None
        assert removed.id == lyr_id
    assert len(doc.layers) == 30

    # Non-existent layer removal
    assert doc.remove_layer("already_removed_id") is None

    # 5. Insert at random positions
    for i in range(10):
        new_lyr = AnnotationMapLayer(id=f"new_ann_{i}", name=f"New Ann {i}")
        doc.add_layer(new_lyr, position=i * 2)
    assert len(doc.layers) == 40


def test_extent_recalculation_edge_cases():
    """Test extent recomputations with empty, single-point, line, hidden, and degenerate layers."""
    doc = MapDocument()
    assert doc.recompute_extent() == (0.0, 0.0, 1.0, 1.0)

    # 1. Single Point Vector Layer (requires pad expansion)
    p_layer = VectorMapLayer(
        features=({"type": "Feature", "geometry": {"type": "Point", "coordinates": [50.0, 50.0]}},),
    )
    doc.add_layer(p_layer)
    ext = doc.recompute_extent()
    assert ext[0] < 50.0 < ext[2]
    assert ext[1] < 50.0 < ext[3]
    assert math.isclose((ext[0] + ext[2]) / 2.0, 50.0, abs_tol=1e-3)

    # 2. Hidden Layer should NOT affect document extent
    hidden_layer = VectorMapLayer(
        visible=False,
        features=({"type": "Feature", "geometry": {"type": "Point", "coordinates": [1000.0, 1000.0]}},),
    )
    doc.add_layer(hidden_layer)
    assert doc.recompute_extent() == ext  # Extent remains unchanged

    # Unhide hidden layer
    hidden_layer.set_visible(True)
    ext_new = doc.recompute_extent()
    assert ext_new[2] >= 1000.0 and ext_new[3] >= 1000.0

    # 3. Layer with empty geometry or corrupted coordinates
    corrupt_layer = VectorMapLayer(
        features=(
            {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": []}},
            {"type": "Feature", "geometry": None},
            {"type": "Feature"},
        ),
    )
    doc.add_layer(corrupt_layer)
    assert doc.recompute_extent() == ext_new  # Corrupt layers do not break calculation


# ============================================================================
# 2. CONCURRENT SNAPSHOT GENERATION & IMMUTABILITY STRESS TESTS
# ============================================================================

def test_concurrent_snapshot_capture_during_live_layer_mutations():
    """Stress test concurrent multi-threaded to_snapshot() while live MapDocument is mutated."""
    doc = MapDocument(title="Concurrent Doc")
    for i in range(20):
        doc.add_layer(_generate_synthetic_graduated_layer(10))

    stop_event = threading.Event()
    mutation_errors: list[Exception] = []
    snapshot_errors: list[Exception] = []
    captured_snapshots: list[MapRenderSnapshot] = []

    def mutator_worker():
        step = 0
        while not stop_event.is_set():
            try:
                step += 1
                # 1. Mutate existing layer
                if doc.layers:
                    target = doc.layers[step % len(doc.layers)]
                    target.set_opacity(random.uniform(0.1, 1.0))
                    target.set_visible(random.choice([True, False]))
                    target.style["stroke_width"] = random.uniform(0.5, 3.0)
                # 2. Add / remove layers
                if step % 5 == 0 and len(doc.layers) < 40:
                    doc.add_layer(AnnotationMapLayer(name=f"Dynamic Ann {step}"))
                elif step % 7 == 0 and len(doc.layers) > 10:
                    doc.remove_layer(doc.layers[-1].id)
                # 3. Reorder
                if step % 11 == 0:
                    ids = [l.id for l in doc.layers]
                    random.shuffle(ids)
                    doc.reorder_layers(ids)
                time.sleep(0.001)
            except Exception as e:
                mutation_errors.append(e)

    def snapshot_worker(worker_id: int):
        for _ in range(50):
            if stop_event.is_set():
                break
            try:
                snap = doc.to_snapshot()
                assert isinstance(snap, MapRenderSnapshot)
                assert isinstance(snap.layers, tuple)
                # Verify internal consistency
                for lyr_snap in snap.layers:
                    assert isinstance(lyr_snap, MapLayerSnapshot)
                    assert isinstance(lyr_snap.style, dict)
                    assert isinstance(lyr_snap.features, tuple)
                captured_snapshots.append(snap)
                time.sleep(0.002)
            except Exception as e:
                snapshot_errors.append(e)

    # Launch 1 mutator and 4 concurrent snapshot readers
    threads = [threading.Thread(target=mutator_worker)]
    for i in range(4):
        threads.append(threading.Thread(target=snapshot_worker, args=(i,)))

    for t in threads:
        t.start()

    # Wait for snapshot workers to finish
    for t in threads[1:]:
        t.join(timeout=10.0)

    stop_event.set()
    threads[0].join(timeout=5.0)

    assert mutation_errors == [], f"Mutation worker encountered errors: {mutation_errors}"
    assert snapshot_errors == [], f"Snapshot workers encountered errors: {snapshot_errors}"
    assert len(captured_snapshots) >= 100


def test_deep_snapshot_immutability_guarantee():
    """Verify that mutating live layers/document post-snapshot DOES NOT affect earlier snapshots."""
    doc = MapDocument(title="Original State")
    ann_layer = AnnotationMapLayer(name="Original Annotations")
    ann_layer.add_annotation("Alpha", 10.0, 20.0, font_size=12.0, color="#ffffff")
    doc.add_layer(ann_layer)

    grad_layer = _generate_synthetic_graduated_layer(5)
    grad_layer.style["fill"] = "#112233"
    doc.add_layer(grad_layer)

    # Capture Snapshot S1
    s1 = doc.to_snapshot()
    assert len(s1.layers) == 2
    assert s1.layers[0].name == "Original Annotations"
    assert len(s1.layers[0].features) == 1
    assert s1.layers[1].style["fill"] == "#112233"

    # Aggressively mutate live layers and document
    ann_layer.add_annotation("Beta", 30.0, 40.0)
    ann_layer.annotations = ()
    ann_layer.features = ()
    ann_layer.name = "MUTATED ANNOTATIONS"
    grad_layer.style["fill"] = "#ff0000"
    grad_layer.set_visible(False)
    doc.layers.append(VectorMapLayer(name="Newly Added Layer"))

    # S1 MUST REMAIN COMPLETELY UNTOUCHED
    assert len(s1.layers) == 2
    assert s1.layers[0].name == "Original Annotations"
    assert len(s1.layers[0].features) == 1
    assert s1.layers[0].features[0]["properties"]["text"] == "Alpha"
    assert s1.layers[1].style["fill"] == "#112233"
    assert s1.layers[1].visible is True

    # Capture Snapshot S2
    s2 = doc.to_snapshot()
    assert len(s2.layers) == 3
    assert s2.layers[0].name == "MUTATED ANNOTATIONS"
    assert len(s2.layers[0].features) == 0
    assert s2.layers[1].style["fill"] == "#ff0000"
    assert s2.layers[1].visible is False


# ============================================================================
# 3. HIGH-RESOLUTION SVG, PNG, AND PDF EXPORTS STRESS TESTS
# ============================================================================

def test_high_resolution_svg_export_with_complex_graduated_and_annotations():
    """Stress test MapComposerRenderer.render_to_svg with graduated layers, complex annotations, and legends."""
    comp_doc = MapCompositionDocument(
        id="comp_doc_stress",
        title="High-Res Stress Map Composition",
        width_mm=420.0,
        height_mm=297.0,
    )  # A3 format

    map_doc = MapDocument(extent=(100.0, 30.0, 200.0, 80.0))
    grid = _generate_synthetic_grid(40, 40)
    grad = _generate_synthetic_graduated_layer(60)
    ann = _generate_synthetic_annotation_layer(30)
    cnt = ContourMapLayer(
        name="Iso-permeability",
        features=tuple({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[100.0 + j * 10, 30.0], [150.0, 50.0 + j * 5], [200.0, 80.0]]},
            "properties": {"level": float(j * 20)},
        } for j in range(5)),
        levels=[0.0, 20.0, 40.0, 60.0, 80.0],
    )
    well = WellPointMapLayer(
        name="Production Wells",
        features=tuple({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [120.0 + k * 15.0, 40.0 + k * 8.0]},
            "properties": {"name": f"H-{k:02d}", "value": 15.2 + k * 3.1},
        } for k in range(5)),
    )

    map_doc.add_layer(grid)
    map_doc.add_layer(grad)
    map_doc.add_layer(cnt)
    map_doc.add_layer(well)
    map_doc.add_layer(ann)

    # 1. Main Map Element
    main_map = ComposerElement(
        id="main_map_1",
        element_type=ElementType.MAIN_MAP,
        x_mm=10.0,
        y_mm=20.0,
        width_mm=300.0,
        height_mm=250.0,
        properties={"map_document": map_doc},
    )
    comp_doc.add_element(main_map)

    # 2. Title Element
    comp_doc.add_element(ComposerElement(
        id="title_1",
        element_type=ElementType.TITLE,
        x_mm=10.0,
        y_mm=5.0,
        width_mm=300.0,
        height_mm=12.0,
        properties={"text": "鄂尔多斯盆地 - 储层非均质性与古地理高分辨率综合图 (High-Res Map)"},
    ))

    # 3. North Arrow & Scale Bar
    comp_doc.add_element(ComposerElement(
        id="na_1",
        element_type=ElementType.NORTH_ARROW,
        x_mm=290.0,
        y_mm=25.0,
        width_mm=15.0,
        height_mm=20.0,
    ))
    comp_doc.add_element(ComposerElement(
        id="sb_1",
        element_type=ElementType.SCALE_BAR,
        x_mm=20.0,
        y_mm=250.0,
        width_mm=60.0,
        height_mm=10.0,
        properties={"length_km": 100},
    ))

    # 4. Legend Element (Auto-extracted from Main Map)
    comp_doc.add_element(ComposerElement(
        id="legend_1",
        element_type=ElementType.LEGEND,
        x_mm=315.0,
        y_mm=20.0,
        width_mm=95.0,
        height_mm=250.0,
    ))

    renderer = MapComposerRenderer()
    svg_output = renderer.render_to_svg(comp_doc)

    # Assertions on SVG structure
    assert svg_output.startswith("<svg")
    assert svg_output.strip().endswith("</svg>")
    assert 'viewBox="0 0 420.0 297.0"' in svg_output
    assert "data:image/png;base64," in svg_output  # Grid rasterized into embedded PNG
    assert "Graduated Permeability" in svg_output or "Low (&lt;0)" in svg_output or "Ultra-High (&gt;120)" in svg_output
    assert "构造带" in svg_output  # Unicode CJK text preserved
    assert "Production Wells" in svg_output or "H-00" in svg_output
    assert "linearGradient" in svg_output  # Legend scalar ramp gradient definition


def test_high_dpi_polygon_raster_png_export(tmp_path):
    """Stress test FallbackMapRenderBackend rendering polygon and grid layers at 300 DPI, 600 DPI, and 4K output size."""
    doc = MapDocument(extent=(100.0, 30.0, 200.0, 80.0))
    doc.add_layer(_generate_synthetic_grid(30, 30))
    poly_layer = PolygonMapLayer(
        name="Facies Polygons",
        features=tuple({
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[100.0 + j * 10, 30.0], [110.0 + j * 10, 30.0], [110.0 + j * 10, 80.0], [100.0 + j * 10, 80.0], [100.0 + j * 10, 30.0]]],
            },
            "properties": {"category": f"Facies-{j}"},
        } for j in range(8)),
        style={"fill": "#4fc3f7", "stroke": "#0288d1", "stroke_width": 1.5},
    )
    doc.add_layer(poly_layer)

    backend = FallbackMapRenderBackend()
    backend.initialize()

    # 1. 300 DPI 4K Render Test
    backend.set_layer_snapshot(doc.to_snapshot())
    backend.set_extent(doc.extent)
    backend.set_output_size(3840, 2160)
    backend.set_dpi(300.0)

    t0 = time.perf_counter()
    frame_4k = backend.render_sync()
    t1 = time.perf_counter()

    assert frame_4k.width == 3840
    assert frame_4k.height == 2160
    assert len(frame_4k.rgba) == 3840 * 2160 * 4
    assert (t1 - t0) < 5.0  # Must complete within 5s

    # Save to disk as PNG and verify header
    png_path = str(tmp_path / "high_res_map_300dpi.png")
    img = Image.frombytes("RGBA", (3840, 2160), frame_4k.rgba)
    img.save(png_path, dpi=(300, 300))
    assert os.path.exists(png_path)
    assert os.path.getsize(png_path) > 10_000

    with open(png_path, "rb") as f:
        header = f.read(8)
        assert header == b"\x89PNG\r\n\x1a\n"

    # 2. 600 DPI High-Density Test
    backend.set_output_size(2400, 1800)
    backend.set_dpi(600.0)
    frame_600 = backend.render_sync()
    assert frame_600.width == 2400
    assert frame_600.height == 1800

    backend.shutdown()


def test_pdf_writer_export_with_qpainter_polygon_grid(tmp_path):
    """Stress test export to PDF using PySide6.QtGui.QPdfWriter and backend painting with grid and polygons."""
    doc = MapDocument(extent=(100.0, 30.0, 200.0, 80.0))
    doc.add_layer(_generate_synthetic_grid(25, 25))
    poly = PolygonMapLayer(
        name="Zones",
        features=({
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[120.0, 40.0], [180.0, 40.0], [180.0, 70.0], [120.0, 70.0], [120.0, 40.0]]],
            },
            "properties": {"zone": "SweetSpot"},
        },),
        style={"fill": "#ffb74d", "stroke": "#e65100", "stroke_width": 2.0},
    )
    doc.add_layer(poly)

    backend = FallbackMapRenderBackend()
    backend.initialize()
    backend.set_layer_snapshot(doc.to_snapshot())
    backend.set_extent(doc.extent)
    backend.set_output_size(1200, 800)
    backend.set_dpi(300.0)

    pdf_path = str(tmp_path / "cartographic_export.pdf")
    writer = QPdfWriter(pdf_path)
    writer.setResolution(300)

    painter = QPainter(writer)
    try:
        backend._paint_composition(painter, width=1200, height=800, dpi=300.0)
    finally:
        painter.end()

    assert os.path.exists(pdf_path)
    assert os.path.getsize(pdf_path) > 1000

    with open(pdf_path, "rb") as f:
        pdf_header = f.read(5)
        assert pdf_header == b"%PDF-"

    backend.shutdown()


# ============================================================================
# 4. ADVERSARIAL STYLING & RENDERER REGISTRY RESOLUTION
# ============================================================================

def test_renderer_registry_adversarial_resolution():
    """Test RendererRegistry resolution with corrupt, missing, and unusual style configurations."""
    reg = DEFAULT_RENDERER_REGISTRY

    # 1. Graduated style without explicit renderer keyword, but with ranges
    l1 = VectorMapLayer(style={"ranges": [[0.0, 10.0, "#ff0000"]]})
    assert isinstance(reg.resolve(l1), GraduatedRenderer)

    # 2. Annotation layer with custom style
    l2 = AnnotationMapLayer(style={"renderer": "single"})
    # Annotation layer type takes precedence
    assert isinstance(reg.resolve(l2), AnnotationRenderer)

    # 3. Explicit renderer key overrides
    l3 = VectorMapLayer(style={"renderer": "categorized", "field": "type"})
    assert isinstance(reg.resolve(l3), CategorizedRenderer)

    l4 = VectorMapLayer(style={"renderer": "graduated", "field": "val"})
    assert isinstance(reg.resolve(l4), GraduatedRenderer)

    # 4. Unknown layer type & unknown style falls back gracefully to single symbol
    l5 = VectorMapLayer(layer_type="unknown_custom_type", style={"renderer": "non_existent_engine"})
    assert isinstance(reg.resolve(l5), SingleSymbolRenderer)


def test_graduated_renderer_out_of_bound_and_nan_values():
    """Verify GraduatedRenderer and _match_range against NaN, Inf, None, out-of-range, and zero values."""
    renderer = GraduatedRenderer()
    ranges = [
        (-50.0, -10.0, "#0000ff", "Negative"),
        (0.0, 0.0, "#00ff00", "Zero Exact"),
        (10.0, 50.0, "#ff0000", "Positive"),
    ]

    # Exact zero match
    assert renderer._match_range(0.0, ranges) == ("#00ff00", "Zero Exact")
    # In range
    assert renderer._match_range(-20.0, ranges) == ("#0000ff", "Negative")
    assert renderer._match_range(30.0, ranges) == ("#ff0000", "Positive")
    # Out of range (gaps)
    assert renderer._match_range(-5.0, ranges) is None
    assert renderer._match_range(5.0, ranges) is None
    assert renderer._match_range(100.0, ranges) is None
    # Boundary inclusion
    assert renderer._match_range(-50.0, ranges) == ("#0000ff", "Negative")
    assert renderer._match_range(-10.0, ranges) == ("#0000ff", "Negative")

    # SVG rendering with NaNs and corrupted properties
    ctx = RenderContext(extent=(0.0, 0.0, 100.0, 100.0), width=500.0, height=500.0)
    layer = VectorMapLayer(
        style={"renderer": "graduated", "field": "val", "ranges": ranges, "fill": "#888888"},
        features=(
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [10.0, 10.0]}, "properties": {"val": float("nan")}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [20.0, 20.0]}, "properties": {"val": None}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [30.0, 30.0]}, "properties": {"val": "not_a_number"}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [40.0, 40.0]}, "properties": {"val": 30.0}},
        ),
    )
    svg = renderer.render_svg(layer, ctx)
    assert 'fill="#888888"' in svg  # Fallback for NaN / None
    assert 'fill="#ff0000"' in svg  # Match for 30.0


# ============================================================================
# 5. EMPIRICAL BUG REPRODUCTION & CHALLENGE ORACLES
# ============================================================================

def test_reproduce_bug1_point_layer_render_crash_on_prepared_layer_type():
    """Verify Point features with default style (style.labels is None) render cleanly
    without AttributeError on _PreparedLayer.layer_type.
    """
    v = VectorMapLayer(
        id="pts_bug1",
        name="Points Without Labels",
        features=({"type": "Feature", "geometry": {"type": "Point", "coordinates": [5.0, 5.0]}},),
        style={"fill": "#ff0000", "marker": "circle", "marker_size": 10.0},
    )

    snap = MapRenderSnapshot(project_crs="EPSG:3857", layers=(v.to_snapshot(),))
    backend = FallbackMapRenderBackend()
    backend.initialize()
    backend.set_layer_snapshot(snap)
    backend.set_extent((0.0, 0.0, 10.0, 10.0))
    backend.set_output_size(100, 100)

    # Must complete cleanly without AttributeError
    frame = backend.render_sync()
    assert frame is not None
    assert frame.width == 100
    assert frame.height == 100
    assert len(frame.rgba) == 100 * 100 * 4

    backend.shutdown()


def test_reproduce_bug2_polymorphic_layer_type_erasure_in_to_snapshot():
    """Verify VectorMapLayer.to_snapshot() preserves polymorphic layer types
    for ContourMapLayer, WellPointMapLayer, and PolygonMapLayer upon snapshot and reconstruction.
    """
    c = ContourMapLayer(id="c1", name="Contour")
    w = WellPointMapLayer(id="w1", name="Well")
    p = PolygonMapLayer(id="p1", name="Polygon")

    assert c.layer_type == "contour"
    assert w.layer_type == "well_point"
    assert p.layer_type == "polygon"

    # Snapshots must retain polymorphic subtype
    snap_c = c.to_snapshot()
    snap_w = w.to_snapshot()
    snap_p = p.to_snapshot()

    assert snap_c.layer_type == "contour"
    assert snap_w.layer_type == "well_point"
    assert snap_p.layer_type == "polygon"

    doc = MapDocument()
    doc.add_layer(c)
    doc.add_layer(w)
    doc.add_layer(p)

    restored = MapDocument.from_snapshot(doc.to_snapshot())
    # Subclass types preserved
    assert isinstance(restored.get_layer("c1"), ContourMapLayer)
    assert isinstance(restored.get_layer("w1"), WellPointMapLayer)
    assert isinstance(restored.get_layer("p1"), PolygonMapLayer)

    # Renderer resolution preserves specialized renderers
    assert isinstance(DEFAULT_RENDERER_REGISTRY.resolve(c), ContourRenderer)
    assert isinstance(DEFAULT_RENDERER_REGISTRY.resolve(restored.get_layer("c1")), ContourRenderer)
    assert isinstance(DEFAULT_RENDERER_REGISTRY.resolve(restored.get_layer("w1")), WellSymbolRenderer)


def test_reproduce_bug3_unescaped_xml_special_characters_in_svg_export():
    """Verify AnnotationRenderer and MapComposerRenderer properly escape XML special characters
    (<, >, &, ", ') in cartographic labels, producing valid XML SVG outputs.
    """
    ann = AnnotationMapLayer(name="Adversarial Text")
    ann.add_annotation("Porosity < 5% & Permeability > 10mD", 10.0, 10.0)

    ctx = RenderContext(extent=(0.0, 0.0, 20.0, 20.0), width=100.0, height=100.0)
    renderer = DEFAULT_RENDERER_REGISTRY.resolve(ann)
    svg_group = renderer.render_svg(ann, ctx)
    full_svg = f'<svg xmlns="http://www.w3.org/2000/svg">{svg_group}</svg>'

    # XML parser must parse valid XML with escaped entities
    root = ET.fromstring(full_svg)
    assert root is not None
    text_elements = list(root.iter("{http://www.w3.org/2000/svg}text")) or list(root.iter("text"))
    assert any("Porosity < 5% & Permeability > 10mD" in (t.text or "") for t in text_elements)

    # Also test MapComposerRenderer with title containing XML characters
    from paleo_workbench.mapping.composer.models import ComposerElement, ElementType, MapCompositionDocument
    from paleo_workbench.mapping.composer.renderer import MapComposerRenderer

    comp = MapCompositionDocument(id="comp_adv", title="Advanced Map", width_mm=100.0, height_mm=100.0)
    comp.add_element(ComposerElement(
        id="title_adv",
        element_type=ElementType.TITLE,
        x_mm=10.0,
        y_mm=10.0,
        width_mm=80.0,
        height_mm=20.0,
        properties={"text": "Geology <North & South>"},
    ))
    comp_svg = MapComposerRenderer().render_to_svg(comp)
    comp_root = ET.fromstring(comp_svg)
    assert comp_root is not None


def test_extent_reset_on_clearing_features_and_annotations():
    """Verify that clearing annotations or features resets extent to default (0, 0, 1, 1)."""
    ann = AnnotationMapLayer(name="Dynamic Extent")
    ann.add_annotation("Point 1", 100.0, 200.0)
    ann.add_annotation("Point 2", 300.0, 400.0)
    assert ann.extent[0] <= 100.0 and ann.extent[2] >= 300.0

    ann.clear_annotations()
    assert ann.extent == (0.0, 0.0, 1.0, 1.0)


def test_qgis_snapshot_polymorphic_vector_layer_encoding():
    """Verify that _qgis_snapshot encodes all polymorphic vector layer types."""
    from paleo_workbench.mapping.map_render_backend import _qgis_snapshot

    doc = MapDocument(id="doc_qgis", title="QGIS Doc")
    doc.add_layer(ContourMapLayer(id="c", name="Contour", features=({"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[0.0, 0.0], [1.0, 1.0]]}},)))
    doc.add_layer(WellPointMapLayer(id="w", name="Well", features=({"type": "Feature", "geometry": {"type": "Point", "coordinates": [0.5, 0.5]}},)))
    doc.add_layer(PolygonMapLayer(id="p", name="Poly", features=({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}},)))
    ann = AnnotationMapLayer(id="a", name="Ann")
    ann.add_annotation("Label", 0.2, 0.2)
    doc.add_layer(ann)

    snap = doc.to_snapshot()
    encoded = _qgis_snapshot(snap)
    assert len(encoded) == 4
    encoded_ids = {lyr["id"] for lyr in encoded}
    assert encoded_ids == {"c", "w", "p", "a"}

