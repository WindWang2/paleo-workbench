"""Screen-vs-export consistency contracts for the unified map canvas."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint

from paleo_workbench.mapping.map_render_backend import FallbackMapRenderBackend
from paleo_workbench.ui.unified_map_canvas import UnifiedMapCanvas


def _snapshot():
    from paleo_workbench.mapping.map_render_backend import MapLayerSnapshot, MapRenderSnapshot

    return MapRenderSnapshot(
        project_crs="EPSG:3857",
        layers=(
            MapLayerSnapshot(
                id="facies",
                name="Facies",
                layer_type="vector",
                extent=(0.0, 0.0, 10.0, 10.0),
                crs="EPSG:3857",
                data_revision=1,
                style_revision=1,
                features=(
                    {
                        "id": "square",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[2.0, 2.0], [8.0, 2.0], [8.0, 8.0], [2.0, 8.0], [2.0, 2.0]]],
                        },
                        "properties": {},
                    },
                ),
                style={"fill": "#d9a441", "stroke": "#593d16", "stroke_width": 2.0},
            ),
        ),
    )


def _canvas(qtbot) -> UnifiedMapCanvas:
    canvas = UnifiedMapCanvas(backend=FallbackMapRenderBackend())
    qtbot.addWidget(canvas)
    canvas.resize(320, 240)
    canvas.show()
    canvas.set_layer_snapshot(_snapshot())
    canvas.set_extent((0.0, 0.0, 10.0, 10.0))
    qtbot.waitUntil(lambda: canvas.last_frame is not None, timeout=5_000)
    return canvas


def _content_bbox(image, *, background=(255, 255, 255)):
    """Bounding box of non-background pixels inside the central 60% region."""
    min_x = min_y = None
    max_x = max_y = None
    x0, y0 = int(image.width() * 0.2), int(image.height() * 0.2)
    x1, y1 = int(image.width() * 0.8), int(image.height() * 0.8)
    for y in range(y0, y1):
        for x in range(x0, x1):
            color = image.pixelColor(QPoint(x, y))
            if (color.red(), color.green(), color.blue()) != background:
                min_x = x if min_x is None else min_x
                max_x = x if max_x is None else max_x
                min_y = y if min_y is None else min_y
                max_y = y if max_y is None else max_y
                max_x = max(max_x, x)
                max_y = max(max_y, y)
                min_x = min(min_x, x)
                min_y = min(min_y, y)
    if min_x is None:
        return None
    return (min_x, min_y, max_x, max_y)


def test_export_png_matches_screen_frame_and_carries_dpi_metadata(qtbot, tmp_path) -> None:
    canvas = _canvas(qtbot)
    # Match the on-screen geometry exactly: same logical size and dpi.
    image = canvas.render_export_image(320, 240, dpi=96.0)

    assert (image.width(), image.height()) == (320, 240)
    frame = canvas.last_frame
    # The composition pixels (centre crop, clear of decorations) must be the
    # same bytes the screen displays: one pipeline, two outputs.
    for probe in ((120, 100), (160, 120), (200, 140)):
        screen = frame.rgba[(probe[1] * frame.stride) + probe[0] * 4 : (probe[1] * frame.stride) + probe[0] * 4 + 4]
        exported = image.pixelColor(QPoint(*probe))
        assert tuple(screen[:3]) == (exported.red(), exported.green(), exported.blue()), probe

    path = tmp_path / "map.png"
    canvas.export_png(str(path), width=320, height=240, dpi=300.0)
    from PySide6.QtGui import QImage

    saved = QImage(str(path))
    assert (saved.width(), saved.height()) == (320, 240)
    assert saved.dotsPerMeterX() == round(300.0 / 0.0254)
    assert saved.dotsPerMeterY() == round(300.0 / 0.0254)


def test_export_preserves_geometry_aspect_at_mismatched_output_ratio(qtbot) -> None:
    canvas = _canvas(qtbot)
    # Square world feature into a 2:1 export frame: without letterboxing the
    # square would render at 2:1.
    image = canvas.render_export_image(400, 200, dpi=96.0)

    bbox = _content_bbox(image)
    assert bbox is not None
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    assert abs(width - height) <= max(2, 0.08 * max(width, height))


def test_export_svg_keeps_vector_primitives(qtbot, tmp_path) -> None:
    canvas = _canvas(qtbot)
    path = tmp_path / "map.svg"

    canvas.export_svg(str(path), width=800, height=600, dpi=96.0)

    text = path.read_text(encoding="utf-8")
    assert "<svg" in text
    assert "<path" in text or "<polygon" in text or "<g" in text


def test_export_pdf_writes_real_pdf(qtbot, tmp_path) -> None:
    canvas = _canvas(qtbot)
    path = tmp_path / "map.pdf"

    canvas.export_pdf(str(path), width=800, height=600, dpi=150.0)

    data = path.read_bytes()
    assert data.startswith(b"%PDF")
    assert len(data) > 1000


def test_export_capabilities_now_include_vector_formats_for_unified_map() -> None:
    from paleo_workbench.resources.export_service import view_export_capabilities

    class _FakeUnifiedCanvas:
        export_png = export_svg = export_pdf = staticmethod(lambda *a, **k: None)

    _FakeUnifiedCanvas.__name__ = "UnifiedMapCanvas"

    assert view_export_capabilities(_FakeUnifiedCanvas()) == frozenset({"PNG", "SVG", "PDF"})


def test_snapshot_source_version_ids_flow_from_layer_provenance(qtbot) -> None:
    from paleo_workbench.mapping.map_render_backend import MapLayerSnapshot, MapRenderSnapshot
    from paleo_workbench.ui.unified_map_canvas import UnifiedMapCanvas

    snapshot = MapRenderSnapshot(
        project_crs="",
        layers=(
            MapLayerSnapshot(
                id="grid",
                name="grid",
                layer_type="scalar_grid",
                extent=(0.0, 0.0, 1.0, 1.0),
                crs="",
                data_revision=1,
                style_revision=1,
                source_version_id="dv-123",
            ),
            MapLayerSnapshot(
                id="other",
                name="other",
                layer_type="scalar_grid",
                extent=(0.0, 0.0, 1.0, 1.0),
                crs="",
                data_revision=1,
                style_revision=1,
                source_version_id="dv-123",
            ),
        ),
    )
    canvas = UnifiedMapCanvas(backend=FallbackMapRenderBackend())
    qtbot.addWidget(canvas)
    canvas.set_layer_snapshot(snapshot)

    assert canvas.snapshot_source_version_ids == ("dv-123",)


def test_export_graduated_and_annotation_layers_consistency(qtbot, tmp_path) -> None:
    from paleo_workbench.mapping.map_render_backend import MapLayerSnapshot, MapRenderSnapshot
    snapshot = MapRenderSnapshot(
        project_crs="EPSG:3857",
        layers=(
            MapLayerSnapshot(
                id="grad",
                name="Graduated Layer",
                layer_type="vector",
                extent=(0.0, 0.0, 20.0, 20.0),
                crs="EPSG:3857",
                data_revision=1,
                style_revision=1,
                features=(
                    {
                        "id": "poly",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[2.0, 2.0], [18.0, 2.0], [18.0, 18.0], [2.0, 18.0], [2.0, 2.0]]],
                        },
                        "properties": {"val": 15.0},
                    },
                ),
                style={
                    "renderer": "graduated",
                    "field": "val",
                    "fill": "#333333",
                    "stroke": "#000000",
                    "ranges": [
                        [0.0, 10.0, "#ff0000", "Low"],
                        [10.0, 20.0, "#00ff00", "Med"],
                    ],
                },
            ),
            MapLayerSnapshot(
                id="ann",
                name="Annotation Layer",
                layer_type="annotation",
                extent=(0.0, 0.0, 20.0, 20.0),
                crs="EPSG:3857",
                data_revision=1,
                style_revision=1,
                features=(
                    {
                        "id": "ann1",
                        "geometry": {"type": "Point", "coordinates": [10.0, 10.0]},
                        "properties": {"text": "Basin Center", "color": "#ffffff"},
                    },
                ),
                style={
                    "fill": "#ffffff",
                    "stroke": "#000000",
                    "labels": {"field": "text", "size": 10.0, "color": "#ffffff", "visible": True},
                },
            ),
        ),
    )
    canvas = UnifiedMapCanvas(backend=FallbackMapRenderBackend())
    qtbot.addWidget(canvas)
    canvas.resize(320, 240)
    canvas.show()
    canvas.set_layer_snapshot(snapshot)
    canvas.set_extent((0.0, 0.0, 20.0, 20.0))
    qtbot.waitUntil(lambda: canvas.last_frame is not None, timeout=5_000)

    # Export PNG, SVG, PDF
    png_path = tmp_path / "grad_map.png"
    svg_path = tmp_path / "grad_map.svg"
    pdf_path = tmp_path / "grad_map.pdf"

    canvas.export_png(str(png_path), width=320, height=240, dpi=96.0)
    canvas.export_svg(str(svg_path), width=320, height=240, dpi=96.0)
    canvas.export_pdf(str(pdf_path), width=320, height=240, dpi=150.0)

    assert png_path.exists()
    assert svg_path.exists()
    assert pdf_path.exists()
    assert "<svg" in svg_path.read_text(encoding="utf-8")
    assert pdf_path.read_bytes().startswith(b"%PDF")



# ---------------------------------------------------------------------------
# Export DPI parity (Issue #1103): 96/150/300/600 print the same page
# ---------------------------------------------------------------------------

_DPI_LEVELS = (96.0, 150.0, 300.0, 600.0)


def _stroke_thickness_px(image, bbox) -> int | None:
    """Device-pixel thickness of the fixture square's left-edge stroke.

    The leftmost content column *is* the left stroke, so scan one row at
    the bbox's vertical middle, starting just left of bbox[0] and crossing
    the edge. Letterboxing shifts the edge with the frame ratio, which is
    why the band is derived from the measured bbox, not a fixed fraction.
    """
    y = (bbox[1] + bbox[3]) // 2
    x0 = max(0, bbox[0] - 3)
    x1 = min(image.width(), bbox[0] + max(9, int(image.width() * 0.02)))
    best = run = 0
    for x in range(x0, x1):
        color = image.pixelColor(QPoint(x, y))
        if (color.red(), color.green(), color.blue()) != (255, 255, 255):
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best or None


def test_export_physical_parity_across_dpi(qtbot, tmp_path) -> None:
    """A fixed physical page must print identically at 96/150/300/600 DPI.

    Two pins: (a) the content footprint (bbox) has the same physical size
    at every resolution, and (b) the painter stroke itself scales its
    device-pixel thickness by dpi/96 — the named
    ``RenderContext.device_px_per_logical_px`` fold — so the printed stroke
    weight is constant.
    """
    from PySide6.QtGui import QImage

    target_w_mm, target_h_mm = 200.0, 150.0
    bboxes = {}
    thickness = {}
    for dpi in _DPI_LEVELS:
        w = round(target_w_mm / 25.4 * dpi)
        h = round(target_h_mm / 25.4 * dpi)
        canvas = _canvas(qtbot)

        # Product path: export_png persists the physical resolution itself.
        path = tmp_path / f"map_{int(dpi)}.png"
        canvas.export_png(str(path), width=w, height=h, dpi=dpi)
        saved = QImage(str(path))
        assert (saved.width(), saved.height()) == (w, h)
        assert saved.dotsPerMeterX() == round(dpi / 0.0254)
        assert saved.dotsPerMeterY() == round(dpi / 0.0254)

        bbox = _content_bbox(saved)
        assert bbox is not None, f"no content rendered at {dpi} dpi"
        bboxes[dpi] = bbox
        stroke = _stroke_thickness_px(saved, bbox)
        assert stroke is not None and stroke >= 1, f"no stroke found at {dpi} dpi"
        thickness[dpi] = stroke

    # (a) Physical content footprint: pixel bbox / dpi agrees across DPIs.
    ref = bboxes[96.0]
    ref_w_in = (ref[2] - ref[0]) / 96.0
    ref_h_in = (ref[3] - ref[1]) / 96.0
    for dpi, bbox in bboxes.items():
        phys_w = (bbox[2] - bbox[0]) / dpi
        phys_h = (bbox[3] - bbox[1]) / dpi
        assert abs(phys_w - ref_w_in) <= 0.05 * ref_w_in + 0.02, (dpi, phys_w, ref_w_in)
        assert abs(phys_h - ref_h_in) <= 0.05 * ref_h_in + 0.02, (dpi, phys_h, ref_h_in)

    # (b) Stroke device thickness tracks dpi/96: printed weight constant.
    # Antialiasing rounds the run length, so allow generous slack around
    # the exact ratio — but an unscaled fold (ratio 1.0) must fail hard.
    ratio = thickness[600.0] / thickness[96.0]
    assert 0.7 * 600.0 / 96.0 <= ratio <= 1.3 * 600.0 / 96.0, ratio


def test_pdf_page_physical_size_tracks_dpi(qtbot, tmp_path) -> None:
    """The PDF page must frame the requested physical size at every DPI.

    Page size is width/dpi inches expressed in PDF points (1/72 inch);
    a 200 mm page is ~567 pt whether written at 96 or 600 DPI.
    """
    import re

    target_w_mm = 200.0
    for dpi in _DPI_LEVELS:
        w = round(target_w_mm / 25.4 * dpi)
        h = round(150.0 / 25.4 * dpi)
        path = tmp_path / f"map_{int(dpi)}.pdf"
        _canvas(qtbot).export_pdf(str(path), width=w, height=h, dpi=dpi)

        data = path.read_bytes()
        assert data.startswith(b"%PDF")
        match = re.search(rb"/MediaBox\s*\[\s*0\s+0\s+([0-9.]+)\s+([0-9.]+)\s*\]", data)
        assert match is not None, "PDF MediaBox not found"
        page_w_pt = float(match.group(1))
        expected_pt = target_w_mm / 25.4 * 72.0
        assert abs(page_w_pt - expected_pt) <= 2.0, (dpi, page_w_pt, expected_pt)


def test_export_svg_physical_geometry_is_dpi_invariant(qtbot, tmp_path) -> None:
    """Canvas SVG export prints the same page at any dpi (#1103 contract).

    ``export_svg`` renders through QSvgGenerator — a QPaintDevice, so it
    belongs to the *device-px painter regime*: its user-unit numbers scale
    with dpi while the root physical-size annotation compensates. The
    contract is physical invariance: identical viewBox, and every
    user-unit quantity divided by the root page width is constant across
    DPIs (same printed geometry, stroke and font size).
    """
    import re

    ratios = []
    for dpi in (96.0, 600.0):
        path = tmp_path / f"map_{int(dpi)}.svg"
        _canvas(qtbot).export_svg(str(path), width=800, height=600, dpi=dpi)
        data = path.read_bytes()
        view = re.search(rb'viewBox="([^"]*)"', data)
        width_mm = re.search(rb'width="([0-9.]+)mm"', data)
        font = re.search(rb'font-size="([0-9.]+)"', data)
        assert view is not None and width_mm is not None and font is not None
        assert view.group(1) == b"0 0 800 600"
        # Physical font ∝ user-units × (page_mm / user_span); with the
        # viewBox span equal, user-units × page_mm is the invariant.
        ratios.append(float(font.group(1)) * float(width_mm.group(1)))

    assert ratios[0] == pytest.approx(ratios[1], rel=1e-3)
