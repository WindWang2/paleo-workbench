"""Render-backend seam tests for the unified map authoring canvas."""

from __future__ import annotations

from dataclasses import replace
import numpy as np
import pytest

from paleo_workbench.mapping.map_render_backend import (
    FallbackMapRenderBackend,
    MapLayerSnapshot,
    MapRenderSnapshot,
    QgisMapRenderBackend,
)
from paleo_workbench.viz.native_factor_map import MapScene
from paleo_workbench.workflow.factor_grid_result import FactorGridResult
from paleo_workbench.project.models import FactorMapTask
from paleo_workbench.workflow.factor_interpolation import apply_interpolation_to_task
from tests.qgis_support import QGIS_SKIP_REASON


def _snapshot(*, data_revision: int = 1) -> MapRenderSnapshot:
    return MapRenderSnapshot(
        project_crs="EPSG:3857",
        layers=(
            MapLayerSnapshot(
                id="facies",
                name="Facies",
                layer_type="vector",
                extent=(0.0, 0.0, 20.0, 20.0),
                crs="EPSG:3857",
                data_revision=data_revision,
                style_revision=1,
                features=(
                    {
                        "id": "facies-1",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [2.0, 2.0],
                                    [18.0, 2.0],
                                    [18.0, 18.0],
                                    [2.0, 18.0],
                                    [2.0, 2.0],
                                ]
                            ],
                        },
                        "properties": {"facies": "shoreface"},
                    },
                ),
                style={"fill": "#d9a441", "stroke": "#593d16", "stroke_width": 1.0},
            ),
        ),
    )


def _configure(backend) -> None:
    backend.initialize()
    backend.set_layer_snapshot(_snapshot())
    backend.set_extent((0.0, 0.0, 20.0, 20.0))
    backend.set_output_size(160, 120)
    backend.set_dpi(96.0)


def test_fallback_backend_renders_revisioned_vector_snapshot() -> None:
    backend = FallbackMapRenderBackend()
    _configure(backend)

    frame = backend.render_sync()

    assert backend.backend_name == "fallback"
    assert backend.is_available
    assert (frame.width, frame.height, frame.stride) == (160, 120, 640)
    assert frame.generation == 1
    assert len(frame.rgba) == frame.height * frame.stride
    # Known opaque polygon content must not collapse to the fallback background.
    assert any(byte not in {255} for byte in frame.rgba)


def test_fallback_backend_discards_preceding_generation_after_view_change() -> None:
    backend = FallbackMapRenderBackend()
    _configure(backend)

    first_generation = backend.request_render()
    backend.set_extent((2.0, 2.0, 18.0, 18.0))
    second_generation = backend.request_render()
    frame = backend.take_completed_frame()

    assert second_generation > first_generation
    assert frame is not None
    assert frame.generation == second_generation
    assert backend.take_completed_frame() is None


def test_qgis_backend_is_explicit_when_optional_native_bridge_is_missing_or_renders_snapshot(qtbot) -> None:
    backend = QgisMapRenderBackend()

    if backend.is_available:
        _configure(backend)
        try:
            frame = backend.render_sync()
        finally:
            backend.shutdown()
        assert backend.backend_name == "qgis"
        assert (frame.width, frame.height) == (160, 120)
        assert len(frame.rgba) == frame.height * frame.stride
        assert any(frame.rgba)
        return

    assert backend.backend_name == "qgis"
    assert "unavailable" in backend.status.lower()
    with pytest.raises(RuntimeError, match="unavailable"):
        backend.initialize()


@pytest.mark.qgis
def test_qgis_backend_delivers_only_the_latest_asynchronous_frame(qtbot) -> None:
    backend = QgisMapRenderBackend()
    if not backend.is_available:
        pytest.skip(QGIS_SKIP_REASON)
    _configure(backend)
    try:
        first = backend.request_render()
        backend.set_extent((2.0, 2.0, 18.0, 18.0))
        second = backend.request_render()
        frame = None

        def take_newest_frame() -> bool:
            nonlocal frame
            frame = backend.take_completed_frame()
            return frame is not None

        qtbot.waitUntil(take_newest_frame, timeout=5_000)
    finally:
        backend.shutdown()

    assert frame is not None
    assert frame.generation == second
    assert second > first


@pytest.mark.qgis
def test_qgis_single_symbol_style_revision_changes_rendered_vector_frame(qtbot) -> None:
    backend = QgisMapRenderBackend()
    if not backend.is_available:
        pytest.skip(QGIS_SKIP_REASON)
    _configure(backend)
    try:
        first = backend.render_sync()
        original = _snapshot().layers[0]
        styled = replace(
            original,
            style_revision=original.style_revision + 1,
            style={"fill": "#e03131", "stroke": "#ffffff", "stroke_width": 3.0},
        )
        backend.set_layer_snapshot(MapRenderSnapshot(project_crs="EPSG:3857", layers=(styled,)))
        second = backend.render_sync()
    finally:
        backend.shutdown()

    assert first.rgba != second.rgba


@pytest.mark.qgis
def test_qgis_categorized_and_labeled_vector_style_uses_host_feature_attributes(qtbot) -> None:
    backend = QgisMapRenderBackend()
    if not backend.is_available:
        pytest.skip(QGIS_SKIP_REASON)
    original = _snapshot().layers[0]
    categorized = replace(
        original,
        data_revision=2,
        style_revision=2,
        features=(
            original.features[0],
            {
                "id": "facies-2",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[2.0, 2.0], [10.0, 2.0], [10.0, 18.0], [2.0, 18.0], [2.0, 2.0]]],
                },
                "properties": {"facies": "channel", "name": "channel"},
            },
        ),
        style={
            "renderer": "categorized",
            "field": "facies",
            "categories": {"shoreface": "#e03131", "channel": "#1971c2"},
            "stroke": "#ffffff",
            "stroke_width": 1.0,
            "labels": {"field": "facies", "size": 9.0, "color": "#111111", "buffer": 1.0},
        },
    )
    backend.initialize()
    try:
        backend.set_layer_snapshot(MapRenderSnapshot(project_crs="EPSG:3857", layers=(original,)))
        backend.set_extent((0.0, 0.0, 20.0, 20.0))
        backend.set_output_size(160, 120)
        plain = backend.render_sync()
        backend.set_layer_snapshot(MapRenderSnapshot(project_crs="EPSG:3857", layers=(categorized,)))
        styled = backend.render_sync()
    finally:
        backend.shutdown()

    assert plain.rgba != styled.rgba


@pytest.mark.qgis
def test_qgis_backend_composes_the_finished_scalar_grid_without_interpolation(qtbot) -> None:
    backend = QgisMapRenderBackend()
    if not backend.is_available:
        pytest.skip(QGIS_SKIP_REASON)
    result = FactorGridResult.from_engine_dict(
        {
            "grid_x": [0.0, 10.0],
            "grid_y": [0.0, 10.0],
            "grid_z": [[0.0, 1.0], [0.5, None]],
            "backend": "idw",
            "n_points": 4,
        },
        factor_name="Porosity",
        crs="EPSG:3857",
    )
    scene = MapScene()
    scene.add_factor_grid(result, layer_id="porosity")
    scalar = scene.scalar_layer("porosity")
    backend.initialize()
    try:
        backend.set_layer_snapshot(scene.render_snapshot(project_crs="EPSG:3857"))
        backend.set_extent(result.extent)
        backend.set_output_size(160, 120)
        backend.request_render()
        frame = None

        def take_frame() -> bool:
            nonlocal frame
            frame = backend.take_completed_frame()
            return frame is not None

        qtbot.waitUntil(take_frame, timeout=5_000)
        cache = backend._scalar_raster_cache
        assert cache is not None
        assert cache.uses_virtual_memory
        assert cache.materialization_count == 1
        assert cache.disk_materialization_count == 0

        # Viewport-only interaction rerenders the QGIS composition but must not
        # materialize the already revision-keyed scalar source a second time.
        backend.set_extent((1.0, 1.0, 9.0, 9.0))
        backend.request_render()
        frame = None
        qtbot.waitUntil(take_frame, timeout=5_000)
        assert cache.materialization_count == 1
    finally:
        backend.shutdown()

    assert frame is not None
    assert (frame.width, frame.height) == (160, 120)
    assert scalar.rasterize_count == 1


@pytest.mark.qgis
def test_qgis_backend_renders_an_external_raster_reference_mirror(tmp_path, qtbot) -> None:
    backend = QgisMapRenderBackend()
    if not backend.is_available:
        pytest.skip(QGIS_SKIP_REASON)
    from osgeo import gdal, osr

    source = tmp_path / "reference.tif"
    dataset = gdal.GetDriverByName("GTiff").Create(str(source), 4, 4, 1, gdal.GDT_Byte)
    dataset.GetRasterBand(1).WriteRaster(0, 0, 4, 4, bytes(range(16)))
    spatial_ref = osr.SpatialReference()
    spatial_ref.ImportFromEPSG(3857)
    dataset.SetProjection(spatial_ref.ExportToWkt())
    dataset.SetGeoTransform((0.0, 1.0, 0.0, 4.0, 0.0, -1.0))
    dataset = None
    snapshot = MapRenderSnapshot(
        project_crs="EPSG:3857",
        layers=(
            MapLayerSnapshot(
                id="reference",
                name="Reference",
                layer_type="raster_source",
                extent=(0.0, 0.0, 4.0, 4.0),
                crs="EPSG:3857",
                data_revision=1,
                style_revision=1,
                renderer_payload=str(source),
            ),
        ),
    )
    backend.initialize()
    try:
        backend.set_layer_snapshot(snapshot)
        backend.set_extent((0.0, 0.0, 4.0, 4.0))
        backend.set_output_size(64, 64)
        frame = backend.render_sync()
    finally:
        backend.shutdown()

    assert any(frame.rgba)


@pytest.mark.qgis
def test_qgis_display_operations_never_reinvoke_factor_interpolation(monkeypatch, qtbot) -> None:
    backend = QgisMapRenderBackend()
    if not backend.is_available:
        pytest.skip(QGIS_SKIP_REASON)
    import paleo_workbench.workflow.factor_interpolation as interpolation

    calls = 0
    original = interpolation.interpolate_factor_grid

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(interpolation, "interpolate_factor_grid", counted)
    task = FactorMapTask(
        id="qgis-idw",
        name="Porosity",
        target_horizon="H1",
        factor_type="Porosity",
        method="IDW",
        status="pending",
        parameters={
            "sample_points": [
                {"x": 0.0, "y": 0.0, "value": 0.0},
                {"x": 1.0, "y": 0.0, "value": 0.3},
                {"x": 0.0, "y": 1.0, "value": 0.7},
                {"x": 1.0, "y": 1.0, "value": 1.0},
            ]
        },
        source_kind="real",
    )
    apply_interpolation_to_task(task, method="IDW", grid_n=8)
    assert calls == 1
    from paleo_workbench.viz.native_factor_map import scene_from_factor_task

    scene = scene_from_factor_task(task, crs="EPSG:3857")
    backend.initialize()
    try:
        backend.set_output_size(160, 120)
        backend.set_layer_snapshot(scene.render_snapshot(project_crs="EPSG:3857"))
        backend.set_extent(scene.extent())
        backend.request_render()

        def take_first() -> bool:
            return backend.take_completed_frame() is not None

        qtbot.waitUntil(take_first, timeout=5_000)
        scene.set_scalar_style(task.id, gamma=1.25)
        scene.set_layer_opacity(task.id, 0.5)
        scene.registry.move_layer(task.id, 0)
        backend.set_layer_snapshot(scene.render_snapshot(project_crs="EPSG:3857"))
        backend.set_extent((0.1, 0.1, 0.9, 0.9))
        backend.request_render()

        def take_second() -> bool:
            return backend.take_completed_frame() is not None

        qtbot.waitUntil(take_second, timeout=5_000)
    finally:
        backend.shutdown()

    assert calls == 1


def _line_snapshot(*, stroke_width: float = 1.0) -> MapRenderSnapshot:
    return MapRenderSnapshot(
        project_crs="EPSG:3857",
        layers=(
            MapLayerSnapshot(
                id="line",
                name="Line",
                layer_type="vector",
                extent=(0.0, 0.0, 20.0, 20.0),
                crs="EPSG:3857",
                data_revision=1,
                style_revision=1,
                features=(
                    {
                        "id": "line-1",
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[0.5, 10.125], [19.5, 10.125]],
                        },
                        "properties": {},
                    },
                ),
                style={"stroke": "#26364d", "stroke_width": stroke_width},
            ),
        ),
    )


def _stroke_ink(backend: FallbackMapRenderBackend, *, dpi: float) -> int:
    """Sum of pixel deviation from the background across the rendered frame.

    Antialiasing preserves ink area, so the sum is proportional to the
    painted stroke width times its length.
    """
    backend.set_output_size(320, 240)
    backend.set_dpi(dpi)
    frame = backend.render_sync()
    pixels = np.frombuffer(frame.rgba, dtype=np.uint8).reshape(240, 320, 4).astype(int)
    background = np.array([0xFF, 0xFF, 0xFF, 0xFF], dtype=int)
    return int(np.abs(pixels - background).sum())


def test_fallback_export_scales_stroke_width_with_dpi() -> None:
    """Fallback export must honor dpi: stroke width = base × dpi/96 (<1%)."""
    import numpy as np

    backend = FallbackMapRenderBackend()
    backend.initialize()
    backend.set_layer_snapshot(_line_snapshot())
    backend.set_extent((0.0, 0.0, 20.0, 20.0))

    ink_96 = _stroke_ink(backend, dpi=96.0)
    ink_300 = _stroke_ink(backend, dpi=300.0)
    ink_600 = _stroke_ink(backend, dpi=600.0)

    assert ink_96 > 0
    # 300/96 is the acceptance criterion (error < 1%); 600 dpi is a looser
    # monotonicity check because sub-pixel AA rounding grows at wider strokes.
    assert ink_300 / ink_96 == pytest.approx(300.0 / 96.0, rel=0.01)
    assert ink_600 / ink_96 == pytest.approx(600.0 / 96.0, rel=0.03)


def test_fallback_dpi_scales_widths_but_not_geometry_positions() -> None:
    """Only cosmetic sizes scale with dpi; the map extent still fills the
    output exactly (a naive painter.scale would push geometry off-canvas)."""
    backend = FallbackMapRenderBackend()
    backend.initialize()
    backend.set_layer_snapshot(_line_snapshot())
    backend.set_extent((0.0, 0.0, 20.0, 20.0))
    backend.set_output_size(320, 240)

    def line_rows(dpi: float) -> set[int]:
        backend.set_dpi(dpi)
        frame = backend.render_sync()
        pixels = np.frombuffer(frame.rgba, dtype=np.uint8).reshape(240, 320, 4).astype(int)
        background = np.array([0xFF, 0xFF, 0xFF, 0xFF], dtype=int)
        diff = np.abs(pixels - background).sum(axis=2)
        return {int(row) for row in np.where((diff > 24).any(axis=1))[0]}

    rows_96 = line_rows(96.0)
    rows_300 = line_rows(300.0)
    assert rows_96 and rows_300
    # Same vertical band center (position unchanged), wider band at 300 dpi.
    assert (min(rows_96) + max(rows_96)) // 2 == (min(rows_300) + max(rows_300)) // 2
    assert len(rows_300) > len(rows_96)


def _frame_ink(frame) -> int:
    """Sum of pixel deviation from the fallback background across a frame."""
    pixels = np.frombuffer(frame.rgba, dtype=np.uint8).reshape(
        frame.height, frame.width, 4
    ).astype(int)
    background = np.array([0xFF, 0xFF, 0xFF, 0xFF], dtype=int)
    return int(np.abs(pixels - background).sum())


def test_fallback_scale_denominator_tracks_configured_dpi() -> None:
    """#852: _scale_denominator must use the configured dpi, not a hard-coded
    96 — otherwise a 300-dpi export reports a 3.1x-too-small denominator and
    scale_range layer visibility flips incorrectly on HiDPI/export."""
    backend = FallbackMapRenderBackend()
    backend.initialize()
    backend.set_extent((0.0, 0.0, 20.0, 20.0))
    backend.set_output_size(160, 120)

    denom_96 = backend._scale_denominator(160)
    backend.set_dpi(192.0)
    denom_192 = backend._scale_denominator(160)
    backend.set_dpi(300.0)
    denom_300 = backend._scale_denominator(160)

    assert denom_96 > 0
    # The denominator is units-per-pixel × dpi / 0.0254: it must scale with
    # the configured dpi (192/96 = 2x, 300/96 = 3.125x).
    assert denom_192 / denom_96 == pytest.approx(192.0 / 96.0, rel=1e-9)
    assert denom_300 / denom_96 == pytest.approx(300.0 / 96.0, rel=1e-9)


def test_fallback_scale_range_visibility_flips_with_configured_dpi() -> None:
    """#852: a scale_range window must gate on the denominator derived from
    the configured dpi; with the 96-dpi hard-code the layer's visibility was
    frozen regardless of the export dpi."""
    backend = FallbackMapRenderBackend()
    backend.initialize()
    backend.set_extent((0.0, 0.0, 20.0, 20.0))
    backend.set_output_size(160, 120)
    # For this viewport the fitted extent spans 26.667 world units across
    # 160 px: denominator ≈ 630 @ 96 dpi and ≈ 1968 @ 300 dpi. The window
    # between the two makes the layer appear only at high dpi.
    backend.set_layer_snapshot(
        MapRenderSnapshot(
            project_crs="EPSG:3857",
            layers=(
                MapLayerSnapshot(
                    id="scaled",
                    name="Scaled",
                    layer_type="vector",
                    extent=(0.0, 0.0, 20.0, 20.0),
                    crs="EPSG:3857",
                    data_revision=1,
                    style_revision=1,
                    features=(
                        {
                            "id": "f1",
                            "geometry": {
                                "type": "Polygon",
                                "coordinates": [
                                    [
                                        [0.0, 0.0],
                                        [20.0, 0.0],
                                        [20.0, 20.0],
                                        [0.0, 20.0],
                                        [0.0, 0.0],
                                    ]
                                ],
                            },
                            "properties": {},
                        },
                    ),
                    style={"fill": "#ff00ff", "stroke": "#ff00ff", "stroke_width": 1.0},
                    scale_range=(700.0, 2000.0),
                ),
            ),
        )
    )

    backend.set_dpi(96.0)
    frame_low = backend.render_sync()
    backend.set_dpi(300.0)
    frame_high = backend.render_sync()

    # Below the window at 96 dpi (629.9 < 700): background only. At 300 dpi
    # (1968.5 in [700, 2000]) the magenta layer covers the viewport.
    assert _frame_ink(frame_low) == 0
    assert _frame_ink(frame_high) > 0


def test_fallback_backend_renders_raster_source_reference(tmp_path) -> None:
    """#832: the fallback composition must draw raster_source layers too —
    the off-thread export worker renders through a throwaway fallback backend
    even on QGIS installs, so a missing branch silently dropped the reference
    basemap from exported PNGs."""
    from PySide6.QtGui import QColor, QImage

    source = tmp_path / "basemap.png"
    image = QImage(8, 8, QImage.Format.Format_RGBA8888)
    image.fill(QColor("#ff8800"))
    assert image.save(str(source), "PNG")

    snapshot = MapRenderSnapshot(
        project_crs="EPSG:3857",
        layers=(
            MapLayerSnapshot(
                id="reference",
                name="Reference",
                layer_type="raster_source",
                extent=(0.0, 0.0, 4.0, 4.0),
                crs="EPSG:3857",
                data_revision=1,
                style_revision=1,
                renderer_payload=str(source),
            ),
        ),
    )
    backend = FallbackMapRenderBackend()
    backend.initialize()
    backend.set_layer_snapshot(snapshot)
    backend.set_extent((0.0, 0.0, 4.0, 4.0))
    backend.set_output_size(64, 64)
    frame = backend.render_sync()

    # The raster tint (#ff8800) must dominate the frame instead of the
    # background: red channel high, green channel at 0x88.
    pixels = np.frombuffer(frame.rgba, dtype=np.uint8).reshape(64, 64, 4).astype(int)
    orange = int(
        ((np.abs(pixels[:, :, 0] - 0xFF) < 40) & (np.abs(pixels[:, :, 1] - 0x88) < 40)).sum()
    )
    assert orange > 64 * 64 // 2


def test_fallback_backend_renders_graduated_ranges() -> None:
    snapshot = MapRenderSnapshot(
        project_crs="EPSG:3857",
        layers=(
            MapLayerSnapshot(
                id="grad_layer",
                name="Graduated Ranges",
                layer_type="vector",
                extent=(0.0, 0.0, 20.0, 20.0),
                crs="EPSG:3857",
                data_revision=1,
                style_revision=1,
                features=(
                    {
                        "id": "poly1",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[2.0, 2.0], [9.0, 2.0], [9.0, 18.0], [2.0, 18.0], [2.0, 2.0]]],
                        },
                        "properties": {"value": 5.0},
                    },
                    {
                        "id": "poly2",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[11.0, 2.0], [18.0, 2.0], [18.0, 18.0], [11.0, 18.0], [11.0, 2.0]]],
                        },
                        "properties": {"value": 25.0},
                    },
                ),
                style={
                    "renderer": "graduated",
                    "field": "value",
                    "fill": "#333333",
                    "stroke": "#000000",
                    "stroke_width": 1.0,
                    "ranges": [
                        [0.0, 10.0, "#ff0000", "0-10"],
                        [20.0, 30.0, "#00ff00", "20-30"],
                    ],
                },
            ),
        ),
    )
    backend = FallbackMapRenderBackend()
    backend.initialize()
    backend.set_layer_snapshot(snapshot)
    backend.set_extent((0.0, 0.0, 20.0, 20.0))
    backend.set_output_size(100, 100)
    frame = backend.render_sync()

    pixels = np.frombuffer(frame.rgba, dtype=np.uint8).reshape(100, 100, 4)
    # Left polygon should be colored with red (#ff0000)
    red_pixels = int(((pixels[:, :50, 0] > 200) & (pixels[:, :50, 1] < 50)).sum())
    # Right polygon should be colored with green (#00ff00)
    green_pixels = int(((pixels[:, 50:, 1] > 200) & (pixels[:, 50:, 0] < 50)).sum())

    assert red_pixels > 100
    assert green_pixels > 100


def test_fallback_backend_renders_annotation_layer() -> None:
    snapshot = MapRenderSnapshot(
        project_crs="EPSG:3857",
        layers=(
            MapLayerSnapshot(
                id="ann_layer",
                name="Annotation",
                layer_type="annotation",
                extent=(0.0, 0.0, 20.0, 20.0),
                crs="EPSG:3857",
                data_revision=1,
                style_revision=1,
                features=(
                    {
                        "id": "ann1",
                        "geometry": {"type": "Point", "coordinates": [10.0, 10.0]},
                        "properties": {"text": "Fault A", "color": "#f8f9fa", "font_size": 12.0},
                    },
                ),
                style={
                    "fill": "#ffffff",
                    "stroke": "#ffffff",
                    "marker_size": 6.0,
                    "labels": {"field": "text", "size": 12.0, "color": "#f8f9fa", "visible": True},
                },
            ),
        ),
    )
    backend = FallbackMapRenderBackend()
    backend.initialize()
    backend.set_layer_snapshot(snapshot)
    backend.set_extent((0.0, 0.0, 20.0, 20.0))
    backend.set_output_size(100, 100)
    frame = backend.render_sync()

    assert frame is not None
    assert frame.width == 100
    assert frame.height == 100
    # Text or marker must have drawn pixels differing from background
    pixels = np.frombuffer(frame.rgba, dtype=np.uint8).reshape(100, 100, 4)
    non_bg = int((pixels[:, :, :3] != np.array([255, 255, 255])).any(axis=-1).sum())
    assert non_bg > 0


def test_fallback_backend_renders_and_exports_annotation_layer_with_none_labels(tmp_path) -> None:
    """Verify rendering and exporting of an AnnotationMapLayer where style.labels is None
    and style={'fill': '#ffffff', 'labels': None} without raising NameError or AssertionError."""
    from PySide6.QtCore import QMarginsF, QRect, QSize, QSizeF
    from PySide6.QtGui import QImage, QPageLayout, QPageSize, QPainter, QPdfWriter
    from PySide6.QtSvg import QSvgGenerator
    from paleo_workbench.mapping.layers import AnnotationMapLayer, MapDocument

    ann = AnnotationMapLayer(
        id="ann_none_labels",
        name="Annotation None Labels",
        style={"fill": "#ffffff", "labels": None},
    )
    ann.add_annotation("Fault Alpha", 10.0, 10.0)
    assert ann.style.get("labels") is None

    doc = MapDocument(layers=[ann])
    backend = FallbackMapRenderBackend()
    backend.initialize()
    backend.set_layer_snapshot(doc.to_snapshot())
    backend.set_extent((0.0, 0.0, 20.0, 20.0))
    backend.set_output_size(100, 100)

    # 1. Screen / Sync rendering
    frame = backend.render_sync()
    assert frame is not None
    assert (frame.width, frame.height) == (100, 100)
    pixels = np.frombuffer(frame.rgba, dtype=np.uint8).reshape(100, 100, 4)
    non_bg = int((pixels[:, :, :3] != np.array([255, 255, 255])).any(axis=-1).sum())
    assert non_bg > 0

    # 2. Raster painter export
    img = QImage(100, 100, QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(img)
    try:
        backend.render_to_painter(painter, 100, 100, dpi=96.0)
    finally:
        painter.end()
    assert not img.isNull()

    # 3. SVG vector export
    svg_path = str(tmp_path / "annotation_none_labels.svg")
    generator = QSvgGenerator()
    generator.setFileName(svg_path)
    generator.setSize(QSize(100, 100))
    generator.setViewBox(QRect(0, 0, 100, 100))
    generator.setResolution(96)
    svg_painter = QPainter(generator)
    try:
        backend.render_to_painter(svg_painter, 100, 100, dpi=96.0)
    finally:
        svg_painter.end()
    assert (tmp_path / "annotation_none_labels.svg").exists()
    assert (tmp_path / "annotation_none_labels.svg").stat().st_size > 0

    # 4. PDF vector export
    pdf_path = str(tmp_path / "annotation_none_labels.pdf")
    writer = QPdfWriter(pdf_path)
    writer.setResolution(96)
    writer.setPageLayout(
        QPageLayout(
            QPageSize(QSizeF(100, 100), QPageSize.Unit.Point),
            QPageLayout.Orientation.Portrait,
            QMarginsF(0, 0, 0, 0),
        )
    )
    pdf_painter = QPainter(writer)
    try:
        backend.render_to_painter(pdf_painter, 100, 100, dpi=96.0)
    finally:
        pdf_painter.end()
    assert (tmp_path / "annotation_none_labels.pdf").exists()
    assert (tmp_path / "annotation_none_labels.pdf").stat().st_size > 0

    backend.shutdown()

