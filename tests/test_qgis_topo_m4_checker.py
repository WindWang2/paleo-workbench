# -*- coding: utf-8 -*-
"""拓扑编辑迁移 M4：检查器——真桥面（规格 §8 → §5）。

场景 12（工区余量：未铺满被抓并高亮，点击缩放；修复=导航不改几何）、
场景 14（多处重叠全部修复逐个裁切，一次 Ctrl+Z 整体回退）。
重叠/有效性检测为场景 13 的桥侧前提。
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.qgis


_FIELDS = json.dumps([
    {"name": "facies", "type": "QString", "alias": "相分类"},
])


def _square(feature_id, x0, y0, size=4.0, **props):
    properties = {"__pwb_fid": feature_id, **props}
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [[
            [x0, y0], [x0 + size, y0], [x0 + size, y0 + size],
            [x0, y0 + size], [x0, y0]]]},
        "properties": properties,
    }


def _collection(*features):
    return json.dumps({"type": "FeatureCollection", "features": list(features)})


def _workspace(x0=0.0, y0=0.0, size=10.0):
    return {
        "type": "Polygon",
        "coordinates": [[
            [x0, y0], [x0 + size, y0], [x0 + size, y0 + size],
            [x0, y0 + size], [x0, y0]]],
    }


@pytest.fixture()
def stack(qapp):
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize()
    yield s
    s.shutdown()


def _canvas(qtbot, stack):
    from shiboken6 import wrapInstance
    from PySide6.QtWidgets import QGraphicsView

    addr = stack.create_canvas()
    view = wrapInstance(addr, QGraphicsView)
    qtbot.addWidget(view)
    view.resize(400, 400)
    view.show()
    return addr, view


def _upsert(stack, doc_id, features, geometry="Polygon", crs="EPSG:4326"):
    stack.upsert_mirror_layer(
        doc_id, doc_id, geometry, crs, _collection(*features),
        "", "", "", True, 1.0, is_reference=False, is_editable=True,
        data_revision=1, fields_json=_FIELDS)


def _readback(stack, doc_id):
    payload = json.loads(stack.mirror_features_json(doc_id, 0))
    assert payload["exists"], doc_id
    return payload["features"]


def _cleanup(stack, addr, *docs):
    stack.set_map_tool(addr, "pan")
    for doc in docs:
        if stack.mirror_layer_editing(doc):
            stack.roll_back_mirror_layer(doc)


def _run(stack, addr, layer_ids, **extra):
    config = {
        "layer_ids": list(layer_ids),
        "rules": ["overlap", "gap", "is_valid", "workspace_remainder"],
        "precision": 8,
        **extra,
    }
    raw = stack.run_geometry_checks(addr, json.dumps(config))
    payload = json.loads(raw) if isinstance(raw, str) else raw
    assert "errors" in payload, payload
    return payload


def _errors_of(payload, rule):
    return [e for e in payload["errors"] if e.get("rule") == rule]


def test_scenario12_workspace_remainder_highlight_and_navigate(qtbot, stack):
    """场景 12：相带未铺满工区 → 余量被抓并高亮；修复=缩放导航不改几何。"""
    addr, _view = _canvas(qtbot, stack)
    try:
        _upsert(stack, "draft", [
            _square("a", 0.0, 0.0, size=4.0, facies="砂岩"),
        ])
        stack.set_canvas_extent(addr, 0.0, 0.0, 10.0, 10.0)

        payload = _run(stack, addr, ["draft"], workspace=_workspace())
        remainders = _errors_of(payload, "workspace_remainder")
        assert remainders, payload["errors"]
        error = remainders[0]
        assert error.get("bbox"), error
        bbox = error["bbox"]
        assert bbox[2] - bbox[0] > 1.0 and bbox[3] - bbox[1] > 1.0

        stack.highlight_checker_errors(addr, json.dumps([error["id"]]))
        assert stack.highlight_count(addr) >= 1

        before = _readback(stack, "draft")
        result = json.loads(stack.fix_geometry_error(addr, str(error["id"]), 0))
        assert result.get("ok") is True, result
        after = _readback(stack, "draft")
        assert after == before, "工区余量修复不得改几何"
        extent = stack.canvas_extent(addr)
        assert extent[0] <= bbox[0] + 0.5
        assert extent[2] >= bbox[2] - 0.5
    finally:
        _cleanup(stack, addr, "draft")


def test_overlap_detected_between_two_polygons(qtbot, stack):
    """场景 13 前提：两面重叠被 QgsGeometryOverlapCheck 抓到。"""
    addr, _view = _canvas(qtbot, stack)
    try:
        _upsert(stack, "draft", [
            _square("a", 0.0, 0.0, size=4.0, facies="砂岩"),
            _square("b", 2.0, 2.0, size=4.0, facies="泥岩"),
        ])
        stack.set_canvas_extent(addr, 0.0, 0.0, 10.0, 10.0)
        payload = _run(stack, addr, ["draft"])
        overlaps = _errors_of(payload, "overlap")
        assert overlaps, payload["errors"]
        ids = {
            overlaps[0].get("feature_id"),
            overlaps[0].get("other_feature_id"),
        }
        assert ids == {"a", "b"} or {"a", "b"}.issubset(
            {e.get("feature_id") for e in overlaps} |
            {e.get("other_feature_id") for e in overlaps})
        assert overlaps[0].get("fixable") is True
        methods = overlaps[0].get("methods") or []
        assert any(m.get("id") == 0 for m in methods)
    finally:
        _cleanup(stack, addr, "draft")


def test_invalid_geometry_make_valid(qtbot, stack):
    """几何有效性：自相交面被抓到；makeValid 修复后消失。"""
    addr, _view = _canvas(qtbot, stack)
    try:
        bowtie = {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [[
                [0, 0], [4, 4], [4, 0], [0, 4], [0, 0]]]},
            "properties": {"__pwb_fid": "bad", "facies": "砂岩"},
        }
        _upsert(stack, "draft", [bowtie])
        stack.set_canvas_extent(addr, -1.0, -1.0, 6.0, 6.0)
        assert stack.start_mirror_layer_editing("draft") == ""
        payload = _run(stack, addr, ["draft"])
        invalids = _errors_of(payload, "is_valid")
        assert invalids, payload["errors"]
        error = invalids[0]
        result = json.loads(stack.fix_geometry_error(addr, str(error["id"]), 0))
        assert result.get("ok") is True, result
        remaining = _errors_of(result, "is_valid")
        assert remaining == [], remaining
    finally:
        _cleanup(stack, addr, "draft")


def test_scenario14_fix_all_overlaps_and_single_undo(qtbot, stack):
    """场景 14：多处重叠全部修复裁切，面板清空；一次 undo 整体回退。"""
    addr, _view = _canvas(qtbot, stack)
    try:
        _upsert(stack, "draft", [
            _square("a", 0.0, 0.0, size=4.0, facies="砂岩"),
            _square("b", 2.0, 2.0, size=4.0, facies="泥岩"),
            _square("c", 3.0, 0.0, size=4.0, facies="灰岩"),
        ])
        stack.set_canvas_extent(addr, 0.0, 0.0, 10.0, 10.0)
        assert stack.start_mirror_layer_editing("draft") == ""

        events = []
        stack.set_edit_pick_callback(
            addr, lambda action, payload: events.append(
                (action, json.loads(payload))))

        payload = _run(stack, addr, ["draft"])
        overlaps = _errors_of(payload, "overlap")
        assert len(overlaps) >= 2, payload["errors"]
        before = _readback(stack, "draft")
        assert len(before) == 3

        ids = [e["id"] for e in overlaps]
        result = json.loads(stack.fix_geometry_errors(addr, json.dumps(ids), 0))
        assert result.get("ok") is True, result
        remaining = _errors_of(result, "overlap")
        assert remaining == [], remaining

        gesture = [p for a, p in events if a == "edit_gesture"]
        assert gesture, events
        assert "draft" in gesture[-1]["layers"]

        assert stack.undo_mirror_edit("draft") == ""
        restored = _readback(stack, "draft")
        assert len(restored) == 3
        payload_after_undo = _run(stack, addr, ["draft"])
        assert len(_errors_of(payload_after_undo, "overlap")) >= 2
    finally:
        _cleanup(stack, addr, "draft")
