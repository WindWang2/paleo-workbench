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
    assert any(byte not in {24, 28, 34, 255} for byte in frame.rgba)


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


def test_qgis_backend_delivers_only_the_latest_asynchronous_frame(qtbot) -> None:
    backend = QgisMapRenderBackend()
    if not backend.is_available:
        pytest.skip("optional qgis_render_bridge is not built")
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


def test_qgis_single_symbol_style_revision_changes_rendered_vector_frame(qtbot) -> None:
    backend = QgisMapRenderBackend()
    if not backend.is_available:
        pytest.skip("optional qgis_render_bridge is not built")
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


def test_qgis_categorized_and_labeled_vector_style_uses_host_feature_attributes(qtbot) -> None:
    backend = QgisMapRenderBackend()
    if not backend.is_available:
        pytest.skip("optional qgis_render_bridge is not built")
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


def test_qgis_backend_composes_the_finished_scalar_grid_without_interpolation(qtbot) -> None:
    backend = QgisMapRenderBackend()
    if not backend.is_available:
        pytest.skip("optional qgis_render_bridge is not built")
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


def test_qgis_backend_renders_an_external_raster_reference_mirror(tmp_path, qtbot) -> None:
    backend = QgisMapRenderBackend()
    if not backend.is_available:
        pytest.skip("optional qgis_render_bridge is not built")
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


def test_qgis_display_operations_never_reinvoke_factor_interpolation(monkeypatch, qtbot) -> None:
    backend = QgisMapRenderBackend()
    if not backend.is_available:
        pytest.skip("optional qgis_render_bridge is not built")
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
    background = np.array([0x18, 0x1C, 0x22, 0xFF], dtype=int)
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
        background = np.array([0x18, 0x1C, 0x22, 0xFF], dtype=int)
        diff = np.abs(pixels - background).sum(axis=2)
        return {int(row) for row in np.where((diff > 24).any(axis=1))[0]}

    rows_96 = line_rows(96.0)
    rows_300 = line_rows(300.0)
    assert rows_96 and rows_300
    # Same vertical band center (position unchanged), wider band at 300 dpi.
    assert (min(rows_96) + max(rows_96)) // 2 == (min(rows_300) + max(rows_300)) // 2
    assert len(rows_300) > len(rows_96)
