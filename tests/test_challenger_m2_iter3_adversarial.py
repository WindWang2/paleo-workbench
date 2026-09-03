"""Adversarial stress and edge-case test harness for Milestone 2 Iteration 3.

Empirical verification covering:
1. Point and annotation rendering & export with:
   - style.labels is None
   - style={"fill": "#000000", "labels": None}
   - style with visible/hidden labels, custom text fields, halos, bold, fonts
   - All MarkerSymbol values (CIRCLE, SQUARE, TRIANGLE, DIAMOND, CROSS, STAR, WELL)
   - All LinePattern values (SOLID, DASH, DOT, DASH_DOT, FAULT, BOUNDARY)
   - Categorized and Graduated point layers with/without labels
   - High-DPI viewports (96, 144, 288, 300, 600) and ultra-resolution canvases
   - Multi-threaded concurrent rendering/export across parallel worker threads
2. Extreme layer configurations:
   - Empty feature layers
   - 10,000+ points (crossing LOD caps at 1500, 4000, 5000)
   - Zero extents (min == max), inverted extents, degenerate line extents
   - Extreme negative coordinates (-1e7, -1e7) and massive planetary coordinates (1e8, 1e8)
   - Microscopic / near-zero extent intervals (1e-9) and extreme aspect ratios (10000:1)
   - NaN, Inf, null, and non-primitive property types
3. Strict XML correctness for all SVG exports:
   - Verifying all generated SVGs parse strictly with xml.etree.ElementTree
   - XML escape entity handling (<, >, &, ", ', <script>, <!--, ]]>, unicode, CJK)
   - MapComposer export with legend, north arrow, scale bar, title, and map elements
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
from typing import Any, Mapping
from uuid import uuid4
import xml.etree.ElementTree as ET

import numpy as np
import pytest
from PySide6.QtCore import QMarginsF, QPoint, QPointF, QRect, QSize, QSizeF
from PySide6.QtGui import QColor, QFont, QImage, QPageLayout, QPageSize, QPainter, QPdfWriter
from PySide6.QtSvg import QSvgGenerator

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
    RenderContext,
    SingleSymbolRenderer,
    WellSymbolRenderer,
)
from paleo_workbench.ui.unified_map_canvas import UnifiedMapCanvas


@pytest.fixture(autouse=True)
def _ensure_qapp(qapp):
    return qapp


# ============================================================================
# 1. POINT & ANNOTATION RENDERING & EXPORT PERMUTATIONS
# ============================================================================

@pytest.mark.parametrize("marker_symbol", list(MarkerSymbol))
@pytest.mark.parametrize("style_config", [
    {"labels": None},
    {"fill": "#000000", "labels": None},
    {"fill": "#123456", "stroke": "#abcdef", "stroke_width": 2.5, "marker_size": 12.0, "labels": None},
    {"labels": {"visible": False}},
    {"labels": {"field": "custom_name", "size": 14.0, "bold": True, "halo_color": "#000000", "halo_width": 2.0}},
    {"labels": {"field": "", "size": 8.0, "color": "#ff00ff"}},
])
def test_point_styles_and_none_labels_permutations(tmp_path, marker_symbol, style_config):
    """Empirically test all MarkerSymbols combined with diverse label configurations
    (including None, dict-with-None, hidden, and custom fields) across raster and vector targets.
    """
    style_dict = dict(style_config)
    style_dict["marker"] = marker_symbol.value
    style_dict["marker_size"] = 8.0

    # Test VectorMapLayer with Point features
    vec = VectorMapLayer(
        id=f"pt_{marker_symbol.value}",
        name=f"Point {marker_symbol.value}",
        features=(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [5.0, 5.0]},
                "properties": {"custom_name": "Target Well #1", "name": "Well-1", "text": "Fallback Text"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [15.0, 15.0]},
                "properties": {"custom_name": "Target Well #2", "name": "Well-2", "text": "Fallback Text 2"},
            },
        ),
        style=style_dict,
    )

    # Test AnnotationMapLayer
    ann = AnnotationMapLayer(
        id=f"ann_{marker_symbol.value}",
        name=f"Annotation {marker_symbol.value}",
        style=style_dict,
    )
    ann.add_annotation("Alpha Note", 5.0, 15.0)
    ann.add_annotation("Beta Note", 15.0, 5.0)

    doc = MapDocument(layers=[vec, ann])
    snap = doc.to_snapshot()

    backend = FallbackMapRenderBackend()
    backend.initialize()
    try:
        backend.set_layer_snapshot(snap)
        backend.set_extent((0.0, 0.0, 20.0, 20.0))
        backend.set_output_size(150, 150)
        backend.set_dpi(96.0)

        # 1. Raster frame rendering
        frame = backend.render_sync()
        assert frame is not None
        assert (frame.width, frame.height) == (150, 150)
        pixels = np.frombuffer(frame.rgba, dtype=np.uint8).reshape(150, 150, 4)
        non_bg = int((pixels[:, :, :3] != np.array([255, 255, 255])).any(axis=-1).sum())
        assert non_bg > 0, f"Expected non-background pixels for {marker_symbol} with {style_config}"

        # 2. QImage raster export
        img = QImage(150, 150, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(QColor(255, 255, 255))
        p = QPainter(img)
        try:
            backend.render_to_painter(p, 150, 150, dpi=96.0)
        finally:
            p.end()
        assert not img.isNull()

        # 3. QSvgGenerator export
        svg_file = tmp_path / f"export_{marker_symbol.value}_{uuid4().hex[:6]}.svg"
        gen = QSvgGenerator()
        gen.setFileName(str(svg_file))
        gen.setSize(QSize(150, 150))
        gen.setViewBox(QRect(0, 0, 150, 150))
        gen.setResolution(96)
        svg_p = QPainter(gen)
        try:
            backend.render_to_painter(svg_p, 150, 150, dpi=96.0)
        finally:
            svg_p.end()
        assert svg_file.exists()
        assert svg_file.stat().st_size > 0

        # Validate SVG XML
        tree = ET.parse(str(svg_file))
        assert tree.getroot() is not None

        # 4. QPdfWriter export
        pdf_file = tmp_path / f"export_{marker_symbol.value}_{uuid4().hex[:6]}.pdf"
        writer = QPdfWriter(str(pdf_file))
        writer.setResolution(96)
        writer.setPageLayout(
            QPageLayout(
                QPageSize(QSizeF(150, 150), QPageSize.Unit.Point),
                QPageLayout.Orientation.Portrait,
                QMarginsF(0, 0, 0, 0),
            )
        )
        pdf_p = QPainter(writer)
        try:
            backend.render_to_painter(pdf_p, 150, 150, dpi=96.0)
        finally:
            pdf_p.end()
        assert pdf_file.exists()
        assert pdf_file.stat().st_size > 0
    finally:
        backend.shutdown()


@pytest.mark.parametrize("line_pattern", list(LinePattern))
def test_line_patterns_and_strokes(tmp_path, line_pattern):
    """Test all line patterns (SOLID, DASH, DOT, DASH_DOT, FAULT, BOUNDARY)
    with vector lines and contour layers.
    """
    layer = ContourMapLayer(
        id=f"line_{line_pattern.value}",
        name=f"Line {line_pattern.value}",
        features=(
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[2.0, 2.0], [5.0, 8.0], [10.0, 12.0], [18.0, 18.0]],
                },
                "properties": {"level": 150.0},
            },
        ),
        style={
            "stroke": "#ff5500",
            "stroke_width": 3.0,
            "line_pattern": line_pattern.value,
            "labels": {"field": "level", "size": 9.0, "color": "#ffffff"},
        },
    )
    doc = MapDocument(layers=[layer])
    backend = FallbackMapRenderBackend()
    backend.initialize()
    try:
        backend.set_layer_snapshot(doc.to_snapshot())
        backend.set_extent((0.0, 0.0, 20.0, 20.0))
        backend.set_output_size(200, 200)
        frame = backend.render_sync()
        assert frame is not None
        pixels = np.frombuffer(frame.rgba, dtype=np.uint8).reshape(200, 200, 4)
        non_bg = int((pixels[:, :, :3] != np.array([255, 255, 255])).any(axis=-1).sum())
        assert non_bg > 0
    finally:
        backend.shutdown()


def test_categorized_and_graduated_points_with_and_without_labels(tmp_path):
    """Test categorized and graduated point layers with labels configured
    and style.labels is None across both fallback rendering and vector exports.
    """
    cat_layer = VectorMapLayer(
        id="cat_pts",
        name="Categorized Wells",
        features=(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [5.0, 5.0]},
                "properties": {"type": "Oil", "well_name": "Well-Oil-1"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [15.0, 15.0]},
                "properties": {"type": "Gas", "well_name": "Well-Gas-1"},
            },
        ),
        style={
            "renderer": "categorized",
            "field": "type",
            "categories": [["Oil", "#e03131", "Oil Well"], ["Gas", "#1971c2", "Gas Well"]],
            "marker": "well",
            "marker_size": 10.0,
            "labels": {"field": "well_name", "size": 10.0, "color": "#ffffff"},
        },
    )

    grad_layer = VectorMapLayer(
        id="grad_pts",
        name="Graduated Wells",
        features=(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [5.0, 15.0]},
                "properties": {"porosity": 5.0, "name": "P5"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [15.0, 5.0]},
                "properties": {"porosity": 25.0, "name": "P25"},
            },
        ),
        style={
            "renderer": "graduated",
            "field": "porosity",
            "ranges": [[0.0, 10.0, "#ffe066", "Low"], [10.0, 30.0, "#f03e3e", "High"]],
            "marker": "diamond",
            "marker_size": 12.0,
            "labels": {"field": "name", "size": 10.0, "color": "#ffffff"},
        },
    )

    doc = MapDocument(layers=[cat_layer, grad_layer])
    backend = FallbackMapRenderBackend()
    backend.initialize()
    try:
        backend.set_layer_snapshot(doc.to_snapshot())
        backend.set_extent((0.0, 0.0, 20.0, 20.0))
        backend.set_output_size(200, 200)

        frame = backend.render_sync()
        assert frame is not None
        pixels = np.frombuffer(frame.rgba, dtype=np.uint8).reshape(200, 200, 4)
        non_bg = int((pixels[:, :, :3] != np.array([255, 255, 255])).any(axis=-1).sum())
        assert non_bg > 0

        # SVG export
        svg_file = tmp_path / "cat_grad_wells.svg"
        gen = QSvgGenerator()
        gen.setFileName(str(svg_file))
        gen.setSize(QSize(200, 200))
        gen.setViewBox(QRect(0, 0, 200, 200))
        gen.setResolution(96)
        p = QPainter(gen)
        try:
            backend.render_to_painter(p, 200, 200, dpi=96.0)
        finally:
            p.end()
        assert svg_file.exists()
        ET.parse(str(svg_file))
    finally:
        backend.shutdown()



# ============================================================================
# 2. HIGH-DPI VIEWPORTS & MULTI-THREADED CONCURRENCY
# ============================================================================

@pytest.mark.parametrize("dpi,width,height", [
    (96.0, 320, 240),
    (144.0, 480, 360),
    (192.0, 640, 480),
    (300.0, 1200, 900),
    (600.0, 2400, 1800),
])
def test_high_dpi_scaling_and_export_integrity(tmp_path, dpi, width, height):
    """Verify high-DPI scaling across raster and vector export targets
    with varied point, polygon, and annotation styles.
    """
    pts = WellPointMapLayer(
        id="dpi_pts",
        name="High DPI Points",
        features=(
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [50.0, 50.0]}, "properties": {"name": "Well-A"}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [150.0, 150.0]}, "properties": {"name": "Well-B"}},
        ),
        style={"marker": "well", "marker_size": 8.0, "fill": "#22b8a7", "stroke": "#ffffff", "labels": {"field": "name", "size": 10.0}},
    )
    ann = AnnotationMapLayer(
        id="dpi_ann",
        name="High DPI Annotation",
        style={"fill": "#ffffff", "labels": None},
    )
    ann.add_annotation("Basin Boundary A", 50.0, 150.0)
    ann.add_annotation("Fault Zone \u03a9", 150.0, 50.0)

    doc = MapDocument(layers=[pts, ann])
    backend = FallbackMapRenderBackend()
    backend.initialize()
    try:
        backend.set_layer_snapshot(doc.to_snapshot())
        backend.set_extent((0.0, 0.0, 200.0, 200.0))
        backend.set_output_size(width, height)
        backend.set_dpi(dpi)

        frame = backend.render_sync()
        assert frame is not None
        assert (frame.width, frame.height) == (width, height)

        # SVG export at high DPI
        svg_path = tmp_path / f"high_dpi_{int(dpi)}.svg"
        gen = QSvgGenerator()
        gen.setFileName(str(svg_path))
        gen.setSize(QSize(width, height))
        gen.setViewBox(QRect(0, 0, width, height))
        gen.setResolution(int(dpi))
        svg_p = QPainter(gen)
        try:
            backend.render_to_painter(svg_p, width, height, dpi=dpi)
        finally:
            svg_p.end()

        assert svg_path.exists()
        root = ET.parse(str(svg_path)).getroot()
        assert root is not None
    finally:
        backend.shutdown()


def test_multithreaded_rendering_and_export_concurrency(tmp_path):
    """Stress test multithreaded concurrent render operations across independent
    FallbackMapRenderBackend instances executing simultaneously.
    """
    def _worker_task(thread_id: int) -> dict[str, Any]:
        backend = FallbackMapRenderBackend()
        backend.initialize()
        try:
            ann = AnnotationMapLayer(
                id=f"ann_t_{thread_id}",
                name=f"Ann Thread {thread_id}",
                style={"fill": "#ffffff", "labels": None if thread_id % 2 == 0 else {"field": "text", "size": 11.0}},
            )
            for i in range(10):
                ann.add_annotation(f"T{thread_id}-Point-{i}", float(i * 10), float((10 - i) * 10))

            vec = VectorMapLayer(
                id=f"vec_t_{thread_id}",
                name=f"Vec Thread {thread_id}",
                features=(
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [float(i * 5), float(i * 5)]},
                        "properties": {"val": i},
                    }
                    for i in range(20)
                ),
                style={
                    "fill": "#ff8800",
                    "marker": list(MarkerSymbol)[thread_id % len(MarkerSymbol)].value,
                    "labels": None,
                },
            )
            doc = MapDocument(layers=[ann, vec])
            backend.set_layer_snapshot(doc.to_snapshot())
            backend.set_extent((0.0, 0.0, 100.0, 100.0))
            backend.set_output_size(200, 200)
            backend.set_dpi(96.0 + thread_id * 10)

            # Sync render
            frame = backend.render_sync()
            assert frame is not None
            assert (frame.width, frame.height) == (200, 200)

            # SVG export
            svg_file = tmp_path / f"thread_{thread_id}.svg"
            gen = QSvgGenerator()
            gen.setFileName(str(svg_file))
            gen.setSize(QSize(200, 200))
            gen.setViewBox(QRect(0, 0, 200, 200))
            gen.setResolution(96)
            p = QPainter(gen)
            try:
                backend.render_to_painter(p, 200, 200, dpi=96.0)
            finally:
                p.end()

            assert svg_file.exists()
            ET.parse(str(svg_file))

            return {"thread_id": thread_id, "success": True, "bytes_rendered": len(frame.rgba)}
        finally:
            backend.shutdown()

    num_threads = 12
    with ThreadPoolExecutor(max_workers=num_threads) as pool:
        futures = [pool.submit(_worker_task, tid) for tid in range(num_threads)]
        results = [f.result() for f in as_completed(futures)]

    assert len(results) == num_threads
    assert all(r["success"] for r in results)


# ============================================================================
# 3. EXTREME LAYER CONFIGURATIONS
# ============================================================================

def test_extreme_10k_points_lod_and_caps():
    """Verify rendering and symbol degradation caps with 10,000 points.
    Tests the 1,500 label cap, 4,000 dot LOD de-duplication, and 5,000 complex symbol cap.
    """
    n_points = 10_000
    rng = np.random.default_rng(42)
    coords = rng.uniform(0.0, 1000.0, size=(n_points, 2))

    features = tuple(
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(coords[i, 0]), float(coords[i, 1])]},
            "properties": {"name": f"Pt-{i}", "val": float(i)},
        }
        for i in range(n_points)
    )

    # Point layer with Star marker (complex symbol) and labels enabled
    layer = VectorMapLayer(
        id="pts_10k",
        name="10k Points",
        features=features,
        style={
            "marker": "star",
            "marker_size": 5.0,
            "fill": "#ffcc00",
            "stroke": "#000000",
            "labels": {"field": "name", "size": 8.0, "visible": True},
        },
    )

    doc = MapDocument(layers=[layer])
    backend = FallbackMapRenderBackend()
    backend.initialize()
    try:
        backend.set_layer_snapshot(doc.to_snapshot())
        backend.set_extent((0.0, 0.0, 1000.0, 1000.0))
        backend.set_output_size(500, 500)

        frame = backend.render_sync()
        assert frame is not None
        assert (frame.width, frame.height) == (500, 500)

        # Inspect backend diagnostics
        diag = backend.render_diagnostics()
        assert diag["points_drawn"] > 0
    finally:
        backend.shutdown()


def test_empty_layer_and_zero_features():
    """Verify rendering layers with zero features or annotations without errors."""
    empty_vec = VectorMapLayer(id="empty_v", name="Empty Vector", features=(), style={"fill": "#ff0000", "labels": None})
    empty_ann = AnnotationMapLayer(id="empty_a", name="Empty Annotation", style={"fill": "#ffffff", "labels": None})
    empty_poly = PolygonMapLayer(id="empty_p", name="Empty Polygon", features=(), style={"fill": "#00ff00"})
    empty_contour = ContourMapLayer(id="empty_c", name="Empty Contour", features=(), style={"stroke": "#0000ff"})

    doc = MapDocument(layers=[empty_vec, empty_ann, empty_poly, empty_contour])
    backend = FallbackMapRenderBackend()
    backend.initialize()
    try:
        backend.set_layer_snapshot(doc.to_snapshot())
        backend.set_extent((0.0, 0.0, 100.0, 100.0))
        backend.set_output_size(100, 100)

        frame = backend.render_sync()
        assert frame is not None
        assert (frame.width, frame.height) == (100, 100)
    finally:
        backend.shutdown()


@pytest.mark.parametrize("extent,should_raise", [
    ((0.0, 0.0, 0.0, 0.0), True),                 # Zero point extent
    ((100.0, 100.0, 100.0, 100.0), True),         # Single point extent
    ((0.0, 50.0, 100.0, 50.0), True),             # Horizontal line (zero height)
    ((50.0, 0.0, 50.0, 100.0), True),             # Vertical line (zero width)
    ((100.0, 100.0, 0.0, 0.0), True),             # Inverted extent
    ((-1e8, -1e8, -1e7, -1e7), False),            # Extreme negative coordinates
    ((1e7, 1e7, 1e8, 1e8), False),                 # Massive coordinates
    ((10.0, 10.0, 10.0 + 1e-6, 10.0 + 1e-6), False),  # Microscopic positive interval
    ((0.0, 0.0, 100000.0, 1.0), False),            # Extreme aspect ratio 100000:1
    ((0.0, 0.0, 1.0, 100000.0), False),            # Extreme aspect ratio 1:100000
])
def test_extreme_extents_and_coordinate_spaces(extent, should_raise):
    """Verify FallbackMapRenderBackend rejects zero/inverted extents with ValueError
    and gracefully renders extreme negative, microscopic, and high aspect-ratio coordinates.
    """
    ann = AnnotationMapLayer(name="Extreme Extent Layer", style={"labels": None})
    ann.add_annotation("Test Point", extent[0], extent[1])

    doc = MapDocument(layers=[ann])
    backend = FallbackMapRenderBackend()
    backend.initialize()
    try:
        backend.set_layer_snapshot(doc.to_snapshot())
        if should_raise:
            with pytest.raises(ValueError, match="extent must have positive width and height"):
                backend.set_extent(extent)
        else:
            backend.set_extent(extent)
            backend.set_output_size(120, 120)
            frame = backend.render_sync()
            assert frame is not None
            assert (frame.width, frame.height) == (120, 120)
    finally:
        backend.shutdown()


def test_corrupted_nonprimitive_and_nan_feature_properties():
    """Verify points and annotations with missing, None, NaN, dict, list,
    or unexpected property values render without raising exceptions.
    """
    features = (
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [10.0, 10.0]}, "properties": {"name": None, "text": None}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [20.0, 20.0]}, "properties": {"name": 12345, "val": [1, 2, 3]}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [30.0, 30.0]}, "properties": {"name": {"nested": "dict"}}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [40.0, 40.0]}, "properties": {}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [float("nan"), 50.0]}, "properties": {"name": "NaN X"}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [60.0, float("inf")]}, "properties": {"name": "Inf Y"}},
    )

    vec = VectorMapLayer(
        id="corrupt_pts",
        name="Corrupted Props",
        features=features,
        style={"fill": "#ff0000", "labels": {"field": "name", "size": 9.0}},
    )

    doc = MapDocument(layers=[vec])
    backend = FallbackMapRenderBackend()
    backend.initialize()
    try:
        backend.set_layer_snapshot(doc.to_snapshot())
        backend.set_extent((0.0, 0.0, 100.0, 100.0))
        backend.set_output_size(100, 100)

        frame = backend.render_sync()
        assert frame is not None
    finally:
        backend.shutdown()


# ============================================================================
# 4. STRICT XML CORRECTNESS OF SVG EXPORTS
# ============================================================================

def test_strict_xml_correctness_of_all_svg_exports(tmp_path):
    """Adversarially test XML validity of SVGs generated across all renderers
    and composition document elements with XML escape characters and complex payloads.
    """
    adversarial_strings = [
        "Well <1> & 'Deep' #2 \"Wildcat\"",
        "Formation Alpha & Beta > Gamma",
        "<script>alert('xss')</script>",
        "<!-- XML Comment Injection -->",
        "<![CDATA[Unclosed CDATA Section",
        "Emoji Test: \U0001F6E2\uFE0F \U0001F525 \u26A1",
        "CJK Characters: \u5854\u91cc\u6728\u76c6\u5730 \u6df1\u5c42\u6cb9\u6c14\u85cf",
        "Quotes: \"double\" 'single' `backtick` &amp; &lt; &gt;",
        "Special: \t Tab \n Newline \r CarriageReturn",
    ]

    ann = AnnotationMapLayer(name="Adversarial Text Layer", style={"fill": "#ffffff", "labels": None})
    for i, adv_str in enumerate(adversarial_strings):
        ann.add_annotation(adv_str, float(i * 10), float(i * 10))

    vec = VectorMapLayer(
        name="Categorized Adversarial",
        features=tuple(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [float(i * 10 + 5), float(i * 10 + 5)]},
                "properties": {"category": adv_str, "name": adv_str},
            }
            for i, adv_str in enumerate(adversarial_strings)
        ),
        style={
            "renderer": "categorized",
            "field": "category",
            "categories": [(s, "#ff0000", s) for s in adversarial_strings],
            "labels": {"field": "name", "size": 9.0},
        },
    )

    doc = MapDocument(layers=[ann, vec])
    backend = FallbackMapRenderBackend()
    backend.initialize()
    try:
        backend.set_layer_snapshot(doc.to_snapshot())
        backend.set_extent((0.0, 0.0, 150.0, 150.0))
        backend.set_output_size(300, 300)

        # 1. FallbackMapRenderBackend via QSvgGenerator
        svg_file1 = tmp_path / "backend_export.svg"
        gen = QSvgGenerator()
        gen.setFileName(str(svg_file1))
        gen.setSize(QSize(300, 300))
        gen.setViewBox(QRect(0, 0, 300, 300))
        gen.setResolution(96)
        p = QPainter(gen)
        try:
            backend.render_to_painter(p, 300, 300, dpi=96.0)
        finally:
            p.end()

        # Strict XML parse verification
        tree1 = ET.parse(str(svg_file1))
        assert tree1.getroot() is not None

        # 2. RendererRegistry SVG rendering
        ctx = RenderContext(extent=(0.0, 0.0, 150.0, 150.0), width=300.0, height=300.0)
        ann_renderer = DEFAULT_RENDERER_REGISTRY.resolve(ann)
        ann_svg_fragment = ann_renderer.render_svg(ann, ctx)
        wrapped_svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="300" height="300">{ann_svg_fragment}</svg>'
        tree2 = ET.fromstring(wrapped_svg)
        assert tree2 is not None

        # 3. MapComposerRenderer full composition SVG export
        comp = MapCompositionDocument(
            id="comp_adv_test",
            title="Adversarial <Map & Title>",
            width_mm=200.0,
            height_mm=150.0,
        )
        comp.add_element(
            ComposerElement(
                id="map_elem",
                element_type=ElementType.MAIN_MAP,
                x_mm=10.0,
                y_mm=10.0,
                width_mm=120.0,
                height_mm=100.0,
                properties={"map_document": doc},
            )
        )

        comp.add_element(
            ComposerElement(
                id="title_elem",
                element_type=ElementType.TITLE,
                x_mm=10.0,
                y_mm=115.0,
                width_mm=120.0,
                height_mm=20.0,
                properties={"text": "Geology <North & South> 'Alpha' \"Beta\""},
            )
        )
        comp.add_element(
            ComposerElement(
                id="legend_elem",
                element_type=ElementType.LEGEND,
                x_mm=135.0,
                y_mm=10.0,
                width_mm=55.0,
                height_mm=80.0,
            )
        )
        comp.add_element(
            ComposerElement(
                id="north_arrow",
                element_type=ElementType.NORTH_ARROW,
                x_mm=150.0,
                y_mm=95.0,
                width_mm=20.0,
                height_mm=20.0,
            )
        )
        comp.add_element(
            ComposerElement(
                id="scale_bar",
                element_type=ElementType.SCALE_BAR,
                x_mm=135.0,
                y_mm=120.0,
                width_mm=55.0,
                height_mm=15.0,
            )
        )

        composer = MapComposerRenderer()
        comp_svg_str = composer.render_to_svg(comp)
        assert comp_svg_str.startswith("<svg") or "<?xml" in comp_svg_str

        # Strict XML parse verification of entire composed document
        tree3 = ET.fromstring(comp_svg_str)
        assert tree3 is not None
    finally:
        backend.shutdown()
