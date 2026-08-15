"""Regression tests for #391: incremental fallback rendering.

Structural (counter/pixel) assertions only, never wall-clock thresholds:
viewport culling, identical-input frame reuse and same-scale pan-strip reuse
must produce frames pixel-identical to a full re-rasterization while skipping
raster work, and edits/zooms must invalidate reuse.
"""

from __future__ import annotations

from paleo_workbench.mapping.map_render_backend import (
    FallbackMapRenderBackend,
    MapLayerSnapshot,
    MapRenderSnapshot,
)


def _features(count: int = 400) -> tuple[dict, ...]:
    side = int(count**0.5) + 1
    rows = []
    for index in range(count):
        x = float((index % side) * 10.0)
        y = float((index // side) * 10.0)
        rows.append(
            {
                "id": f"f{index}",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[x, y], [x + 8, y], [x + 8, y + 8], [x, y + 8], [x, y]]],
                },
                "properties": {"name": f"F{index}"},
            }
        )
    return tuple(rows)


def _snapshot(features=None, *, data_revision: int = 1) -> MapRenderSnapshot:
    return MapRenderSnapshot(
        project_crs="EPSG:3857",
        layers=(
            MapLayerSnapshot(
                id="map:facies",
                name="Facies",
                layer_type="vector",
                extent=(0.0, 0.0, 220.0, 220.0),
                crs="EPSG:3857",
                data_revision=data_revision,
                style_revision=1,
                features=_features() if features is None else features,
                style={"fill": "#6c8ebf", "stroke": "#26364d", "stroke_width": 1.0},
            ),
        ),
    )


def _configure(backend, *, extent=(0.0, 0.0, 220.0, 220.0), size=(200, 160)) -> None:
    backend.set_layer_snapshot(_snapshot())
    backend.set_extent(extent)
    backend.set_output_size(*size)
    backend.set_dpi(96.0)


def _render_frame(backend, extent, *, snapshot=None) -> bytes:
    if snapshot is not None:
        backend.set_layer_snapshot(snapshot)
    backend.set_extent(extent)
    return backend.render_sync().rgba


def test_fallback_pan_strip_reuse_is_pixel_identical_to_full_render() -> None:
    pan_a = (30.0, 20.0, 230.0, 220.0)  # 200x200 map window at 200px wide
    pan_b = (40.0, 20.0, 240.0, 220.0)  # 10px right pan, same scale

    reference = FallbackMapRenderBackend()
    _configure(reference)
    full_b = _render_frame(reference, pan_b)

    incremental = FallbackMapRenderBackend()
    _configure(incremental)
    incremental.set_extent(pan_a)
    incremental.render_sync()
    incremental.set_extent(pan_b)
    reused = incremental.render_sync()

    assert reused.rgba == full_b
    diagnostics = incremental.fallback_diagnostics()
    assert diagnostics["rasterization_count"] == 1
    assert diagnostics["strip_reuse_count"] == 1


def test_fallback_identical_input_serves_the_cached_frame_without_rasterizing() -> None:
    backend = FallbackMapRenderBackend()
    _configure(backend)
    backend.set_extent((0.0, 0.0, 220.0, 220.0))

    first = backend.render_sync()
    second = backend.render_sync()
    third = backend.render_sync()

    assert second.generation > first.generation
    assert third.generation > second.generation
    assert second.rgba == first.rgba
    diagnostics = backend.fallback_diagnostics()
    assert diagnostics["rasterization_count"] == 1
    assert diagnostics["frame_cache_hits"] == 2


def test_fallback_culls_features_outside_the_viewport() -> None:
    viewport = (50.0, 50.0, 70.0, 70.0)  # shows only a few features

    full_backend = FallbackMapRenderBackend()
    _configure(full_backend)
    full_frame = _render_frame(full_backend, viewport)

    # A fresh backend whose snapshot holds exactly the visible subset must
    # produce the same pixels as culling the full snapshot.
    visible = [
        feature
        for feature in _features()
        if 45.0 <= feature["geometry"]["coordinates"][0][0][0] <= 75.0
        and 45.0 <= feature["geometry"]["coordinates"][0][0][1] <= 75.0
    ]
    subset_backend = FallbackMapRenderBackend()
    _configure(subset_backend)
    subset_backend.set_layer_snapshot(_snapshot(tuple(visible)))
    subset_frame = _render_frame(subset_backend, viewport)

    assert full_frame == subset_frame
    assert full_backend.fallback_diagnostics()["culled_feature_count"] > 0


def test_fallback_edit_invalidates_reuse_and_next_render_rasterizes() -> None:
    backend = FallbackMapRenderBackend()
    _configure(backend)
    backend.set_extent((30.0, 30.0, 230.0, 230.0))
    first = backend.render_sync()

    backend.set_layer_snapshot(_snapshot(data_revision=2))
    second = backend.render_sync()

    diagnostics = backend.fallback_diagnostics()
    assert diagnostics["rasterization_count"] == 2  # edit forces a re-raster
    assert diagnostics["strip_reuse_count"] == 0
    assert second.generation > first.generation


def test_fallback_zoom_at_a_new_scale_always_re_rasterizes() -> None:
    backend = FallbackMapRenderBackend()
    _configure(backend)
    backend.set_extent((30.0, 30.0, 230.0, 230.0))
    backend.render_sync()
    backend.set_extent((50.0, 50.0, 210.0, 210.0))  # smaller window: new scale
    backend.render_sync()

    diagnostics = backend.fallback_diagnostics()
    assert diagnostics["rasterization_count"] == 2
    assert diagnostics["strip_reuse_count"] == 0


def test_fallback_bounds_cache_survives_revision_bumps_without_rescanning_all() -> None:
    """Unchanged features keep their cached bounds after a data revision bump."""
    backend = FallbackMapRenderBackend()
    _configure(backend)
    backend.set_extent((0.0, 0.0, 220.0, 220.0))
    backend.render_sync()
    layer = backend._snapshot.layers[0]
    feature = layer.features[0]
    bounds = backend._bounds_for_feature(layer, feature)
    assert bounds is not None

    backend.set_layer_snapshot(_snapshot(data_revision=3))
    backend.render_sync()
    new_layer = backend._snapshot.layers[0]
    assert backend._bounds_for_feature(new_layer, feature) == bounds
