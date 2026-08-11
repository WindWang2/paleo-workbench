"""Optional native QGIS bridge contract, exercised only when built locally."""

from __future__ import annotations

import pytest


qgis_render_bridge = pytest.importorskip("qgis_render_bridge")


def test_qgis_bridge_renders_a_memory_vector_layer(qtbot):
    bridge = qgis_render_bridge.QgisRenderBridge()
    bridge.initialize()
    try:
        bridge.set_layer_snapshot(
            [
                {
                    "id": "facies",
                    "name": "Facies",
                    "crs": "EPSG:3857",
                    "data_revision": 1,
                    "style_revision": 1,
                    "visible": True,
                    "opacity": 1.0,
                    "features": [
                        {"id": "f1", "wkt": "POLYGON ((0 0, 10 0, 10 10, 0 10, 0 0))"}
                    ],
                }
            ],
            "EPSG:3857",
        )
        frame = bridge.render_sync((0.0, 0.0, 10.0, 10.0), 160, 120, 96.0)
    finally:
        bridge.shutdown()

    assert frame["width"] == 160
    assert frame["height"] == 120
    assert frame["stride"] >= 640
    assert len(frame["rgba"]) == frame["height"] * frame["stride"]


def test_qgis_bridge_can_be_reopened_without_reinitializing_qgis(qtbot):
    """Bridge lifetime is shorter than the process-wide QGIS runtime."""
    for _ in range(2):
        bridge = qgis_render_bridge.QgisRenderBridge()
        bridge.initialize()
        try:
            bridge.set_layer_snapshot(
                [
                    {
                        "id": "points",
                        "name": "Points",
                        "crs": "EPSG:3857",
                        "data_revision": 1,
                        "style_revision": 1,
                        "visible": True,
                        "opacity": 1.0,
                        "features": [{"id": "p1", "wkt": "POINT (5 5)"}],
                    }
                ],
                "EPSG:3857",
            )
            frame = bridge.render_sync((0.0, 0.0, 10.0, 10.0), 32, 32, 96.0)
            assert len(frame["rgba"]) == frame["height"] * frame["stride"]
        finally:
            bridge.shutdown()


def test_qgis_bridge_coalesces_asynchronous_render_generations(qtbot):
    bridge = qgis_render_bridge.QgisRenderBridge()
    bridge.initialize()
    try:
        bridge.set_layer_snapshot(
            [
                {
                    "id": "facies",
                    "name": "Facies",
                    "crs": "EPSG:3857",
                    "data_revision": 1,
                    "style_revision": 1,
                    "visible": True,
                    "opacity": 1.0,
                    "features": [
                        {"id": "f1", "wkt": "POLYGON ((0 0, 10 0, 10 10, 0 10, 0 0))"}
                    ],
                }
            ],
            "EPSG:3857",
        )
        bridge.request_render((0.0, 0.0, 10.0, 10.0), 512, 512, 96.0, 1)
        bridge.request_render((1.0, 1.0, 9.0, 9.0), 256, 256, 96.0, 2)

        frame = None

        def take_newest_frame():
            nonlocal frame
            frame = bridge.take_completed_frame()
            return frame is not None

        qtbot.waitUntil(take_newest_frame, timeout=5_000)
    finally:
        bridge.shutdown()

    assert frame is not None
    assert frame["generation"] == 2
    assert (frame["width"], frame["height"]) == (256, 256)
