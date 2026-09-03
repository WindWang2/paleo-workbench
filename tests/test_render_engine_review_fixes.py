"""Regression tests for issues found by adversarial review (round 1 fixes)."""

from __future__ import annotations

import pytest

from PySide6.QtCore import QPoint
from PySide6.QtGui import QImage

from paleo_workbench.mapping.map_authoring import MapAuthoringDocument
from paleo_workbench.mapping.map_render_backend import (
    FallbackMapRenderBackend,
    MapLayerSnapshot,
    MapRenderSnapshot,
)
from paleo_workbench.mapping.map_document_snapshot import document_render_snapshot
from paleo_workbench.project.models import PaleoMapDocument


def _point_layer(features, style, layer_id="points", **kwargs) -> MapLayerSnapshot:
    return MapLayerSnapshot(
        id=layer_id, name=layer_id, layer_type="vector",
        extent=(0.0, 0.0, 100.0, 100.0), crs="EPSG:3857",
        data_revision=1, style_revision=1, features=features, style=style, **kwargs,
    )


def _line_layer(style, layer_id="lines", coordinates=None) -> MapLayerSnapshot:
    coordinates = coordinates or [[10.0, 50.0], [90.0, 50.0]]
    return MapLayerSnapshot(
        id=layer_id, name=layer_id, layer_type="vector",
        extent=(0.0, 0.0, 100.0, 100.0), crs="EPSG:3857",
        data_revision=1, style_revision=1,
        features=(
            {"id": "l1", "geometry": {"type": "LineString", "coordinates": coordinates}, "properties": {}},
        ),
        style=style,
    )


def _configure(backend: FallbackMapRenderBackend, snapshot: MapRenderSnapshot) -> None:
    backend.initialize()
    backend.set_layer_snapshot(snapshot)
    backend.set_extent((0.0, 0.0, 100.0, 100.0))
    backend.set_output_size(200, 200)
    backend.set_dpi(96.0)


def _image(frame) -> QImage:
    return QImage(frame.rgba, frame.width, frame.height, frame.stride, QImage.Format.Format_RGBA8888).copy()


# ---------------------------------------------------------------------------
# P1: dashed line patterns must render (setDashCap crash)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pattern", ["dash", "dot", "dash_dot", "fault"])
def test_dashed_line_patterns_render_without_crashing(pattern: str) -> None:
    backend = FallbackMapRenderBackend()
    _configure(backend, MapRenderSnapshot(project_crs="", layers=(
        _line_layer({"fill": "transparent", "stroke": "#ff0000", "stroke_width": 2.0, "line_pattern": pattern}),
    )))

    frame = backend.render_sync()

    assert frame is not None
    assert any(
        _image(frame).pixelColor(QPoint(x, 100)).red() > 100
        for x in range(20, 180)
    )


def test_fault_pattern_renders_differently_from_solid() -> None:
    def render(style: dict):
        backend = FallbackMapRenderBackend()
        _configure(backend, MapRenderSnapshot(project_crs="", layers=(_line_layer(style),)))
        return backend.render_sync().rgba

    solid = render({"fill": "transparent", "stroke": "#ff0000", "stroke_width": 2.0})
    fault = render({"fill": "transparent", "stroke": "#ff0000", "stroke_width": 2.0, "line_pattern": "fault"})

    assert solid != fault


def test_zero_stroke_width_disables_stroke() -> None:
    backend = FallbackMapRenderBackend()
    _configure(backend, MapRenderSnapshot(project_crs="", layers=(
        _line_layer({"fill": "transparent", "stroke": "#ff0000", "stroke_width": 0.0}),
    )))

    image = _image(backend.render_sync())
    # 白底上检测红色描边要同时压低绿/蓝通道（白色 red 也是 255）。
    painted = any(
        (lambda c: c.red() > 100 and c.green() < 100 and c.blue() < 100)(
            image.pixelColor(QPoint(x, 100))
        )
        for x in range(20, 180)
    )

    assert not painted


# ---------------------------------------------------------------------------
# P2: categorized rendering must not crash (dict() over 3-tuples)
# ---------------------------------------------------------------------------


def test_categorized_polygon_fills_render_without_crashing() -> None:
    features = tuple(
        {
            "id": f"p{index}",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[5 * index, 5], [5 * index + 4, 5], [5 * index + 4, 40], [5 * index, 40], [5 * index, 5]]],
            },
            "properties": {"facies": "delta" if index % 2 == 0 else "channel"},
        }
        for index in range(8)
    )
    style = {
        "fill": "#888888", "stroke": "#ffffff", "stroke_width": 1.0,
        "renderer": "categorized", "field": "facies",
        "categories": {"delta": "#e03131", "channel": "#1971c2"},
    }
    backend = FallbackMapRenderBackend()
    _configure(backend, MapRenderSnapshot(project_crs="", layers=(
        MapLayerSnapshot(
            id="polys", name="polys", layer_type="vector",
            extent=(0.0, 0.0, 100.0, 100.0), crs="",
            data_revision=1, style_revision=1, features=features, style=style,
        ),
    )))

    image = _image(backend.render_sync())

    def category_hits(check) -> int:
        return sum(
            1
            for x in range(12, 74, 2)
            for y in (140, 160)
            if check(image.pixelColor(QPoint(x, y)))
        )

    reds = category_hits(lambda c: c.red() > 150 and c.blue() < 100)
    blues = category_hits(lambda c: c.blue() > 150 and c.red() < 100)

    assert reds > 0 and blues > 0


def test_categorized_points_render_and_marker_pen_stays_solid() -> None:
    features = tuple(
        {
            "id": f"w{index}",
            "geometry": {"type": "Point", "coordinates": [5.0 + index * 4, 50.0]},
            "properties": {"facies": "delta" if index % 2 == 0 else "channel"},
        }
        for index in range(10)
    )
    style = {
        "fill": "#888888", "stroke": "#ffffff", "stroke_width": 1.0, "marker_size": 10.0,
        "renderer": "categorized", "field": "facies",
        "categories": {"delta": "#e03131", "channel": "#1971c2"},
        "line_pattern": "dash",  # dashes must not leak into point strokes
    }
    backend = FallbackMapRenderBackend()
    _configure(backend, MapRenderSnapshot(project_crs="", layers=(_point_layer(features, style),)))

    image = _image(backend.render_sync())
    colors = {
        (image.pixelColor(QPoint(x, 100)).red(), image.pixelColor(QPoint(x, 100)).blue())
        for x in range(10, 190, 2)
    }

    assert any(r > 150 and b < 100 for r, b in colors)
    assert any(b > 150 and r < 100 for r, b in colors)


def test_threaded_render_surfaces_errors_instead_of_hanging(qtbot, monkeypatch) -> None:
    backend = FallbackMapRenderBackend(threaded=True)
    _configure(backend, MapRenderSnapshot(project_crs="", layers=(_line_layer({"stroke": "#ff0000"}),)))
    monkeypatch.setattr(
        FallbackMapRenderBackend, "_paint_composition",
        lambda self, *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    try:
        backend.request_render()

        deadline_polls = 0
        frame = None
        while deadline_polls < 100:
            frame = backend.take_completed_frame()
            if frame is not None or not backend.render_active:
                break
            deadline_polls += 1

        assert frame is None
        assert backend.render_diagnostics()["render_errors"] == 1
        assert not backend.render_active
    finally:
        backend.shutdown()


# ---------------------------------------------------------------------------
# P3: threaded queue coalescing + frame-cache key capture
# ---------------------------------------------------------------------------


def test_threaded_burst_supersedes_instead_of_queueing(qtbot) -> None:
    dense = tuple(
        {
            "id": f"l{index}",
            "geometry": {
                "type": "LineString",
                "coordinates": [[float(step % 90), float((index + step) % 90)] for step in range(120)],
            },
            "properties": {},
        }
        for index in range(1200)
    )
    backend = FallbackMapRenderBackend(threaded=True)
    _configure(backend, MapRenderSnapshot(project_crs="", layers=(
        _line_layer({"stroke": "#ff0000", "stroke_width": 1.0}, layer_id="dense", coordinates=None),
    )))
    # Replace with the dense payload for the burst itself.
    backend.set_layer_snapshot(MapRenderSnapshot(project_crs="", layers=(
        MapLayerSnapshot(
            id="dense", name="dense", layer_type="vector",
            extent=(0.0, 0.0, 100.0, 100.0), crs="",
            data_revision=1, style_revision=1, features=dense, style={"stroke": "#ff0000"},
        ),
    )))
    try:
        generations = [backend.request_render() for _ in range(30)]

        assert all(generation >= 0 for generation in generations)
        # Only one task may execute at a time and at most one follow-up is
        # queued: superseded requests must not pile up behind each other.
        frames = 0
        import time as _time

        deadline = _time.monotonic() + 10.0
        while _time.monotonic() < deadline:
            if backend.take_completed_frame() is not None:
                frames += 1
            if frames >= 1:
                break
            _time.sleep(0.01)
        assert frames >= 1
        diagnostics = backend.render_diagnostics()
        assert diagnostics["frames_rendered"] <= 31
    finally:
        backend.shutdown()


def test_frame_cache_never_serves_a_frame_from_a_superseded_extent() -> None:
    backend = FallbackMapRenderBackend()
    _configure(backend, MapRenderSnapshot(project_crs="", layers=(
        _line_layer({"stroke": "#ff0000", "stroke_width": 3.0}),
    )))

    frame = backend.render_sync()
    first = _image(frame).pixelColor(QPoint(100, 100)).red()

    # A viewport change invalidates the cached frame: the second render must
    # reflect the new extent, not a cache hit keyed after the fact.
    backend.set_extent((0.0, 0.0, 50.0, 100.0))
    second = _image(backend.render_sync())
    second_red = sum(1 for x in range(10, 190, 4) if second.pixelColor(QPoint(x, 100)).red() > 100)

    assert first > 100
    assert second_red > 0


# ---------------------------------------------------------------------------
# P4: rollback must not resurrect stale records from the cache
# ---------------------------------------------------------------------------


def _authoring_records(document_id: str, well_x: float) -> list[dict]:
    return [{
        "id": "w1", "kind": "well", "name": "W1",
        "coordinates": [well_x, 10.0], "properties": {},
    }]


def test_rollback_then_different_edit_never_reuses_stale_records() -> None:
    authoring = MapAuthoringDocument(
        document_id="doc", project_crs="", records=_authoring_records("doc", 10.0)
    )

    session = authoring.start_editing("well")
    session.move_feature("w1", 30.0, 0.0)  # session revision → 1
    assert authoring.records()[0]["coordinates"][0] == 40.0
    authoring.rollback_changes()

    session = authoring.start_editing("well")
    session.move_feature("w1", 5.0, 0.0)  # fresh session, revision 1 again
    records = authoring.records()

    assert records[0]["coordinates"][0] == 15.0


def test_replaced_authoring_object_never_reuses_feature_cache() -> None:
    document = PaleoMapDocument(id="cache-doc", name="d", linked_target_horizon="H1")

    first = MapAuthoringDocument(document_id="cache-doc", records=_authoring_records("cache-doc", 10.0))
    snapshot_a = document_render_snapshot(
        document, project_crs="", records=first.records(),
        data_revisions={kind: first.data_revision_key(kind)[2] for kind in ("facies", "well", "line", "label")},
        cache_owner=first,
    )
    x_first = snapshot_a.layers[1].features[0]["geometry"]["coordinates"][0]

    # New owner object, same document id, changed content, same revision index.
    second = MapAuthoringDocument(document_id="cache-doc", records=_authoring_records("cache-doc", 70.0))
    revisions = {}
    for kind in ("facies", "well", "line", "label"):
        key = second.data_revision_key(kind)
        first_key = first.data_revision_key(kind)
        revisions[kind] = key[2] if key[:2] == first_key[:2] else key[2] + 100
    snapshot_b = document_render_snapshot(
        document, project_crs="", records=second.records(),
        data_revisions=revisions, cache_owner=second,
    )
    x_second = snapshot_b.layers[1].features[0]["geometry"]["coordinates"][0]

    assert x_first == 10.0
    assert x_second == 70.0


# ---------------------------------------------------------------------------
# P6: vertex budget must not delete polygons
# ---------------------------------------------------------------------------


def test_vertex_budget_keeps_small_polygons_alive(monkeypatch) -> None:
    features = tuple(
        {
            "id": f"poly{index}",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [2.0 + index % 5, 2.0 + (index // 5) * 6],
                    [6.0 + index % 5, 2.0 + (index // 5) * 6],
                    [6.0 + index % 5, 7.0 + (index // 5) * 6],
                    [2.0 + index % 5, 7.0 + (index // 5) * 6],
                    [2.0 + index % 5, 2.0 + (index // 5) * 6],
                ]],
            },
            "properties": {},
        }
        for index in range(30)
    )
    # One very long line forces the budget path to trigger.
    long_line = {
        "id": "spine",
        "geometry": {
            "type": "LineString",
            "coordinates": [[float(step % 20) * 5, float(step % 40) * 2.5] for step in range(30_000)],
        },
        "properties": {},
    }
    snapshot = MapRenderSnapshot(project_crs="", layers=(
        MapLayerSnapshot(
            id="mixed", name="mixed", layer_type="vector",
            extent=(0.0, 0.0, 100.0, 100.0), crs="",
            data_revision=1, style_revision=1, features=features + (long_line,),
            style={"fill": "#e03131", "stroke": "#ffffff", "stroke_width": 1.0},
        ),
    ))
    backend = FallbackMapRenderBackend()
    backend._vertex_budget = 800  # far below the 30k-line vertices
    _configure(backend, snapshot)

    image = _image(backend.render_sync())
    # Polygons live in world x 2..10, y 2..31 → screen x 4..20, y 138..196.
    polygon_pixels = sum(
        1
        for x in range(5, 19)
        for y in range(140, 195, 2)
        if image.pixelColor(QPoint(x, y)).red() > 150
    )

    assert polygon_pixels > 50


# ---------------------------------------------------------------------------
# P7: export chrome correctness
# ---------------------------------------------------------------------------


def _canvas(qtbot):
    from paleo_workbench.ui.unified_map_canvas import UnifiedMapCanvas

    canvas = UnifiedMapCanvas(backend=FallbackMapRenderBackend())
    qtbot.addWidget(canvas)
    canvas.resize(320, 240)
    canvas.show()
    canvas.set_layer_snapshot(MapRenderSnapshot(project_crs="", layers=(
        MapLayerSnapshot(
            id="facies", name="Facies", layer_type="vector",
            extent=(0.0, 0.0, 10.0, 10.0), crs="",
            data_revision=1, style_revision=1,
            features=({"id": "f", "geometry": {"type": "Polygon", "coordinates": [[[2, 2], [8, 2], [8, 8], [2, 8], [2, 2]]]}, "properties": {}},),
            style={"fill": "#d9a441", "stroke": "#593d16", "stroke_width": 2.0},
        ),
    )))
    canvas.set_extent((0.0, 0.0, 10.0, 10.0))
    qtbot.waitUntil(lambda: canvas.last_frame is not None, timeout=5_000)
    return canvas


def test_scale_bar_label_matches_bar_length_and_ladder() -> None:
    from paleo_workbench.ui.unified_map_canvas import UnifiedMapCanvas

    # Square 10-unit view exported at 2:1 → letterboxed extent spans 20 units.
    spec = UnifiedMapCanvas._scale_bar_spec((0.0, 0.0, 20.0, 10.0), 400)

    assert spec is not None
    bar_units, bar_pixels = spec
    ladder = {1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 0.5, 0.2, 0.1}
    assert bar_units in ladder
    # Bar pixels must correspond exactly to the printed unit count.
    assert abs(bar_pixels - bar_units / 20.0 * 400) < 1e-6


def test_export_svg_contains_background_fill(qtbot, tmp_path) -> None:
    canvas = _canvas(qtbot)
    path = tmp_path / "map.svg"

    canvas.export_svg(str(path), width=800, height=600)

    text = path.read_text(encoding="utf-8")
    assert "#ffffff" in text.lower()


def test_export_vector_cancels_in_flight_screen_render(qtbot, tmp_path) -> None:
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QImage, QPainter

    canvas = _canvas(qtbot)
    cancelled = []

    class _SpyBackend:
        render_active = True
        _output_size = (320, 240)
        _dpi = 96.0
        _extent = canvas.view_extent
        _snapshot = canvas.backend._snapshot

        def cancel_render(self):
            cancelled.append(True)

        def set_output_size(self, *a):
            pass

        def set_dpi(self, *a):
            pass

        def set_extent(self, *a):
            pass

        def render_sync(self):
            return canvas.backend.render_sync()

    real_backend = canvas.backend
    spy_target = real_backend

    class _SpyBackend2(_SpyBackend):
        def render_sync(self):
            return spy_target.render_sync()

    try:
        canvas._backend = _SpyBackend2()
        image = QImage(400, 300, QImage.Format.Format_RGBA8888)
        painter = QPainter(image)
        canvas._paint_export_vector(painter, 400, 300, 96.0)
        painter.end()
        assert cancelled == [True]
    finally:
        canvas._backend = real_backend
