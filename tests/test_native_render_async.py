"""Async native-raster delivery, stale-result suppression, and cache contract."""

from __future__ import annotations

import threading

import numpy as np
from PySide6.QtCore import QCoreApplication, QThread

from paleo_workbench.ui.native_map_canvas import NativeMapCanvas
from paleo_workbench.ui.native_render_worker import NativeRasterRequestController

from tests.test_native_map_canvas import _scene


class _BlockingScalar:
    """Thread-safe enough fake that makes cancellation delivery deterministic."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release_first = threading.Event()
        self.calls = 0
        self.worker_thread = None

    def rasterize(self):
        self.worker_thread = QThread.currentThread()
        self.calls += 1
        if self.calls == 1:
            self.started.set()
            assert self.release_first.wait(2.0)
        return np.full((2, 2, 4), self.calls, dtype=np.uint8)


def test_latest_scalar_revision_suppresses_stale_async_delivery(qtbot):
    controller = NativeRasterRequestController()
    scalar = _BlockingScalar()
    delivered = []
    controller.raster_ready.connect(
        lambda request, rgba: delivered.append((request.raster_key, int(rgba[0, 0, 0])))
    )
    try:
        controller.request(
            scene_epoch=1, layer_id="surface", raster_key=(1, 1), scalar=scalar
        )
        assert scalar.started.wait(1.0)
        # Revisions changed while the first bounded C++ call is active. It may finish,
        # but its result is cancellation-suppressed; only the newer key can reach Qt.
        controller.request(
            scene_epoch=1, layer_id="surface", raster_key=(1, 2), scalar=scalar
        )
        scalar.release_first.set()
        qtbot.waitUntil(lambda: delivered == [((1, 2), 2)], timeout=3000)
        assert scalar.calls == 2
        assert scalar.worker_thread is not QCoreApplication.instance().thread()
    finally:
        controller.shutdown()


def test_scene_invalidation_discards_active_result(qtbot):
    controller = NativeRasterRequestController()
    scalar = _BlockingScalar()
    delivered = []
    controller.raster_ready.connect(lambda request, rgba: delivered.append(request))
    try:
        controller.request(
            scene_epoch=1, layer_id="surface", raster_key=(1, 1), scalar=scalar
        )
        assert scalar.started.wait(1.0)
        controller.invalidate()
        scalar.release_first.set()
        qtbot.waitUntil(lambda: not controller.is_running, timeout=3000)
        assert delivered == []
    finally:
        controller.shutdown()


def test_pan_zoom_and_opacity_reuse_completed_native_image_cache(qtbot):
    scene = _scene()
    canvas = NativeMapCanvas(scene)
    qtbot.addWidget(canvas)
    canvas.resize(360, 220)
    canvas.show()
    scalar = scene.scalar_layer("surface")

    canvas.grab()
    qtbot.waitUntil(
        lambda: scalar.rasterize_count == 1 and "surface" in canvas._image_cache,
        timeout=3000,
    )
    first_key = canvas._image_cache["surface"][0]

    canvas.zoom_by(0.7)
    canvas.pan_by_pixels(24, 12)
    scene.set_layer_opacity("surface", 0.4)
    canvas.grab()
    qtbot.wait(30)
    assert scalar.rasterize_count == 1
    assert canvas._image_cache["surface"][0] == first_key
