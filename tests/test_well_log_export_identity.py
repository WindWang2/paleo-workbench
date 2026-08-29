"""Tests for Native QPainter Well Log 1:1 Export (#646)."""
import os
import tempfile

import numpy as np
from PySide6.QtCore import QSize, QRectF
from PySide6.QtGui import QImage, QPainter, QPixmap

from geoviz import CurveData, WellLogData, build_qpainter_tracks
from geoviz_well_log.renderer.canvas import WellLogCanvas
from geoviz_well_log.export_qpainter import export_svg, export_pdf, export_png
from geoviz_cross_well.correlation_layer import CorrelationLayer


def _paint_nonwhite_pixels(canvas: WellLogCanvas) -> int:
    """Rasterize ``paint_all`` onto a white image; empty paint is all white."""
    img = QImage(canvas.size(), QImage.Format.Format_RGBA8888)
    img.fill(0xFFFFFFFF)
    painter = QPainter(img)
    canvas.paint_all(painter)
    painter.end()
    arr = np.frombuffer(img.constBits(), dtype=np.uint8).reshape(
        img.height(), img.width(), 4
    ).copy()
    return int(np.count_nonzero(np.any(arr[:, :, :3] != 255, axis=2)))


def test_well_log_canvas_paint_all_and_exports(qtbot):
    """#646: export must paint loaded tracks, not just a non-empty container."""
    empty = WellLogCanvas()
    empty.resize(400, 800)
    qtbot.addWidget(empty)

    data = WellLogData(
        well_name="EXPORT-TEST",
        top_depth=1000.0,
        bottom_depth=1100.0,
        curves=[
            CurveData(
                name="GR",
                unit="GAPI",
                depth=[1000.0, 1050.0, 1100.0],
                values=[40.0, 120.0, 55.0],
            )
        ],
    )
    canvas = WellLogCanvas()
    canvas.resize(400, 800)
    canvas.set_tracks(build_qpainter_tracks(data))
    canvas.set_depth_range(1000.0, 1100.0)
    qtbot.addWidget(canvas)

    with tempfile.TemporaryDirectory() as tmpdir:
        empty_svg = os.path.join(tmpdir, "empty.svg")
        empty_png = os.path.join(tmpdir, "empty.png")
        svg_path = os.path.join(tmpdir, "output.svg")
        pdf_path = os.path.join(tmpdir, "output.pdf")
        png_path = os.path.join(tmpdir, "output.png")

        export_svg(empty, empty_svg)
        export_png(empty, empty_png)
        export_svg(canvas, svg_path)
        export_pdf(canvas, pdf_path)
        export_png(canvas, png_path)

        assert os.path.exists(svg_path) and os.path.getsize(svg_path) > 0
        assert os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0
        assert os.path.exists(png_path) and os.path.getsize(png_path) > 0

        svg_text = open(svg_path, encoding="utf-8", errors="replace").read()
        empty_svg_text = open(empty_svg, encoding="utf-8", errors="replace").read()
        assert "GR" in svg_text
        assert "GR" not in empty_svg_text
        assert os.path.getsize(svg_path) > os.path.getsize(empty_svg)
        # grab() of an offscreen empty widget is a noisy container; paint_all
        # is the content path export_svg uses. Loaded tracks must ink pixels.
        assert _paint_nonwhite_pixels(empty) == 0
        assert _paint_nonwhite_pixels(canvas) > 0
