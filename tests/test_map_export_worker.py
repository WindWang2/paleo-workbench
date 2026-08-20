"""Off-thread unified-map export worker regressions (#832 / #852).

The worker renders a throwaway fallback backend on a background thread, so the
fallback composition must cover every layer type the live canvas can show, and
a mid-render cancel must never leave a partial export file behind.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QImage

from paleo_workbench.mapping.map_render_backend import (
    FallbackMapRenderBackend,
    MapLayerSnapshot,
    MapRenderSnapshot,
)
from paleo_workbench.ui.map_export_worker import (
    MapExportSpec,
    MapExportWorker,
    render_and_save_map_export,
    snapshot_map_export,
)
from paleo_workbench.ui.unified_map_canvas import UnifiedMapCanvas


def _raster_snapshot(raster_path: str) -> MapRenderSnapshot:
    return MapRenderSnapshot(
        project_crs="EPSG:3857",
        layers=(
            MapLayerSnapshot(
                id="reference",
                name="Reference",
                layer_type="raster_source",
                extent=(0.0, 0.0, 10.0, 10.0),
                crs="EPSG:3857",
                data_revision=1,
                style_revision=1,
                renderer_payload=raster_path,
            ),
        ),
    )


def _canvas_with_raster(qtbot, raster_path: str) -> UnifiedMapCanvas:
    canvas = UnifiedMapCanvas(backend=FallbackMapRenderBackend())
    qtbot.addWidget(canvas)
    canvas.resize(320, 240)
    canvas.set_layer_snapshot(_raster_snapshot(raster_path))
    canvas.set_extent((0.0, 0.0, 10.0, 10.0), record_history=False)
    qtbot.waitUntil(lambda: canvas.last_frame is not None, timeout=5_000)
    return canvas


def test_export_worker_png_includes_raster_source_layer(qtbot, tmp_path) -> None:
    """#832: the off-thread export path renders a raster_source reference
    basemap into the PNG instead of silently dropping the layer (the fallback
    backend has no QGIS symbology, but the raster reference map must appear)."""
    source = tmp_path / "basemap.png"
    image = QImage(16, 16, QImage.Format.Format_RGBA8888)
    image.fill(QColor("#ff8800"))
    assert image.save(str(source), "PNG")

    canvas = _canvas_with_raster(qtbot, str(source))

    out = tmp_path / "export.png"
    spec = snapshot_map_export(canvas, str(out), width=200, height=200, dpi=96.0)
    render_and_save_map_export(spec)

    saved = QImage(str(out))
    assert not saved.isNull()
    orange = 0
    for y in range(saved.height()):
        for x in range(saved.width()):
            color = saved.pixelColor(QPoint(x, y))
            if color.red() > 200 and 60 < color.green() < 200:
                orange += 1
    # The raster fills the whole viewport: it must dominate the frame.
    assert orange > saved.width() * saved.height() // 2, (
        "raster_source layer missing from off-thread export"
    )


def test_export_worker_cancel_after_render_removes_partial_file(
    monkeypatch, tmp_path
) -> None:
    """#852: a cancel that lands after the render wrote its file must not
    leave the stale PNG behind on the target path."""
    import paleo_workbench.ui.map_export_worker as worker_module

    out = tmp_path / "export.png"
    spec = MapExportSpec(
        snapshot=MapRenderSnapshot(project_crs=""),
        extent=(0.0, 0.0, 1.0, 1.0),
        width=160,
        height=120,
        dpi=96.0,
        decorations={},
        path=str(out),
    )
    worker = MapExportWorker(spec)
    emitted: list[str] = []

    def fake_render(existing: MapExportSpec):
        # Simulate a render that completes (writes the PNG) while the user is
        # cancelling: the flag is observed only after the file exists.
        image = QImage(160, 120, QImage.Format.Format_RGBA8888)
        image.fill(QColor("#56789a"))
        assert image.save(existing.path, "PNG")
        worker.cancel()

    monkeypatch.setattr(worker_module, "render_and_save_map_export", fake_render)
    worker.cancelled.connect(lambda: emitted.append("cancelled"))
    worker.finished.connect(lambda _path: emitted.append("finished"))

    worker.run()

    assert emitted == ["cancelled"]
    assert not out.exists(), "a cancelled export must not leave a partial file"

def test_worker_and_canvas_legend_agree_at_export_dpi(qtbot):
    """#892: the async PNG export path must scale the legend like the canvas
    path does — a 300-dpi export previously drew ~1 mm legend text because
    the worker copy skipped DPI scaling and never set a font."""
    from PySide6.QtGui import QImage, QPainter

    from paleo_workbench.ui.unified_map_canvas import (
        UnifiedMapCanvas,
        paint_map_decorations,
    )

    decorations = {
        "elements": ("图例",),
        "legend_items": ("砂岩", "泥岩", "石灰岩"),
    }
    canvas = UnifiedMapCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(2400, 1600)
    canvas._view_extent = (0.0, 0.0, 1000.0, 500.0)

    def render(kind: str) -> QImage:
        img = QImage(2400, 1600, QImage.Format.Format_ARGB32)
        img.fill(0)
        painter = QPainter(img)
        if kind == "worker":
            paint_map_decorations(
                painter, decorations, width=2400, height=1600,
                extent=(0.0, 0.0, 1000.0, 500.0), dpi=300.0,
            )
        else:
            canvas._paint_decorations(
                painter, decorations, width=2400, height=1600,
                scale=300.0 / 96.0, extent=(0.0, 0.0, 1000.0, 500.0),
            )
        painter.end()
        return img

    def swatch_height(img: QImage) -> int:
        # Legend swatches are opaque blue-ish (#6c8ebf) squares; measure the
        # tallest blue run in the bottom-right quadrant.
        best = 0
        for x in range(1840, 1990):
            run = 0
            for y in range(1300, 1599):
                pixel = img.pixelColor(x, y)
                if pixel.blue() > 120 and pixel.red() < 160 and pixel.green() < 160:
                    run += 1
                else:
                    best = max(best, run)
                    run = 0
            best = max(best, run)
        return best

    worker_h = swatch_height(render("worker"))
    canvas_h = swatch_height(render("canvas"))
    # At 300 dpi the swatch is 9px * 300/96 ≈ 28px; before the fix the worker
    # path drew a 9px swatch (ratio ~3.1).
    assert abs(worker_h - canvas_h) <= 1
    assert worker_h >= 20, f"worker legend swatch too small for 300 dpi: {worker_h}px"
