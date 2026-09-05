"""Optional native QGIS bridge contract, exercised only when built locally.

Opt-in path (packaging #437): build the vendored-QGIS bridge with
``PALEO_WITH_QGIS_RENDERER=1 python -m pip install -e native/qgis_render_bridge``
and select these tests with ``pytest -m qgis``. The main CI gate does not
build QGIS, so the module self-skips there.
"""

from __future__ import annotations

import pytest

from tests.qgis_support import QGIS_SKIP_REASON

pytestmark = pytest.mark.qgis

qgis_render_bridge = pytest.importorskip("qgis_render_bridge", reason=QGIS_SKIP_REASON)


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


def _layer(layer_id, name, wkt, data_revision=1, style_revision=1):
    return {
        "id": layer_id,
        "name": name,
        "crs": "EPSG:3857",
        "data_revision": data_revision,
        "style_revision": style_revision,
        "visible": True,
        "opacity": 1.0,
        "features": [{"id": f"{layer_id}-f1", "wkt": wkt}],
    }


def test_qgis_bridge_failed_snapshot_keeps_previous_layers(qtbot):
    """#519: a throwing apply_snapshot must not delete previously valid layers.

    The old code moved reused layers out of the live registry before the whole
    snapshot validated; a later throw deleted them (and could leave null
    pointers that settings_for() handed to QGIS). The registry must be
    unchanged by a failed snapshot: the same render stays byte-identical.
    """
    bridge = qgis_render_bridge.QgisRenderBridge()
    bridge.initialize()
    try:
        good = [
            _layer("a", "A", "POLYGON ((0 0, 10 0, 10 10, 0 10, 0 0))"),
            _layer("b", "B", "POLYGON ((20 0, 30 0, 30 10, 20 10, 20 0))"),
        ]
        bridge.set_layer_snapshot(good, "EPSG:3857")
        before = bridge.render_sync((0.0, 0.0, 30.0, 10.0), 160, 120, 96.0)

        # A is reused (revision unchanged); B is rebuilt and carries invalid
        # WKT, so the second snapshot throws after A was already processed.
        bad = [
            good[0],
            _layer("b", "B", "NOT VALID WKT", data_revision=2),
        ]
        with pytest.raises(Exception):
            bridge.set_layer_snapshot(bad, "EPSG:3857")

        # The previously valid registry must render IDENTICALLY: the failed
        # snapshot must not have deleted layer A or nulled any mirror.
        after = bridge.render_sync((0.0, 0.0, 30.0, 10.0), 160, 120, 96.0)
        assert after["width"] == before["width"]
        assert after["height"] == before["height"]
        assert after["rgba"] == before["rgba"]
    finally:
        bridge.shutdown()


def test_qgis_bridge_failed_pending_snapshot_does_not_swallow_next_render(qtbot):
    """#519: a failed queued snapshot must clear the queued render so the next
    completed frame is delivered instead of being discarded as superseded.

    The sequence is deterministic: the async job is polled until it has
    finished WITHOUT draining it, so the bad snapshot is applied from the
    pending queue — the only path that could leave a stale pending_request.
    """
    bridge = qgis_render_bridge.QgisRenderBridge()
    bridge.initialize()
    try:
        good = [
            _layer("a", "A", "POLYGON ((0 0, 10 0, 10 10, 0 10, 0 0))"),
            _layer("b", "B", "POLYGON ((20 0, 30 0, 30 10, 20 10, 20 0))"),
        ]
        # A is reused (revision unchanged), B is rebuilt with invalid WKT:
        # the failed apply corrupts the registry on the old code path.
        bad = [
            good[0],
            _layer("b", "B", "NOT VALID WKT", data_revision=2),
        ]

        bridge.set_layer_snapshot(good, "EPSG:3857")
        # Many small polygons + a big output keep the async job alive long
        # enough for the bad snapshot + newer render to be QUEUED behind it.
        many = [
            {
                "id": f"p{i}",
                "name": f"P{i}",
                "crs": "EPSG:3857",
                "data_revision": 1,
                "style_revision": 1,
                "visible": True,
                "opacity": 1.0,
                "features": [
                    {
                        "id": f"p{i}-f1",
                        "wkt": (
                            f"POLYGON (({i % 40} {(i // 40) % 40}, "
                            f"{i % 40 + 1} {(i // 40) % 40}, "
                            f"{i % 40 + 1} {(i // 40) % 40 + 1}, "
                            f"{i % 40} {(i // 40) % 40 + 1}, "
                            f"{i % 40} {(i // 40) % 40}))"
                        ),
                    }
                ],
            }
            for i in range(2000)
        ]
        bridge.set_layer_snapshot(many, "EPSG:3857")
        bridge.request_render((0.0, 0.0, 40.0, 50.0), 1024, 1024, 96.0, 1)
        # Queue the bad snapshot + a newer render while the job is active.
        bridge.set_layer_snapshot(bad, "EPSG:3857")
        bridge.request_render((0.0, 0.0, 40.0, 50.0), 1024, 1024, 96.0, 2)

        # Wait for the job to finish WITHOUT draining it, then drain: the
        # pending bad snapshot is applied here and must raise.
        qtbot.waitUntil(lambda: not bridge.render_active, timeout=30_000)
        with pytest.raises(Exception):
            bridge.take_completed_frame()

        # A fresh snapshot + render must now deliver ITS frame with the right
        # generation (the failed snapshot must not have poisoned the queue).
        bridge.set_layer_snapshot(good, "EPSG:3857")
        bridge.request_render((0.0, 0.0, 40.0, 50.0), 1024, 1024, 96.0, 3)
        frame = None

        def take_newest():
            nonlocal frame
            frame = bridge.take_completed_frame()
            return frame is not None

        qtbot.waitUntil(take_newest, timeout=30_000)
        assert frame["generation"] == 3
    finally:
        bridge.shutdown()


def test_concurrent_render_and_shutdown_never_corrupts(qtbot):
    """#1133: GIL-released render_sync racing shutdown() must serialize —
    every render either completes or raises RuntimeError, never UAF."""
    import threading

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
        outcomes: list[str] = []
        stop = threading.Event()

        def _render_loop() -> None:
            while not stop.is_set():
                try:
                    frame = bridge.render_sync((0.0, 0.0, 10.0, 10.0), 64, 48, 96.0)
                    assert len(frame["rgba"]) == frame["height"] * frame["stride"]
                    outcomes.append("ok")
                except RuntimeError:
                    outcomes.append("rejected")

        workers = [threading.Thread(target=_render_loop) for _ in range(4)]
        for w in workers:
            w.start()
        qtbot.wait(500)
        bridge.shutdown()
        stop.set()
        for w in workers:
            w.join(timeout=30)
            assert not w.is_alive()
        assert outcomes, "renders must have run before shutdown"
        assert all(o in ("ok", "rejected") for o in outcomes)
    finally:
        try:
            bridge.shutdown()
        except Exception:
            pass
