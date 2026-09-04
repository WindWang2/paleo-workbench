"""M2 Task 5: 原生 QgsVectorLayerProperties 对话框 exec 与结果回写。"""
import json

import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.qgis
from PySide6.QtCore import QTimer

_FC = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1.0, 1.0]}, "properties": {}}]}


@pytest.fixture()
def stack(qapp):
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize()
    yield s
    s.shutdown()


def _auto_close_modal(qapp, action, deadline_ms=3000, interval_ms=100):
    """offscreen 下自动 accept/reject 模态对话框；未出现时循环重试至上限。"""
    state = {"elapsed": 0, "done": False}

    def tick():
        if state["done"]:
            return
        widget = qapp.activeModalWidget()
        if widget is not None:
            state["done"] = True
            getattr(widget, action)()
            return
        state["elapsed"] += interval_ms
        if state["elapsed"] < deadline_ms:
            QTimer.singleShot(interval_ms, tick)

    QTimer.singleShot(interval_ms, tick)


def test_exec_properties_cancel_returns_not_ok(qtbot, stack, qapp):
    canvas = stack.create_canvas()
    stack.upsert_mirror_layer("doc-a", "井位", "Point", "EPSG:4326",
                              json.dumps(_FC), "", "", "", True, 1.0)
    _auto_close_modal(qapp, "reject")
    result = stack.exec_layer_properties(canvas, "doc-a")
    assert result["ok"] is False


def test_exec_properties_accept_returns_renderer_xml(qtbot, stack, qapp):
    canvas = stack.create_canvas()
    stack.upsert_mirror_layer("doc-a", "井位", "Point", "EPSG:4326",
                              json.dumps(_FC), "", "", "", True, 1.0)
    _auto_close_modal(qapp, "accept")
    result = stack.exec_layer_properties(canvas, "doc-a")
    assert result["ok"] is True
    assert "<renderer" in result["renderer_xml"]
    assert 0.0 < result["opacity"] <= 1.0
    assert result["name"] == "井位"


def test_exec_properties_unknown_layer_raises(qtbot, stack):
    canvas = stack.create_canvas()
    with pytest.raises(Exception):
        stack.exec_layer_properties(canvas, "no-such-doc")
