# -*- coding: utf-8 -*-
"""V10 capture flow: digitizing progress callback (points/segment/total +
snap info), Backspace undo of last captured vertex, self-snapping during
capture (active mirror layer participates in locator)."""
import json

import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.qgis

_FC = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature",
         "geometry": {"type": "Polygon",
                      "coordinates": [[(5.0, 5.0), (8.0, 5.0), (8.0, 8.0), (5.0, 8.0), (5.0, 5.0)]]},
         "properties": {"__pwb_fid": "f1", "name": "A"}},
    ],
}


@pytest.fixture()
def stack(qapp):
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize()
    yield s
    s.shutdown()


def _send_move(w, point):
    """直接向 viewport 投递合成 move（QTest.mouseMove 依赖窗口系统光标，
    offscreen 下对非首个画布不投递——探针验证 sendEvent 路径稳定可达工具层）。"""
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    ev = QMouseEvent(QEvent.MouseMove, point, w.viewport().mapToGlobal(point),
                     Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                     Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(w.viewport(), ev)


def _setup(qtbot, stack, kind="addLine", snapping=None):
    from shiboken6 import wrapInstance
    from PySide6.QtWidgets import QGraphicsView

    canvas = stack.create_canvas()
    w = wrapInstance(canvas, QGraphicsView)
    qtbot.addWidget(w)
    w.resize(400, 400)
    w.show()
    stack.upsert_mirror_layer("doc-poly", "相带", "Polygon", "EPSG:4326",
                              json.dumps(_FC), "", "", "", True, 1.0,
                              is_reference=False, is_editable=True)
    stack.set_canvas_extent(canvas, 0.0, 0.0, 10.0, 10.0)
    if snapping is not None:
        stack.set_snapping_config(canvas, json.dumps(snapping))
    events = []
    stack.set_digitize_callback(
        canvas, lambda status, payload: events.append((status, payload)))
    stack.set_map_tool(canvas, kind)
    return w, events


def _pixel(x: float, y: float):
    from PySide6.QtCore import QPoint

    return QPoint(int(40 * x), int(400 - 40 * y))


def _progress(events):
    return [json.loads(p) for s, p in events if s == "digitizing"]


def test_digitizing_progress_streams_points_and_lengths(qtbot, stack):
    w, events = _setup(qtbot, stack, "addLine")
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    _send_move(w, _pixel(2.0, 5.0))
    qtbot.waitUntil(lambda: bool(_progress(events)), timeout=2000)
    empty = _progress(events)[-1]
    assert empty["action"] == "digitizing"
    assert empty["planar"] is True
    assert empty["points"] == []
    assert abs(empty["hover"][0] - 2.0) < 0.15

    QTest.mouseClick(w.viewport(), Qt.LeftButton, Qt.NoModifier, _pixel(2.0, 5.0))
    _send_move(w, _pixel(5.0, 5.0))
    qtbot.waitUntil(lambda: bool(_progress(events) and _progress(events)[-1]["points"]),
                        timeout=2000)
    one = _progress(events)[-1]
    assert len(one["points"]) == 1
    assert abs(one["segments"] - 3.0) < 0.2  # hover 段长 ≈ 3.0 地图单位
    assert abs(one["total"] - 0.0) < 0.2    # 已采 1 点：折线总长 0



def test_backspace_removes_last_captured_vertex(qtbot, stack):
    w, events = _setup(qtbot, stack, "addLine")
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    QTest.mouseClick(w.viewport(), Qt.LeftButton, Qt.NoModifier, _pixel(2.0, 5.0))
    QTest.mouseClick(w.viewport(), Qt.LeftButton, Qt.NoModifier, _pixel(5.0, 5.0))
    QTest.keyClick(w, Qt.Key_Backspace)
    QTest.mouseClick(w.viewport(), Qt.LeftButton, Qt.NoModifier, _pixel(8.0, 5.0))
    QTest.mouseClick(w.viewport(), Qt.RightButton, Qt.NoModifier, _pixel(8.0, 5.0))
    qtbot.waitUntil(lambda: any(s == "completed" for s, _ in events), timeout=2000)
    g = json.loads([p for s, p in events if s == "completed"][-1])
    coords = g["coordinates"]
    if g["type"] == "MultiLineString":
        coords = coords[0]
    # Backspace 撤销了 (5,5)：完成几何 = (2,5)→(8,5) 两点。
    assert len(coords) == 2
    assert abs(coords[0][0] - 2.0) < 0.2
    assert abs(coords[1][0] - 8.0) < 0.2


def test_capture_self_snapping_to_active_mirror_layer(qtbot, stack):
    # 活动镜像层自身参与 AdvancedConfiguration 捕捉（self-snapping）：
    # 在既有顶点 (5,5) 容差内采点，完成几何应精确吸附到 (5,5)。
    w, events = _setup(qtbot, stack, "addLine", snapping={
        "enabled": True, "mode": "all_layers", "tolerance_px": 20.0,
        "types": ["vertex"],
    })
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    QTest.mouseClick(w.viewport(), Qt.LeftButton, Qt.NoModifier, _pixel(5.2, 5.1))
    QTest.mouseClick(w.viewport(), Qt.LeftButton, Qt.NoModifier, _pixel(8.0, 8.0))
    QTest.mouseClick(w.viewport(), Qt.RightButton, Qt.NoModifier, _pixel(8.0, 8.0))
    qtbot.waitUntil(lambda: any(s == "completed" for s, _ in events), timeout=2000)
    g = json.loads([p for s, p in events if s == "completed"][-1])
    coords = g["coordinates"]
    if g["type"] == "MultiLineString":
        coords = coords[0]
    assert abs(coords[0][0] - 5.0) < 1e-6
    assert abs(coords[0][1] - 5.0) < 1e-6


def test_digitizing_progress_snap_info_and_throttle(qtbot, stack):
    """snap 信息回传 + 亚像素节流（与 streams 分离：snapping 配置变体）。"""
    w, events = _setup(qtbot, stack, "addLine", snapping={
        "enabled": True, "mode": "all_layers", "tolerance_px": 20.0,
        "types": ["vertex"],
    })
    from PySide6.QtTest import QTest

    _send_move(w, _pixel(5.2, 5.1))
    qtbot.waitUntil(lambda: bool(_progress(events)), timeout=2000)
    qtbot.waitUntil(
        lambda: bool([p for p in _progress(events) if p.get("snap")]),
        timeout=2000)
    snap = [p for p in _progress(events) if p.get("snap")][-1]["snap"]
    assert snap["matched"] is True
    assert snap["layer_doc_id"] == "doc-poly"
    assert abs(snap["x"] - 5.0) < 1e-6
    # 亚像素移动（同命中、点数未变）→ 不产生新的 digitizing 回调。
    before = len(_progress(events))
    _send_move(w, _pixel(5.21, 5.1))
    _send_move(w, _pixel(5.22, 5.1))
    QTest.qWait(120)
    assert len(_progress(events)) == before
