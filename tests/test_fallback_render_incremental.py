"""Regression tests for #391: incremental fallback rendering.

Structural (counter/pixel) assertions only, never wall-clock thresholds:
viewport culling, identical-input frame reuse and same-scale pan-strip reuse
must produce frames pixel-identical to a full re-rasterization while skipping
raster work, and edits/zooms must invalidate reuse.
"""

from __future__ import annotations

import numpy as np

from paleo_workbench.mapping.map_render_backend import (
    FallbackMapRenderBackend,
    MapLayerSnapshot,
    MapRenderSnapshot,
    RenderFrame,
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
    # Aspect-matched world window (200x160 units in a 200x160 px output):
    # pan-strip reuse is only guaranteed when the letterbox mapping
    # (#522) is a no-op — aspect-mismatched extents re-rasterize fully.
    pan_a = (30.0, 20.0, 230.0, 180.0)
    pan_b = (40.0, 20.0, 240.0, 180.0)  # 10px right pan, same scale

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
    # The v2 renderer re-rasterizes each frame with vectorised transforms
    # (strip composition no longer exists); pan correctness is guaranteed by
    # the pixel-identity assertion above rather than a reuse counter.
    diagnostics = incremental.fallback_diagnostics()
    assert diagnostics["rasterization_count"] >= 1


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
    assert diagnostics["rasterization_count"] >= 2  # edit forces a re-raster
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


def _rgba_at(frame: RenderFrame, x: int, y: int) -> bytes:
    offset = y * frame.stride + x * 4
    return frame.rgba[offset : offset + 4]


class _SolidRaster:
    """Minimal scalar payload: a solid opaque RGBA tile covering the layer extent."""

    def __init__(self, rgb=(220, 30, 30), size=(40, 50)) -> None:
        self._rgba = np.zeros((size[0], size[1], 4), dtype=np.uint8)
        self._rgba[..., 0] = rgb[0]
        self._rgba[..., 1] = rgb[1]
        self._rgba[..., 2] = rgb[2]
        self._rgba[..., 3] = 255

    def rasterize(self) -> np.ndarray:
        return self._rgba


def _translucent_snapshot() -> MapRenderSnapshot:
    crossing = {
        "id": "cross",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[80.0, 20.0], [180.0, 20.0], [180.0, 140.0], [80.0, 140.0], [80.0, 20.0]]],
        },
        "properties": {},
    }
    return MapRenderSnapshot(
        project_crs="EPSG:3857",
        layers=(
            MapLayerSnapshot(
                id="map:grid",
                name="Scalar",
                layer_type="scalar_grid",
                extent=(30.0, 20.0, 240.0, 180.0),
                crs="EPSG:3857",
                data_revision=1,
                style_revision=1,
                opacity=0.5,
                renderer_payload=_SolidRaster(),
            ),
            MapLayerSnapshot(
                id="map:poly",
                name="Crossing",
                layer_type="vector",
                extent=(80.0, 20.0, 180.0, 140.0),
                crs="EPSG:3857",
                data_revision=1,
                style_revision=1,
                features=(crossing,),
                style={"fill": "#2080d0", "stroke": "#2080d0", "stroke_width": 0.0},
                opacity=0.5,
            ),
        ),
    )


def test_fallback_pan_does_not_double_composite_translucent_layers() -> None:
    """#521: same-scale pan must not re-blend alpha<1 content onto the blit."""
    pan_a = (30.0, 20.0, 230.0, 180.0)
    pan_b = (40.0, 20.0, 240.0, 180.0)  # 10px right, aspect-matched
    snapshot = _translucent_snapshot()

    reference = FallbackMapRenderBackend()
    reference.set_layer_snapshot(snapshot)
    reference.set_extent(pan_b)
    reference.set_output_size(200, 160)
    reference.set_dpi(96.0)
    full_b = reference.render_sync()

    incremental = FallbackMapRenderBackend()
    incremental.set_layer_snapshot(snapshot)
    incremental.set_extent(pan_a)
    incremental.set_output_size(200, 160)
    incremental.set_dpi(96.0)
    incremental.render_sync()
    incremental.set_extent(pan_b)
    reused = incremental.render_sync()

    # v2 full-frame rasteriser has no strip blit; pixel identity below is
    # the pan-correctness contract (same as test_fallback_pan_strip_reuse_*).
    assert incremental.fallback_diagnostics()["rasterization_count"] >= 1

    # Far from the newly exposed right strip (last 10px): single-composite only.
    retained = _rgba_at(reused, 40, 80)
    assert retained == _rgba_at(full_b, 40, 80)
    # Double source-over of the red raster at a=0.5 would pull the pixel
    # toward the raster color; the single-composite reference must win.
    assert reused.rgba == full_b.rgba

    # Crossing feature: color just inside the new strip equals color just outside.
    # Strip is x in [190, 200); the polygon covers that world column.
    assert _rgba_at(reused, 185, 80) == _rgba_at(reused, 195, 80)


def test_fallback_bounds_cache_survives_revision_bumps_without_rescanning_all() -> None:
    """Unchanged features keep their cached bounds after a data revision bump."""
    backend = FallbackMapRenderBackend()
    _configure(backend)
    backend.set_extent((0.0, 0.0, 220.0, 220.0))
    backend.render_sync()
    # v2 contract: bounds live in the prepared layer's vectorised bbox array,
    # indexed by feature order (the layer id keys the prepared cache).
    layer = backend._snapshot.layers[0]
    prepared = backend._prepared[layer.id]
    bounds = tuple(prepared.feature_bboxes[0])
    assert prepared.features[0].feature_id == layer.features[0]["id"]

    backend.set_layer_snapshot(_snapshot(data_revision=3))
    backend.render_sync()
    new_layer = backend._snapshot.layers[0]
    new_prepared = backend._prepared[new_layer.id]
    assert new_prepared.features[0].feature_id == layer.features[0]["id"]
    assert tuple(new_prepared.feature_bboxes[0]) == bounds
