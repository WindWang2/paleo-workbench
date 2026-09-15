# -*- coding: utf-8 -*-
"""vector-perf-increment Phase-1 baseline measurements (measurement-only).

Records the PRE-optimization cost of the four SLA dimensions on real
production code paths (docs/development/vector-perf-increment/01-perf-baseline.md):

* snap   - real vertex-tool mouse-press pick over an N-vertex mirror layer
           (drives the C++ canvasPressEvent -> verticesNear linear scan via
           QTest injection — no synthetic reimplementation)
* topo   - bridge run_geometry_checks full-layer scan plus the post-node-move
           re-validation cost (today identical: full rescan)
* render - fallback QPainter renderer, facies-pattern polygon layer,
           first-frame bake + zoom/pan sweep
* ffi    - Python<->C++ JSON channel: event decode x10k, mirror delta
           publish, delta apply through the real bridge, readback, GC pauses

These are measurements, not gates: no SLA assertions here (the per-ticket
benchmark tests add those). Run with ``-s`` to see the numbers::

    pytest tests/perf/test_vector_perf_baseline.py -s -m "qgis or slow"
"""
from __future__ import annotations

import json
import statistics
import time

import pytest

pytest.importorskip("PySide6")
pytestmark = [pytest.mark.slow, pytest.mark.qgis]

SCALES = [1_000, 10_000, 20_000, 50_000]
REPEATS = 15


def _stats_ms(samples_s: list[float]) -> dict:
    ms = [s * 1000.0 for s in samples_s]
    return {
        "n": len(ms),
        "median_ms": round(statistics.median(ms), 3),
        "min_ms": round(min(ms), 3),
        "max_ms": round(max(ms), 3),
    }


def _emit(name: str, key: str, stats: dict) -> None:
    print(f"[vector-baseline] {name} {key} median={stats['median_ms']}ms "
          f"min={stats['min_ms']}ms max={stats['max_ms']}ms", flush=True)


def _grid_squares(n_vertices: int, span: float = 100.0) -> list[dict]:
    """Square grid polygons totalling ~n_vertices (5 per square ring)."""
    squares = max(1, n_vertices // 5)
    side = max(1, int(squares**0.5))
    cell = span / side
    feats: list[dict] = []
    for i in range(side):
        for j in range(side):
            if len(feats) >= squares:
                break
            x0, y0 = i * cell, j * cell
            feats.append({
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[
                    [x0, y0], [x0 + cell, y0], [x0 + cell, y0 + cell],
                    [x0, y0 + cell], [x0, y0]]]},
                "properties": {"__pwb_fid": f"f{i}-{j}", "facies_name": "delta"},
            })
    return feats


def _collection(features: list[dict]) -> str:
    return json.dumps({"type": "FeatureCollection", "features": features})


def _upsert(stack, doc, feats, revision=1):
    stack.upsert_mirror_layer(
        doc, "bench", "Polygon", "EPSG:3857", _collection(feats),
        "", "", "", True, 1.0, is_reference=False, is_editable=True,
        data_revision=revision)


@pytest.fixture()
def stack(qapp):
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize()
    yield s
    s.shutdown()


def _canvas(qtbot, stack, size=800):
    from shiboken6 import wrapInstance
    from PySide6.QtWidgets import QGraphicsView

    addr = stack.create_canvas()
    view = wrapInstance(addr, QGraphicsView)
    qtbot.addWidget(view)
    view.resize(size, size)
    view.show()
    return addr, view


# ------------------------------------------------------------------- snap


def test_baseline_snap_press_pick(qtbot, qapp, stack):
    """Real vertex-tool press pick latency per vertex scale."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    def _upsert4326(doc, feats):
        stack.upsert_mirror_layer(
            doc, "bench", "Polygon", "EPSG:4326", _collection(feats),
            "", "", "", True, 1.0, is_reference=False, is_editable=True,
            data_revision=1)

    for n in SCALES:
        feats = _grid_squares(n)
        doc = f"snap-{n}"
        addr, view = _canvas(qtbot, stack, size=400)
        _upsert4326(doc, feats)
        stack.set_canvas_extent(addr, 0.0, 0.0, 10.0, 10.0)
        assert stack.start_mirror_layer_editing(doc) == ""
        stack.set_current_layer(addr, doc)
        events: list[tuple[str, dict]] = []
        stack.set_edit_pick_callback(
            addr, lambda action, payload: events.append(
                (action, json.loads(payload))))
        stack.set_map_tool(addr, "vertex")
        span_px = 400.0 / 10.0

        def press_at(x: float, y: float):
            pos = QPoint(int(span_px * x), int(400 - span_px * y))
            QTest.mousePress(view.viewport(), Qt.LeftButton, Qt.NoModifier, pos)
            QTest.mouseMove(view.viewport(), pos)
            QTest.mouseRelease(view.viewport(), Qt.LeftButton, Qt.NoModifier, pos)

        # Press on fractional offsets far from every vertex (>10px pick
        # radius at this extent): verticesNear performs the identical full
        # scan regardless of hits; a vertex hit would additionally begin a
        # shared drag.（V12 注：曾在 vendor 构建因 MSVC 实参求值顺序
        # use-after-move 崩溃——编辑工具链 D-A 已修复，绕行注释历史化。） At the densest scale (cell = 1.0 unit,
        # pick radius = 0.25 unit) the chosen points stay ≥0.35 units from
        # the nearest vertex.
        targets = [(5.4, 5.4), (6.25, 4.75)]
        press_at(*targets[0])  # warmup
        qapp.processEvents()
        samples = []
        for k in range(REPEATS):
            t0 = time.perf_counter()
            press_at(*targets[k % 2])
            samples.append(time.perf_counter() - t0)
            qapp.processEvents()
        _emit("snap", f"press_pick_v{n}", _stats_ms(samples))
        stack.roll_back_mirror_layer(doc)
        stack.remove_mirror_layers_except([])
        view.close()

    # empty-layer floor: fixed press overhead without the N-vertex scan
    addr, view = _canvas(qtbot, stack, size=400)
    _upsert4326("snap-empty", _grid_squares(5))
    stack.set_canvas_extent(addr, 0.0, 0.0, 10.0, 10.0)
    assert stack.start_mirror_layer_editing("snap-empty") == ""
    stack.set_current_layer(addr, "snap-empty")
    stack.set_map_tool(addr, "vertex")
    span_px = 40.0

    def press_empty(x: float, y: float):
        pos = QPoint(int(span_px * x), int(400 - span_px * y))
        QTest.mousePress(view.viewport(), Qt.LeftButton, Qt.NoModifier, pos)
        QTest.mouseMove(view.viewport(), pos)
        QTest.mouseRelease(view.viewport(), Qt.LeftButton, Qt.NoModifier, pos)

    press_empty(5.4, 5.4)
    qapp.processEvents()
    samples = []
    for k in range(10):
        t0 = time.perf_counter()
        press_empty(*((5.4, 5.4) if k % 2 == 0 else (4.75, 6.25)))
        samples.append(time.perf_counter() - t0)
        qapp.processEvents()
    _emit("snap", "press_floor_5vert", _stats_ms(samples))
    stack.roll_back_mirror_layer("snap-empty")


# ------------------------------------------------------------------- topo


def test_baseline_topo_full_scan(qtbot, stack):
    """Bridge run_geometry_checks full-scan + post-move revalidation."""
    addr, _view = _canvas(qtbot, stack, size=400)
    for n in [s for s in SCALES if s != 20_000]:
        feats = _grid_squares(n)
        doc = f"topo-{n}"
        _upsert(stack, doc, feats)
        stack.set_canvas_extent(addr, 0.0, 0.0, 100.0, 100.0)
        config = json.dumps({
            "layer_ids": [doc],
            "rules": ["is_valid", "overlap", "dangle"],
            "precision": 8,
        })
        payload = stack.run_geometry_checks(addr, config)  # warmup
        assert "errors" in json.loads(payload)
        samples = []
        for _ in range(3):
            t0 = time.perf_counter()
            payload = stack.run_geometry_checks(addr, config)
            samples.append(time.perf_counter() - t0)
            assert "errors" in json.loads(payload)
        _emit("topo", f"full_scan_v{n}", _stats_ms(samples))

        # Post-node-move re-validation: move one vertex of feature 0, push
        # through the production delta channel, re-run checks.
        moved = json.loads(json.dumps(feats[0]))
        ring = moved["geometry"]["coordinates"][0]
        ring[1] = [ring[1][0] + 0.01, ring[1][1] + 0.01]
        delta = {"base_revision": 1, "changed": [moved], "removed_ids": []}
        stack.upsert_mirror_layer(
            doc, "bench", "Polygon", "EPSG:3857", _collection(feats),
            "", "", "", True, 1.0, is_reference=False, is_editable=True,
            data_revision=2, delta=json.dumps(delta))
        samples = []
        for _ in range(3):
            t0 = time.perf_counter()
            stack.run_geometry_checks(addr, config)
            samples.append(time.perf_counter() - t0)
        _emit("topo", f"post_move_revalidate_v{n}", _stats_ms(samples))
        stack.remove_mirror_layers_except([])


# ----------------------------------------------------------------- render


def test_baseline_render_facies_sweep():
    """Fallback QPainter facies-pattern zoom/pan sweep."""
    from paleo_workbench.mapping.map_render_backend import (
        FallbackMapRenderBackend,
        MapLayerSnapshot,
        MapRenderSnapshot,
    )

    for n in [s for s in SCALES if s != 20_000]:
        feats = [{
            "id": raw["properties"]["__pwb_fid"],
            "geometry": raw["geometry"],
            "properties": raw["properties"],
        } for raw in _grid_squares(n)]
        style = {
            "renderer": "categorized",
            "field": "facies_name",
            "categories": [["delta", "#e6c9a8", "d"],
                           ["lacustrine", "#cfd8c9", "l"]],
            "stroke": "#26364d",
            "stroke_width": 1.0,
            "fill_patterns": {"delta": "delta", "lacustrine": "sand"},
        }
        backend = FallbackMapRenderBackend()
        backend.initialize()
        backend.set_layer_snapshot(MapRenderSnapshot(
            project_crs="EPSG:3857",
            layers=(MapLayerSnapshot(
                id="facies", name="Facies", layer_type="vector",
                extent=(0.0, 0.0, 100.0, 100.0), crs="EPSG:3857",
                data_revision=1, style_revision=1, features=tuple(feats),
                style=style),),
        ))
        backend.set_output_size(800, 600)
        backend.set_dpi(96.0)

        t0 = time.perf_counter()  # first frame includes lazy SVG->brush bake
        backend.set_extent((0.0, 0.0, 100.0, 100.0))
        backend.render_sync()
        print(f"[vector-baseline] render first_frame_bake_v{n}_ms "
              f"{(time.perf_counter() - t0) * 1000.0:.3f}", flush=True)

        zoom, pan = [], []
        for k in range(12):
            half = 45.0 * (0.92**k)
            t0 = time.perf_counter()
            backend.set_extent((50.0 - half, 50.0 - half, 50.0 + half, 50.0 + half))
            backend.render_sync()
            zoom.append(time.perf_counter() - t0)
        for k in range(12):
            dx = (k % 4) * 2.0
            t0 = time.perf_counter()
            backend.set_extent((dx, dx, dx + 40.0, dx + 40.0))
            backend.render_sync()
            pan.append(time.perf_counter() - t0)
        _emit("render", f"zoom_sweep_v{n}", _stats_ms(zoom))
        _emit("render", f"pan_sweep_v{n}", _stats_ms(pan))


# -------------------------------------------------------------------- ffi

_GESTURE_PAYLOAD = json.dumps({
    "kind": "move", "base_revision": 7, "layer_doc_id": "draft-a",
    "moves": [
        {"feature_id": "f123", "path": [0, 4], "from": [12.5, 8.25],
         "to": [12.6, 8.31]},
        {"feature_id": "f123", "path": [0, 5], "from": [14.0, 8.25],
         "to": [14.1, 8.31]},
        {"feature_id": "f124", "path": [0, 2], "from": [12.5, 9.0],
         "to": [12.6, 9.05]},
    ],
    "tolerance": 1e-8,
})


def test_baseline_ffi_json_channel(qapp, stack):
    """Python<->C++ JSON channel costs at gesture cadence."""
    n_events = 10_000
    payload = _GESTURE_PAYLOAD

    t0 = time.perf_counter()
    for _ in range(n_events):
        json.loads(payload)
    print(f"[vector-baseline] ffi event_decode_{n_events}_ms "
          f"{(time.perf_counter() - t0) * 1000.0:.3f}", flush=True)

    # allocation volume + GC pauses across the same loop
    import gc
    import tracemalloc

    gc.collect()
    state = {"pauses_s": 0.0, "collections": 0}
    _t: dict[str, float] = {}

    def _pause_cb(phase, info):
        if phase == "start":
            _t["t0"] = time.perf_counter()
        elif phase == "stop" and "t0" in _t:
            state["pauses_s"] += time.perf_counter() - _t.pop("t0")
            state["collections"] += 1

    gc.callbacks.append(_pause_cb)
    tracemalloc.start()
    t0 = time.perf_counter()
    for _ in range(n_events):
        json.loads(payload)
    loop_ms = (time.perf_counter() - t0) * 1000.0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    gc.callbacks.remove(_pause_cb)
    print(f"[vector-baseline] ffi event_decode_alloc_loop_ms {loop_ms:.3f} "
          f"tracemalloc_peak_kb={peak / 1024:.1f} "
          f"gc_collections={state['collections']} "
          f"gc_pause_ms={state['pauses_s'] * 1000:.3f}", flush=True)

    # -- real bridge: delta encode+apply through upsert (production route) --
    n_feat = 10_000
    doc = "ffi-bench"
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature",
         "geometry": {"type": "Polygon", "coordinates": [[
             [float(i), 0.0], [float(i) + 1, 0.0], [float(i) + 1, 1.0],
             [float(i), 1.0], [float(i), 0.0]]]},
         "properties": {"__pwb_fid": f"f{i}"}}
        for i in range(n_feat)]}
    fc_json = json.dumps(fc)
    stack.upsert_mirror_layer(
        doc, "ffi", "Polygon", "EPSG:3857", fc_json,
        "", "", "", True, 1.0, is_reference=False, is_editable=True,
        data_revision=1)

    def _delta(base: int, tweak: float):
        changed = [
            {"type": "Feature",
             "geometry": {"type": "Polygon", "coordinates": [[
                 [float(i), 0.0], [float(i) + 1 + tweak, 0.0],
                 [float(i) + 1 + tweak, 1.0], [float(i), 1.0],
                 [float(i), 0.0]]]},
             "properties": {"__pwb_fid": f"f{i}"}}
            for i in range(100)]
        return json.dumps({
            "base_revision": base, "changed": changed, "removed_ids": []})

    t0 = time.perf_counter()
    delta_json = _delta(1, 0.1)
    encode_ms = (time.perf_counter() - t0) * 1000.0
    # warmup apply (rev 1 -> 2), then timed apply (rev 2 -> 3): both take the
    # in-place delta path (base_revision matches the current revision).
    stack.upsert_mirror_layer(
        doc, "ffi", "Polygon", "EPSG:3857", fc_json,
        "", "", "", True, 1.0, is_reference=False, is_editable=True,
        data_revision=2, delta=delta_json)
    delta_json = _delta(2, 0.2)
    t0 = time.perf_counter()
    stack.upsert_mirror_layer(
        doc, "ffi", "Polygon", "EPSG:3857", fc_json,
        "", "", "", True, 1.0, is_reference=False, is_editable=True,
        data_revision=3, delta=delta_json)
    apply_ms = (time.perf_counter() - t0) * 1000.0
    print(f"[vector-baseline] ffi delta_encode_100_of_{n_feat}_ms "
          f"{encode_ms:.3f} delta_apply_via_upsert_ms {apply_ms:.3f}",
          flush=True)

    t0 = time.perf_counter()
    raw = stack.mirror_features_json(doc, 0)
    pull_ms = (time.perf_counter() - t0) * 1000.0
    t0 = time.perf_counter()
    parsed = json.loads(raw)
    parse_ms = (time.perf_counter() - t0) * 1000.0
    assert parsed["exists"]
    print(f"[vector-baseline] ffi readback_pull_{n_feat}_ms {pull_ms:.3f} "
          f"readback_parse_ms {parse_ms:.3f}", flush=True)

    # -- Python-side publish path: signature walk + delta assembly --------
    from paleo_workbench.mapping.map_render_backend import MapLayerSnapshot
    from paleo_workbench.mapping.qgis_mirror import (
        mirror_snapshot_to_stack,
        reset_publish_ledger,
    )

    class _CountingStack:
        shipped = 0

        def set_destination_crs(self, canvas, crs):
            pass

        def upsert_mirror_layer(self, doc_id, name, geom, crs, geojson,
                                renderer_xml="", labeling_xml="",
                                legacy_style=None, visible=True, opacity=1.0,
                                is_reference=False, is_editable=False,
                                reference_snap=False, data_revision=0, delta=""):
            payload_ = json.loads(delta) if delta else json.loads(geojson)
            self.shipped += len(payload_.get(
                "changed", payload_.get("features", ())))

        def remove_mirror_layers_except(self, seen):
            pass

        def set_mirror_layer_order(self, order):
            pass

        def refresh_canvas(self, canvas):
            pass

    class _Snap:
        def __init__(self, layers):
            self.layers = tuple(layers)
            self.project_crs = "EPSG:3857"

    features = [{
        "id": f"f{i}",
        "geometry": {"type": "Polygon", "coordinates": [[
            [float(i), 0.0], [float(i) + 1, 0.0], [float(i) + 1, 1.0],
            [float(i), 1.0], [float(i), 0.0]]]},
        "properties": {"name": "n", "facies_name": "delta"},
    } for i in range(n_feat)]

    def _snapshot(rev, feats):
        return MapLayerSnapshot(
            id="big-1", name="big", layer_type="vector",
            extent=(0.0, 0.0, float(n_feat), 1.0), crs="EPSG:3857",
            data_revision=rev, style_revision=1, features=tuple(feats),
            style={}, visible=True, opacity=1.0, renderer_payload=None)

    reset_publish_ledger()
    fake = _CountingStack()
    mirror_snapshot_to_stack(fake, 0x1, _Snap([_snapshot(1, features)]))
    assert fake.shipped == n_feat
    fake.shipped = 0
    edited = list(features)
    edited[42] = dict(edited[42],
                      properties={"name": "edited", "facies_name": "delta"})
    t0 = time.perf_counter()
    mirror_snapshot_to_stack(fake, 0x1, _Snap([_snapshot(2, edited)]))
    pub_ms = (time.perf_counter() - t0) * 1000.0
    assert fake.shipped == 1, fake.shipped
    print(f"[vector-baseline] ffi mirror_delta_publish_1of{n_feat}_ms "
          f"{pub_ms:.3f}", flush=True)
    reset_publish_ledger()
