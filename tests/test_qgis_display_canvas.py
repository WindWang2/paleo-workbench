# -*- coding: utf-8 -*-
"""M4: QgisDisplayCanvas 快照镜像、单击、工厂回落。"""
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent
import pytest

pytest.importorskip("PySide6")
from tests.qgis_support import QGIS_SKIP_REASON

pytest.importorskip("qgis_render_bridge.mapstack", reason=QGIS_SKIP_REASON)
pytestmark = pytest.mark.qgis


def _point_snapshot():
    from paleo_workbench.mapping.map_render_backend import (
        MapLayerSnapshot, MapRenderSnapshot,
    )
    layer = MapLayerSnapshot(
        id="home_workarea:wells",
        name="wells",
        layer_type="vector",
        extent=(0.0, 0.0, 10.0, 10.0),
        crs="EPSG:4326",
        data_revision=1,
        style_revision=1,
        features=(
            {"id": "w1", "geometry": {"type": "Point", "coordinates": [5.0, 5.0]},
             "properties": {"well_id": "A12"}},
        ),
        style={"stroke": "#409cff"},
        visible=True,
        opacity=1.0,
    )
    return MapRenderSnapshot(project_crs="EPSG:4326", layers=(layer,))


def _click(widget, pos: QPointF):
    press = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress, pos,
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    release = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease, pos,
        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication = __import__("PySide6.QtWidgets", fromlist=["QApplication"]).QApplication
    QApplication.sendEvent(widget, press)
    QApplication.sendEvent(widget, release)


def test_display_canvas_mirrors_snapshot_and_click(qtbot, qapp):
    from paleo_workbench.ui.qgis_stack.display_canvas import QgisDisplayCanvas

    canvas = QgisDisplayCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(400, 400)
    canvas.show()
    canvas.set_layer_snapshot(_point_snapshot())
    canvas.set_extent((0.0, 0.0, 10.0, 10.0))
    qtbot.wait(50)
    assert canvas.stack.canvas_layer_count(canvas.canvas_address) == 1

    seen = []
    canvas.map_clicked.connect(seen.append)
    target = canvas.canvas
    _click(target, QPointF(200, 200))
    qtbot.wait(50)
    assert len(seen) == 1
    assert seen[0][0] == pytest.approx(5.0, abs=1.5)
    assert seen[0][1] == pytest.approx(5.0, abs=1.5)


def test_display_canvas_drag_does_not_click(qtbot, qapp):
    from PySide6.QtWidgets import QApplication
    from paleo_workbench.ui.qgis_stack.display_canvas import QgisDisplayCanvas

    canvas = QgisDisplayCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(400, 400)
    canvas.show()
    canvas.set_extent((0.0, 0.0, 10.0, 10.0))
    seen = []
    canvas.map_clicked.connect(seen.append)
    target = canvas.canvas
    press = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress, QPointF(80, 80),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    move = QMouseEvent(
        QMouseEvent.Type.MouseMove, QPointF(180, 160),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    release = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease, QPointF(180, 160),
        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(target, press)
    QApplication.sendEvent(target, move)
    QApplication.sendEvent(target, release)
    qtbot.wait(50)
    assert seen == []


def test_create_display_canvas_returns_qgis_when_bridge_present(qapp):
    from paleo_workbench.ui.qgis_stack.display_canvas import (
        QgisDisplayCanvas, create_display_canvas,
    )
    w = create_display_canvas()
    assert isinstance(w, QgisDisplayCanvas)
    w.shutdown()


def test_shim_and_display_share_mirror_helper(qtbot, qapp):
    from paleo_workbench.ui.qgis_stack.mirror import mirror_snapshot_to_stack
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize(display=True)
    try:
        addr = s.create_canvas()
        from shiboken6 import wrapInstance
        from PySide6.QtWidgets import QWidget
        w = wrapInstance(addr, QWidget)
        qtbot.addWidget(w)
        w.resize(200, 200)
        w.show()
        qgis_ids, doc_ids, _failures = mirror_snapshot_to_stack(s, addr, _point_snapshot())
        assert doc_ids == ["home_workarea:wells"]
        assert s.canvas_layer_count(addr) == 1
        assert qgis_ids
    finally:
        s.shutdown()
