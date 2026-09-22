"""Regression tests for #822 — fallback renderer threaded rasterisation.

ADR 0058 claimed per-frame rasterisation runs off the GUI thread; in reality
only ``_prepare_layers`` did, and ``take_completed_frame`` painted the whole
frame on the GUI thread (pan 861 ms @10k features, ~10 s @100k). The fix
rasterises geometry on the worker (label placements collected as plain data)
and paints labels during GUI-thread finalisation — no font engine is touched
off-thread (the documented Py3.13 constraint).
"""

from __future__ import annotations

import threading

import pytest

from paleo_workbench.mapping.map_render_backend import (
    FallbackMapRenderBackend,
    MapLayerSnapshot,
    MapRenderSnapshot,
)


def _labeled_snapshot(n_points: int = 200) -> MapRenderSnapshot:
    features = tuple(
        {
            "id": f"well-{i}",
            "geometry": {"type": "Point", "coordinates": [float(i % 50), float(i // 50)]},
            "properties": {"name": f"W{i}"},
        }
        for i in range(n_points)
    )
    return MapRenderSnapshot(
        project_crs="EPSG:3857",
        layers=(
            MapLayerSnapshot(
                id="wells",
                name="Wells",
                layer_type="vector",
                extent=(0.0, 0.0, 50.0, 50.0),
                crs="EPSG:3857",
                data_revision=1,
                style_revision=1,
                features=features,
                style={
                    "fill": "#55b6ff",
                    "marker_size": 6.0,
                    "labels": {"visible": True, "field": "name", "size": 8},
                },
            ),
        ),
    )


def _drive_threaded_frame(backend: FallbackMapRenderBackend):
    backend.request_render()
    frame = None
    import time

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        frame = backend.take_completed_frame()
        if frame is not None:
            break
        if not backend.render_active and frame is None:
            backend.request_render()
    return frame


def test_rasterisation_runs_off_gui_thread(qtbot, monkeypatch) -> None:
    """#822: the geometry rasterisation pass must execute on the worker
    thread, not the GUI thread that calls take_completed_frame."""
    backend = FallbackMapRenderBackend(threaded=True)
    backend.initialize()
    backend.set_output_size(400, 300)
    backend.set_layer_snapshot(_labeled_snapshot())
    backend.set_extent((0.0, 0.0, 50.0, 50.0))

    raster_threads: list[str] = []
    original = backend._rasterize_frame_offthread

    def _probe():
        raster_threads.append(threading.current_thread().name)
        return original()

    monkeypatch.setattr(backend, "_rasterize_frame_offthread", _probe)

    frame = _drive_threaded_frame(backend)
    assert frame is not None
    assert raster_threads, "rasterisation never ran"
    assert all(t != threading.main_thread().name for t in raster_threads)
    backend.shutdown()


def test_label_painting_runs_on_gui_thread(qtbot, monkeypatch) -> None:
    """The only font work — collected label specs — must paint on the GUI
    thread (Py3.13 font-thread constraint documented at _prepare_layers)."""
    backend = FallbackMapRenderBackend(threaded=True)
    backend.initialize()
    backend.set_output_size(400, 300)
    backend.set_layer_snapshot(_labeled_snapshot())
    backend.set_extent((0.0, 0.0, 50.0, 50.0))

    label_threads: list[str] = []
    original = backend._paint_label_specs

    def _probe(painter, specs):
        label_threads.append(threading.current_thread().name)
        return original(painter, specs)

    monkeypatch.setattr(backend, "_paint_label_specs", _probe)

    frame = _drive_threaded_frame(backend)
    assert frame is not None
    assert label_threads, "labels never painted"
    assert all(t == threading.main_thread().name for t in label_threads)
    backend.shutdown()


def test_threaded_frame_matches_synchronous_bytes() -> None:
    """Sync and threaded paths must produce byte-identical frames (both order
    geometry-then-labels), keeping the test contract honest."""
    sync = FallbackMapRenderBackend(threaded=False)
    sync.initialize()
    sync.set_output_size(400, 300)
    sync.set_layer_snapshot(_labeled_snapshot())
    sync.set_extent((0.0, 0.0, 50.0, 50.0))
    sync.request_render()
    sync_frame = sync.take_completed_frame()
    assert sync_frame is not None

    threaded = FallbackMapRenderBackend(threaded=True)
    threaded.initialize()
    threaded.set_output_size(400, 300)
    threaded.set_layer_snapshot(_labeled_snapshot())
    threaded.set_extent((0.0, 0.0, 50.0, 50.0))
    thread_frame = _drive_threaded_frame(threaded)

    assert thread_frame is not None
    assert thread_frame.rgba == sync_frame.rgba
    assert (thread_frame.width, thread_frame.height) == (sync_frame.width, sync_frame.height)
    threaded.shutdown()
    sync.shutdown()


def test_labels_present_in_output() -> None:
    """The deferred label pass really paints: labeled frames differ from the
    same composition with labels disabled."""
    backend = FallbackMapRenderBackend(threaded=False)
    backend.initialize()
    backend.set_output_size(400, 300)
    backend.set_layer_snapshot(_labeled_snapshot())
    backend.set_extent((0.0, 0.0, 50.0, 50.0))
    backend.request_render()
    labeled = backend.take_completed_frame()

    plain = _labeled_snapshot()
    style = dict(plain.layers[0].style)
    style["labels"] = {"visible": False, "field": "name", "size": 8}
    from dataclasses import replace

    plain = replace(plain, layers=(replace(plain.layers[0], style=style, style_revision=2),))
    backend.set_layer_snapshot(plain)
    backend.request_render()
    unlabeled = backend.take_completed_frame()

    assert labeled is not None and unlabeled is not None
    assert labeled.rgba != unlabeled.rgba
    backend.shutdown()
