# -*- coding: utf-8 -*-
"""M4: display 栈自有 QgsProject，不写入编修单例。"""
import json

import pytest

pytest.importorskip("PySide6")
from tests.qgis_support import QGIS_SKIP_REASON

pytest.importorskip("qgis_render_bridge.mapstack", reason=QGIS_SKIP_REASON)
pytestmark = pytest.mark.qgis

_GEOJSON = json.dumps({
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1.0, 2.0]},
         "properties": {"name": "P"}}
    ],
})


@pytest.fixture()
def qapp_ok(qapp):
    return qapp


def _show(qtbot, addr):
    from shiboken6 import wrapInstance
    from PySide6.QtWidgets import QWidget
    w = wrapInstance(addr, QWidget)
    qtbot.addWidget(w)
    w.resize(400, 400)
    w.show()
    return w


def test_initialize_display_kwarg_exists(qapp_ok):
    from qgis_render_bridge.mapstack import QgisMapStack
    s = QgisMapStack()
    s.initialize(display=True)
    try:
        assert s.initialized
    finally:
        s.shutdown()


def test_display_upsert_does_not_change_authoring_count(qtbot, qapp_ok):
    from qgis_render_bridge.mapstack import QgisMapStack

    authoring = QgisMapStack()
    authoring.initialize()
    display = QgisMapStack()
    display.initialize(display=True)
    try:
        before = authoring.project_layer_count()
        canvas = display.create_canvas()
        _show(qtbot, canvas)
        display.upsert_mirror_layer(
            "home_workarea:wells", "wells", "Point", "EPSG:4326",
            _GEOJSON, "", "", "", True, 1.0,
        )
        assert display.project_layer_count() == 1
        assert display.canvas_layer_count(canvas) == 1
        assert authoring.project_layer_count() == before
    finally:
        display.shutdown()
        authoring.shutdown()


def test_two_display_stacks_do_not_share_layers(qtbot, qapp_ok):
    from qgis_render_bridge.mapstack import QgisMapStack

    a = QgisMapStack()
    a.initialize(display=True)
    b = QgisMapStack()
    b.initialize(display=True)
    try:
        ca = a.create_canvas()
        cb = b.create_canvas()
        _show(qtbot, ca)
        _show(qtbot, cb)
        a.upsert_mirror_layer(
            "a:wells", "A", "Point", "EPSG:4326", _GEOJSON, "", "", "", True, 1.0,
        )
        assert a.project_layer_count() == 1
        assert b.project_layer_count() == 0
        assert a.canvas_layer_count(ca) == 1
        assert b.canvas_layer_count(cb) == 0
    finally:
        a.shutdown()
        b.shutdown()


def test_display_create_layer_tree_view_raises(qtbot, qapp_ok):
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize(display=True)
    try:
        canvas = s.create_canvas()
        _show(qtbot, canvas)
        with pytest.raises(RuntimeError, match="display"):
            s.create_layer_tree_view(canvas)
    finally:
        s.shutdown()


def test_display_rejects_edit_map_tools(qtbot, qapp_ok):
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize(display=True)
    try:
        canvas = s.create_canvas()
        _show(qtbot, canvas)
        s.set_map_tool(canvas, "pan")
        with pytest.raises(RuntimeError, match="display"):
            s.set_map_tool(canvas, "addPoint")
    finally:
        s.shutdown()


def test_display_hidden_upsert_not_on_canvas(qtbot, qapp_ok):
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize(display=True)
    try:
        canvas = s.create_canvas()
        _show(qtbot, canvas)
        s.upsert_mirror_layer(
            "home_workarea:wells", "wells", "Point", "EPSG:4326",
            _GEOJSON, "", "", "", False, 1.0,
        )
        assert s.project_layer_count() == 1
        assert s.canvas_layer_count(canvas) == 0
    finally:
        s.shutdown()


def test_display_visibility_toggle_updates_canvas(qtbot, qapp_ok):
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize(display=True)
    try:
        canvas = s.create_canvas()
        _show(qtbot, canvas)
        qgis_id = s.upsert_mirror_layer(
            "home_workarea:wells", "wells", "Point", "EPSG:4326",
            _GEOJSON, "", "", "", True, 1.0,
        )
        assert s.canvas_layer_count(canvas) == 1
        s.set_mirror_layer_visibility("home_workarea:wells", False)
        assert s.canvas_layer_count(canvas) == 0
        s.set_layer_visibility(qgis_id, True)
        assert s.canvas_layer_count(canvas) == 1
        s.set_layer_visibility(qgis_id, False)
        assert s.canvas_layer_count(canvas) == 0
    finally:
        s.shutdown()


def test_display_shutdown_detaches_canvas_without_touching_authoring(qtbot, qapp_ok):
    from qgis_render_bridge.mapstack import QgisMapStack

    authoring = QgisMapStack()
    authoring.initialize()
    display = QgisMapStack()
    display.initialize(display=True)
    try:
        before = authoring.project_layer_count()
        canvas = display.create_canvas()
        _show(qtbot, canvas)
        display.upsert_mirror_layer(
            "home_workarea:wells", "wells", "Point", "EPSG:4326",
            _GEOJSON, "", "", "", True, 1.0,
        )
        display.shutdown()
        assert authoring.project_layer_count() == before
        assert display.canvas_layer_count(canvas) == 0
    finally:
        authoring.shutdown()


def test_display_canvas_has_no_cad_dock(qtbot, qapp_ok):
    from shiboken6 import wrapInstance
    from PySide6.QtWidgets import QWidget
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize(display=True)
    try:
        canvas = s.create_canvas()
        w = wrapInstance(canvas, QWidget)
        qtbot.addWidget(w)
        w.resize(400, 400)
        w.show()
        dock = next(
            (c for c in w.children()
             if c.metaObject().className() == "QgsAdvancedDigitizingDockWidget"),
            None,
        )
        assert dock is None
    finally:
        s.shutdown()
