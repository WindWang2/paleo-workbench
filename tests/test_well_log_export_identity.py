"""Tests for Native QPainter Well Log, 1:1 Export & Cross-Well LOD (Issues #15, #17)."""
import os
import tempfile
import numpy as np
import pytest
from PySide6.QtCore import QSize, QRectF
from PySide6.QtGui import QPainter, QPixmap

from geoviz_well_log.renderer.canvas import WellLogCanvas
from geoviz_well_log.export_qpainter import export_svg, export_pdf, export_png
from geoviz_cross_well.correlation_layer import CorrelationLayer, depth_range_clip_filter, douglas_peucker_simplify


def test_well_log_canvas_paint_all_and_exports(qtbot):
    canvas = WellLogCanvas()
    canvas.resize(400, 800)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        svg_path = os.path.join(tmpdir, "output.svg")
        pdf_path = os.path.join(tmpdir, "output.pdf")
        png_path = os.path.join(tmpdir, "output.png")
        
        export_svg(canvas, svg_path)
        export_pdf(canvas, pdf_path)
        export_png(canvas, png_path)
        
        assert os.path.exists(svg_path) and os.path.getsize(svg_path) > 0
        assert os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0
        assert os.path.exists(png_path) and os.path.getsize(png_path) > 0


def test_depth_range_clip_filter():
    # Tie lines with (min_depth, max_depth)
    ties = [
        {"id": "tie1", "top_depth": 1000.0, "bottom_depth": 1100.0},  # In range (1000-1500)
        {"id": "tie2", "top_depth": 500.0, "bottom_depth": 800.0},    # Offscreen above
        {"id": "tie3", "top_depth": 1800.0, "bottom_depth": 2000.0},  # Offscreen below
        {"id": "tie4", "top_depth": 1400.0, "bottom_depth": 1600.0},  # Partially overlaps
    ]
    
    visible = depth_range_clip_filter(ties, vp_top_depth=1000.0, vp_bottom_depth=1500.0)
    
    visible_ids = {t["id"] for t in visible}
    assert "tie1" in visible_ids
    assert "tie4" in visible_ids
    assert "tie2" not in visible_ids
    assert "tie3" not in visible_ids


def test_douglas_peucker_simplify():
    # Create a dense collinear polyline with slight jitter < 0.5px
    x = np.linspace(0, 100, 1000)
    y = 2.0 * x + np.sin(x) * 0.1  # jitter amplitude 0.1px (< 0.5px tolerance)
    points = np.column_stack([x, y])
    
    simplified = douglas_peucker_simplify(points, epsilon=0.5)
    
    # 1000 points simplified down to < 50 points (95%+ reduction)
    assert len(simplified) < 50
    assert len(simplified) < len(points)
