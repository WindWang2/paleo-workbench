"""Render-backend seam tests for the unified map authoring canvas."""

from __future__ import annotations

import pytest

from paleo_workbench.mapping.map_render_backend import (
    FallbackMapRenderBackend,
    MapLayerSnapshot,
    MapRenderSnapshot,
    QgisMapRenderBackend,
)


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


def test_qgis_backend_is_explicit_when_optional_native_bridge_is_missing_or_renders_snapshot() -> None:
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
