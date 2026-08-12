"""Frame ownership and navigation request coalescing tests."""

from __future__ import annotations

from paleo_workbench.mapping.map_render_backend import FallbackMapRenderBackend
from paleo_workbench.ui.unified_map_canvas import UnifiedMapCanvas
from tests.test_unified_map_canvas import _snapshot


def test_canvas_keeps_the_borrowed_rgba_payload_alive_for_qimage(qtbot) -> None:
    canvas = UnifiedMapCanvas(backend=FallbackMapRenderBackend())
    qtbot.addWidget(canvas)
    canvas.resize(320, 180)
    canvas.show()
    canvas.set_layer_snapshot(_snapshot())
    canvas.set_extent((0.0, 0.0, 10.0, 10.0))
    qtbot.waitUntil(lambda: canvas.last_frame is not None, timeout=2_000)

    frame = canvas.last_frame
    assert frame is not None
    assert canvas._image_buffer is frame.rgba
    canvas._last_frame = None
    assert not canvas._image.isNull()
    assert canvas._image.pixelColor(0, 0).isValid()


def test_rapid_pan_coalesces_to_one_final_render_while_preview_stays_immediate(qtbot) -> None:
    canvas = UnifiedMapCanvas(backend=FallbackMapRenderBackend())
    qtbot.addWidget(canvas)
    canvas.resize(320, 180)
    canvas.show()
    canvas.set_layer_snapshot(_snapshot())
    canvas.set_extent((0.0, 0.0, 10.0, 10.0))
    qtbot.waitUntil(lambda: canvas.last_frame is not None, timeout=2_000)
    before = canvas.frame_delivery_diagnostics()

    for _ in range(100):
        canvas.pan_by_pixels(2.0, 0.0)

    assert canvas.navigation_preview_active
    assert canvas.frame_delivery_diagnostics()["render_requests"] == before["render_requests"]
    qtbot.waitUntil(
        lambda: canvas.frame_delivery_diagnostics()["frames_delivered"] == before["frames_delivered"] + 1,
        timeout=2_000,
    )
    after = canvas.frame_delivery_diagnostics()
    assert after["render_requests"] == before["render_requests"] + 1


def test_wheel_equivalent_zoom_burst_coalesces_to_one_final_render(qtbot) -> None:
    canvas = UnifiedMapCanvas(backend=FallbackMapRenderBackend())
    qtbot.addWidget(canvas)
    canvas.resize(320, 180)
    canvas.show()
    canvas.set_layer_snapshot(_snapshot())
    canvas.set_extent((0.0, 0.0, 10.0, 10.0))
    qtbot.waitUntil(lambda: canvas.last_frame is not None, timeout=2_000)
    before = canvas.frame_delivery_diagnostics()

    for _ in range(30):
        canvas.zoom_by(0.8, coalesce_history=True)

    assert canvas.navigation_preview_active
    assert canvas.frame_delivery_diagnostics()["render_requests"] == before["render_requests"]
    qtbot.waitUntil(
        lambda: canvas.frame_delivery_diagnostics()["frames_delivered"] == before["frames_delivered"] + 1,
        timeout=2_000,
    )
    assert canvas.frame_delivery_diagnostics()["render_requests"] == before["render_requests"] + 1
